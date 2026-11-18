"""Acceso a datos: alta de solicitudes y utilidades de conteo.

Aqui vive la operacion CREATE del CRUD (el resto -- read, update, delete --
se agrega en la Fase 3). El seed la reutiliza en lugar de duplicar Cypher.

EL PATRON CLAVE
---------------
El PII no se guarda como propiedad de la solicitud sino como NODO propio, y
se inserta con MERGE. Eso significa que si el telefono ya existe en el grafo,
la nueva solicitud se cuelga del mismo nodo: la red de atributos compartidos
se teje sola en el momento del alta, sin que el codigo tenga que buscar
coincidencias ni mantener tablas de enlace.
"""

import re
from typing import Any, Dict, List, NamedTuple, Optional

from src.db import ejecutar_escritura, ejecutar_lectura

ESTATUS_VALIDOS = (
    "EN_REVISION",
    "APROBADA",
    "RECHAZADA",
    "FRAUDE_CONFIRMADO",
)


class SolicitudNueva(NamedTuple):
    """Datos de una solicitud de credito tal como llegan del formulario."""

    id: str
    fecha: str  # ISO-8601, p.ej. "2026-03-14"
    monto_solicitado: float
    persona_id: str
    nombre_completo: str
    fecha_nacimiento: str  # ISO-8601
    curp: str
    telefono: str
    email: str
    calle: str
    cp: str
    ciudad: str
    fingerprint: str
    tipo_dispositivo: str
    clabe: str
    empleador: str
    estatus: str = "EN_REVISION"


def clave_domicilio(calle: str, cp: str, ciudad: str) -> str:
    """Normaliza un domicilio a una llave unica de una sola propiedad.

    Las node key compuestas requieren Neo4j Enterprise, asi que derivamos
    la llave aqui. Normalizar tambien evita que 'Av.  Reforma 12' y
    'av. reforma 12' se traten como domicilios distintos, lo que partiria
    un anillo de fraude en dos componentes.
    """
    partes = [re.sub(r"\s+", " ", p).strip().upper() for p in (calle, cp, ciudad)]
    return "|".join(partes)


CYPHER_CREAR_SOLICITUD = """
// --- Persona y su CURP ---------------------------------------------------
MERGE (p:Persona {id: $persona_id})
  ON CREATE SET p.nombre_completo  = $nombre_completo,
                p.fecha_nacimiento = date($fecha_nacimiento)
MERGE (c:Curp {valor: $curp})
MERGE (p)-[:TIENE_CURP]->(c)

// --- La solicitud --------------------------------------------------------
MERGE (s:Solicitud {id: $id})
  ON CREATE SET s.fecha            = date($fecha),
                s.monto_solicitado = $monto_solicitado,
                s.estatus          = $estatus,
                s.score_riesgo     = null
MERGE (s)-[:PRESENTADA_POR]->(p)

// --- Atributos de identidad, cada uno como nodo compartible --------------
MERGE (t:Telefono {numero: $telefono})
MERGE (s)-[:USA_TELEFONO]->(t)

MERGE (e:Email {direccion: $email})
MERGE (s)-[:USA_EMAIL]->(e)

MERGE (d:Domicilio {clave: $domicilio_clave})
  ON CREATE SET d.calle = $calle, d.cp = $cp, d.ciudad = $ciudad
MERGE (s)-[:RESIDE_EN]->(d)

MERGE (dev:Dispositivo {fingerprint: $fingerprint})
  ON CREATE SET dev.tipo = $tipo_dispositivo
MERGE (s)-[:ORIGINADA_EN]->(dev)

MERGE (b:CuentaBanco {clabe: $clabe})
MERGE (s)-[:DEPOSITO_A]->(b)

MERGE (emp:Empleador {nombre: $empleador})
MERGE (p)-[:TRABAJA_EN]->(emp)

RETURN s.id AS id
"""


def _parametros(solicitud: SolicitudNueva) -> Dict[str, Any]:
    if solicitud.estatus not in ESTATUS_VALIDOS:
        raise ValueError(
            "Estatus invalido: {!r}. Validos: {}".format(
                solicitud.estatus, ", ".join(ESTATUS_VALIDOS)
            )
        )

    params = solicitud._asdict()
    params["domicilio_clave"] = clave_domicilio(
        solicitud.calle, solicitud.cp, solicitud.ciudad
    )
    return params


def crear_solicitud(solicitud: SolicitudNueva) -> str:
    """Da de alta una solicitud con todo su PII. Idempotente por `id`."""
    filas = ejecutar_escritura(CYPHER_CREAR_SOLICITUD, **_parametros(solicitud))
    return filas[0]["id"]


CYPHER_CREAR_LOTE = """
UNWIND $lote AS fila

MERGE (p:Persona {id: fila.persona_id})
  ON CREATE SET p.nombre_completo  = fila.nombre_completo,
                p.fecha_nacimiento = date(fila.fecha_nacimiento)
MERGE (c:Curp {valor: fila.curp})
MERGE (p)-[:TIENE_CURP]->(c)

MERGE (s:Solicitud {id: fila.id})
  ON CREATE SET s.fecha            = date(fila.fecha),
                s.monto_solicitado = fila.monto_solicitado,
                s.estatus          = fila.estatus,
                s.score_riesgo     = null
MERGE (s)-[:PRESENTADA_POR]->(p)

MERGE (t:Telefono {numero: fila.telefono})
MERGE (s)-[:USA_TELEFONO]->(t)

MERGE (e:Email {direccion: fila.email})
MERGE (s)-[:USA_EMAIL]->(e)

MERGE (d:Domicilio {clave: fila.domicilio_clave})
  ON CREATE SET d.calle = fila.calle, d.cp = fila.cp, d.ciudad = fila.ciudad
MERGE (s)-[:RESIDE_EN]->(d)

MERGE (dev:Dispositivo {fingerprint: fila.fingerprint})
  ON CREATE SET dev.tipo = fila.tipo_dispositivo
MERGE (s)-[:ORIGINADA_EN]->(dev)

MERGE (b:CuentaBanco {clabe: fila.clabe})
MERGE (s)-[:DEPOSITO_A]->(b)

MERGE (emp:Empleador {nombre: fila.empleador})
MERGE (p)-[:TRABAJA_EN]->(emp)

RETURN count(s) AS creadas
"""


def crear_solicitudes_lote(solicitudes: List[SolicitudNueva], tamano: int = 50) -> int:
    """Alta por lotes: mucho mas rapido que una transaccion por solicitud.

    Cada ida y vuelta a Aura cuesta decenas de milisegundos. Mandar 400 altas
    de una en una son 400 round-trips; agruparlas en transacciones de ~50
    baja el tiempo del seed de minutos a segundos.
    """
    if not solicitudes:
        return 0

    filas = [_parametros(s) for s in solicitudes]
    total = 0
    for inicio in range(0, len(filas), tamano):
        bloque = filas[inicio : inicio + tamano]
        ejecutar_escritura(CYPHER_CREAR_LOTE, lote=bloque)
        total += len(bloque)
    return total


def contar_entidades() -> Dict[str, int]:
    """Conteo por etiqueta y total de relaciones. Para el reporte del seed."""
    filas = ejecutar_lectura(
        """
        MATCH (n)
        UNWIND labels(n) AS etiqueta
        RETURN etiqueta, count(*) AS total
        ORDER BY etiqueta
        """
    )
    conteo = {fila["etiqueta"]: fila["total"] for fila in filas}

    rels = ejecutar_lectura("MATCH ()-[r]->() RETURN count(r) AS total")
    conteo["_relaciones"] = rels[0]["total"] if rels else 0
    return conteo


def obtener_solicitud_cruda(solicitud_id: str) -> Optional[Dict[str, Any]]:
    """Lectura minima de una solicitud con su PII a un salto.

    Version reducida; la lectura completa del expediente llega en la Fase 3.
    """
    filas = ejecutar_lectura(
        """
        MATCH (s:Solicitud {id: $id})-[:PRESENTADA_POR]->(p:Persona)
        OPTIONAL MATCH (p)-[:TIENE_CURP]->(c:Curp)
        OPTIONAL MATCH (s)-[:USA_TELEFONO]->(t:Telefono)
        OPTIONAL MATCH (s)-[:USA_EMAIL]->(e:Email)
        OPTIONAL MATCH (s)-[:RESIDE_EN]->(d:Domicilio)
        OPTIONAL MATCH (s)-[:ORIGINADA_EN]->(dev:Dispositivo)
        OPTIONAL MATCH (s)-[:DEPOSITO_A]->(b:CuentaBanco)
        RETURN s.id              AS id,
               toString(s.fecha) AS fecha,
               s.monto_solicitado AS monto,
               s.estatus         AS estatus,
               s.score_riesgo    AS score_riesgo,
               p.nombre_completo AS solicitante,
               c.valor           AS curp,
               t.numero          AS telefono,
               e.direccion       AS email,
               d.calle + ', ' + d.ciudad AS domicilio,
               dev.fingerprint   AS dispositivo,
               b.clabe           AS cuenta_deposito
        """,
        id=solicitud_id,
    )
    return filas[0] if filas else None
