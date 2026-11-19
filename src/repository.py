"""Acceso a datos: el CRUD completo de solicitudes.

El PII no es propiedad de la solicitud sino nodo propio, insertado con MERGE:
si el telefono ya existe, la nueva solicitud se cuelga del mismo nodo y la red
de atributos compartidos se teje sola en el alta.
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
    fecha: str  # ISO-8601
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
    """Llave unica de una sola propiedad, normalizada.

    Normalizar evita que 'Av.  Reforma 12' y 'av. reforma 12' partan un
    anillo en dos componentes.
    """
    partes = [re.sub(r"\s+", " ", p).strip().upper() for p in (calle, cp, ciudad)]
    return "|".join(partes)


CYPHER_CREAR_SOLICITUD = """
// Persona y su CURP
MERGE (p:Persona {id: $persona_id})
  ON CREATE SET p.nombre_completo  = $nombre_completo,
                p.fecha_nacimiento = date($fecha_nacimiento)
MERGE (c:Curp {valor: $curp})
MERGE (p)-[:TIENE_CURP]->(c)

// La solicitud
MERGE (s:Solicitud {id: $id})
  ON CREATE SET s.fecha            = date($fecha),
                s.monto_solicitado = $monto_solicitado,
                s.estatus          = $estatus,
                s.score_riesgo     = null
MERGE (s)-[:PRESENTADA_POR]->(p)

// Atributos de identidad: cada uno es un nodo compartible
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
    """Alta por lotes: una transaccion cada `tamano`, no una por solicitud.

    Cada round-trip a Aura cuesta decenas de milisegundos.
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
    """Conteo por etiqueta y total de relaciones."""
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


# --------------------------------------------------------------------------
# READ
# --------------------------------------------------------------------------
def obtener_solicitud(solicitud_id: str) -> Optional[Dict[str, Any]]:
    """La solicitud con todo su PII, a un salto."""
    filas = ejecutar_lectura(
        """
        MATCH (s:Solicitud {id: $id})-[:PRESENTADA_POR]->(p:Persona)
        OPTIONAL MATCH (p)-[:TIENE_CURP]->(c:Curp)
        OPTIONAL MATCH (p)-[:TRABAJA_EN]->(emp:Empleador)
        OPTIONAL MATCH (s)-[:USA_TELEFONO]->(t:Telefono)
        OPTIONAL MATCH (s)-[:USA_EMAIL]->(e:Email)
        OPTIONAL MATCH (s)-[:RESIDE_EN]->(d:Domicilio)
        OPTIONAL MATCH (s)-[:ORIGINADA_EN]->(dev:Dispositivo)
        OPTIONAL MATCH (s)-[:DEPOSITO_A]->(b:CuentaBanco)
        RETURN s.id               AS id,
               toString(s.fecha)  AS fecha,
               s.monto_solicitado AS monto_solicitado,
               s.estatus          AS estatus,
               s.score_riesgo     AS score_riesgo,
               p.id               AS persona_id,
               p.nombre_completo  AS solicitante,
               toString(p.fecha_nacimiento) AS fecha_nacimiento,
               c.valor            AS curp,
               t.numero           AS telefono,
               e.direccion        AS email,
               d.calle            AS calle,
               d.cp               AS cp,
               d.ciudad           AS ciudad,
               dev.fingerprint    AS dispositivo,
               dev.tipo           AS tipo_dispositivo,
               b.clabe            AS cuenta_deposito,
               emp.nombre         AS empleador
        """,
        id=solicitud_id,
    )
    return filas[0] if filas else None


def listar_solicitudes(
    limite: int = 20,
    desplazamiento: int = 0,
    estatus: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Listado paginado, opcionalmente filtrado por estatus."""
    if estatus is not None and estatus not in ESTATUS_VALIDOS:
        raise ValueError(
            "Estatus invalido: {!r}. Validos: {}".format(
                estatus, ", ".join(ESTATUS_VALIDOS)
            )
        )

    return ejecutar_lectura(
        """
        MATCH (s:Solicitud)
        WHERE $estatus IS NULL OR s.estatus = $estatus
        MATCH (s)-[:PRESENTADA_POR]->(p:Persona)
        RETURN s.id               AS id,
               toString(s.fecha)  AS fecha,
               s.monto_solicitado AS monto_solicitado,
               s.estatus          AS estatus,
               s.score_riesgo     AS score_riesgo,
               p.nombre_completo  AS solicitante
        ORDER BY s.id
        SKIP $desplazamiento
        LIMIT $limite
        """,
        estatus=estatus,
        desplazamiento=desplazamiento,
        limite=limite,
    )


def contar_solicitudes(estatus: Optional[str] = None) -> int:
    filas = ejecutar_lectura(
        """
        MATCH (s:Solicitud)
        WHERE $estatus IS NULL OR s.estatus = $estatus
        RETURN count(s) AS total
        """,
        estatus=estatus,
    )
    return filas[0]["total"] if filas else 0


# --------------------------------------------------------------------------
# UPDATE
# --------------------------------------------------------------------------
def actualizar_estatus(solicitud_id: str, estatus: str) -> Optional[Dict[str, Any]]:
    """Registra la decision del analista."""
    if estatus not in ESTATUS_VALIDOS:
        raise ValueError(
            "Estatus invalido: {!r}. Validos: {}".format(
                estatus, ", ".join(ESTATUS_VALIDOS)
            )
        )

    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud {id: $id})
        SET s.estatus = $estatus
        RETURN s.id AS id, s.estatus AS estatus
        """,
        id=solicitud_id,
        estatus=estatus,
    )
    return filas[0] if filas else None


def guardar_score(solicitud_id: str, score: float) -> Optional[Dict[str, Any]]:
    """Persiste el score calculado por el modulo de deteccion."""
    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud {id: $id})
        SET s.score_riesgo = $score
        RETURN s.id AS id, s.score_riesgo AS score_riesgo
        """,
        id=solicitud_id,
        score=score,
    )
    return filas[0] if filas else None


def actualizar_telefono(
    solicitud_id: str, telefono: str
) -> Optional[Dict[str, Any]]:
    """Reapunta USA_TELEFONO a otro nodo, en lugar de sobreescribir un campo.

    La solicitud cambia de vecindario, asi que su riesgo puede cambiar sin
    que nada mas en el grafo se haya tocado.
    """
    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud {id: $id})-[r:USA_TELEFONO]->(viejo:Telefono)
        MERGE (nuevo:Telefono {numero: $telefono})
        DELETE r
        MERGE (s)-[:USA_TELEFONO]->(nuevo)
        RETURN s.id        AS id,
               viejo.numero AS telefono_anterior,
               nuevo.numero AS telefono_nuevo
        """,
        id=solicitud_id,
        telefono=telefono,
    )
    return filas[0] if filas else None


# --------------------------------------------------------------------------
# DELETE
# --------------------------------------------------------------------------
def eliminar_solicitud(solicitud_id: str) -> Optional[str]:
    """Borra la solicitud y sus relaciones, no su PII.

    Un telefono puede seguir vivo porque otra solicitud lo usa; lo que queda
    sin dueno lo limpia `purgar_huerfanos()`.
    """
    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud {id: $id})
        WITH s, s.id AS id
        DETACH DELETE s
        RETURN id
        """,
        id=solicitud_id,
    )
    return filas[0]["id"] if filas else None


def purgar_huerfanos() -> Dict[str, int]:
    """Elimina personas y PII que quedaron sin solicitud.

    Primero las personas: al irse dejan huerfanos su CURP y su empleador.
    """
    personas = ejecutar_escritura(
        """
        MATCH (p:Persona)
        WHERE NOT (p)<-[:PRESENTADA_POR]-()
        WITH p, count(*) AS _
        DETACH DELETE p
        RETURN count(*) AS eliminados
        """
    )

    pii = ejecutar_escritura(
        """
        MATCH (n)
        WHERE (n:Telefono OR n:Email OR n:Domicilio OR n:Dispositivo
               OR n:CuentaBanco OR n:Curp OR n:Empleador)
          AND NOT ()-->(n)
        DELETE n
        RETURN count(*) AS eliminados
        """
    )

    return {
        "personas": personas[0]["eliminados"] if personas else 0,
        "nodos_pii": pii[0]["eliminados"] if pii else 0,
    }
