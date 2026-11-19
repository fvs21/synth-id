"""Las seis consultas especializadas de grafo.

Los traversals recorren solo `REL_PII`: `TRABAJA_EN` queda fuera porque
cientos de personas comparten empleador y eso conecta el grafo entero
(medido a 8 saltos: 0 solicitudes alcanzadas sin esa relacion, 98 con ella).
Las cotas se interpolan porque Cypher no acepta `*1..$n`.
"""

from typing import Any, Dict, List, Optional

from src.db import ejecutar_lectura

# Relaciones a atributos identificadores.
REL_PII = (
    "USA_TELEFONO|USA_EMAIL|RESIDE_EN|ORIGINADA_EN|DEPOSITO_A"
    "|PRESENTADA_POR|TIENE_CURP"
)

# Etiquetas de PII y la propiedad que las identifica.
PROPIEDAD_PII = {
    "Telefono": "numero",
    "Email": "direccion",
    "Domicilio": "clave",
    "Dispositivo": "fingerprint",
    "CuentaBanco": "clabe",
    "Curp": "valor",
}

# Tipos colgados de la Solicitud. `Curp` no esta: pende de la Persona.
HUBS_SOPORTADOS = {
    "Telefono": "USA_TELEFONO",
    "Email": "USA_EMAIL",
    "Domicilio": "RESIDE_EN",
    "Dispositivo": "ORIGINADA_EN",
    "CuentaBanco": "DEPOSITO_A",
}

_FILTRO_PII = " OR ".join("pii:{}".format(e) for e in PROPIEDAD_PII)
_VALOR_PII = "coalesce({})".format(
    ", ".join("pii.{}".format(p) for p in PROPIEDAD_PII.values())
)


def _cota(valor: int, maximo: int = 12) -> int:
    """Valida una profundidad antes de interpolarla en el Cypher."""
    entero = int(valor)
    if not 1 <= entero <= maximo:
        raise ValueError(
            "Profundidad fuera de rango: {} (permitido 1..{})".format(
                entero, maximo
            )
        )
    return entero


# --------------------------------------------------------------------------
# 1. Vecindad: con quien comparte atributos esta solicitud
# --------------------------------------------------------------------------
def atributos_compartidos(solicitud_id: str) -> List[Dict[str, Any]]:
    """Atributos de identidad que esta solicitud comparte con otras.

    Usa `*1..2` porque la CURP pende de la Persona, no de la Solicitud.
    """
    return ejecutar_lectura(
        """
        MATCH (s:Solicitud {{id: $id}})-[:{rel}*1..2]->(pii)
        WHERE {filtro}
        WITH DISTINCT pii
        MATCH (otra:Solicitud)-[:{rel}*1..2]->(pii)
        WHERE otra.id <> $id
        RETURN labels(pii)[0]          AS tipo,
               {valor}                 AS valor,
               count(DISTINCT otra)    AS comparten,
               collect(DISTINCT otra.id)[..10] AS solicitudes
        ORDER BY comparten DESC, tipo
        """.format(rel=REL_PII, filtro=_FILTRO_PII, valor=_VALOR_PII),
        id=solicitud_id,
    )


# --------------------------------------------------------------------------
# 2. El anillo completo: traversal de longitud variable
# --------------------------------------------------------------------------
def anillo_de(solicitud_id: str, profundidad: int = 8) -> List[Dict[str, Any]]:
    """Solicitudes conectadas a esta, hasta `profundidad` saltos.

    Una sola clausula devuelve el cluster completo, esten a 2 o a 8 saltos.
    """
    return ejecutar_lectura(
        """
        MATCH (s:Solicitud {{id: $id}})-[:{rel}*1..{n}]-(otra:Solicitud)
        WHERE otra.id <> $id
        RETURN DISTINCT otra.id        AS id,
               otra.estatus            AS estatus,
               otra.score_riesgo       AS score_riesgo
        ORDER BY id
        """.format(rel=REL_PII, n=_cota(profundidad)),
        id=solicitud_id,
    )


def personas_del_anillo(
    solicitud_id: str, profundidad: int = 8
) -> List[Dict[str, Any]]:
    """Nombres del anillo, incluido el de origen. Lo usa la regla familiar."""
    return ejecutar_lectura(
        """
        MATCH (s:Solicitud {{id: $id}})
        OPTIONAL MATCH (s)-[:{rel}*1..{n}]-(otra:Solicitud)
        WHERE otra.id <> $id
        WITH collect(DISTINCT otra) + collect(DISTINCT s) AS solicitudes
        UNWIND solicitudes AS sol
        MATCH (sol)-[:PRESENTADA_POR]->(p:Persona)
        RETURN DISTINCT sol.id AS solicitud, p.nombre_completo AS nombre
        ORDER BY solicitud
        """.format(rel=REL_PII, n=_cota(profundidad)),
        id=solicitud_id,
    )


# --------------------------------------------------------------------------
# 3. Camino mas corto: la cadena de evidencia
# --------------------------------------------------------------------------
def ruta_entre(
    solicitud_a: str, solicitud_b: str, max_saltos: int = 10
) -> Optional[Dict[str, Any]]:
    """Camino mas corto entre dos solicitudes: la cadena de evidencia.

    Cada salto es un dato verificable, asi que el resultado ES la evidencia.
    """
    filas = ejecutar_lectura(
        """
        MATCH (a:Solicitud {{id: $a}}), (b:Solicitud {{id: $b}})
        MATCH ruta = shortestPath((a)-[:{rel}*..{n}]-(b))
        RETURN length(ruta) AS saltos,
               [nodo IN nodes(ruta) | {{
                   tipo:  labels(nodo)[0],
                   valor: coalesce(nodo.id, nodo.numero, nodo.direccion,
                                   nodo.clave, nodo.fingerprint, nodo.clabe,
                                   nodo.valor, nodo.nombre_completo)
               }}] AS cadena
        """.format(rel=REL_PII, n=_cota(max_saltos)),
        a=solicitud_a,
        b=solicitud_b,
    )
    return filas[0] if filas else None


# --------------------------------------------------------------------------
# 4. La firma de la identidad sintetica
# --------------------------------------------------------------------------
def curps_multiples(min_variantes: int = 2) -> List[Dict[str, Any]]:
    """CURPs usadas por mas de un nombre: un dato real con nombres inventados."""
    return ejecutar_lectura(
        """
        MATCH (c:Curp)<-[:TIENE_CURP]-(p:Persona)
        WITH c, collect(DISTINCT p.nombre_completo) AS nombres
        WHERE size(nombres) >= $minimo
        RETURN c.valor      AS curp,
               size(nombres) AS variantes,
               nombres
        ORDER BY variantes DESC, curp
        """,
        minimo=min_variantes,
    )


# --------------------------------------------------------------------------
# 5. Nodos hub: atributos con grado anomalo
# --------------------------------------------------------------------------
def hubs(tipo: str, minimo_personas: int = 3) -> List[Dict[str, Any]]:
    """Atributos usados por `minimo_personas` personas distintas o mas."""
    if tipo not in HUBS_SOPORTADOS:
        raise ValueError(
            "Tipo no soportado: {!r}. Validos: {}".format(
                tipo, ", ".join(sorted(HUBS_SOPORTADOS))
            )
        )

    return ejecutar_lectura(
        """
        MATCH (n:{etiqueta})<-[:{rel}]-(s:Solicitud)-[:PRESENTADA_POR]->(p:Persona)
        WITH n, count(DISTINCT s) AS solicitudes,
                count(DISTINCT p) AS personas,
                collect(DISTINCT p.nombre_completo)[..10] AS nombres,
                collect(DISTINCT s.id)[..10] AS ids
        WHERE personas >= $minimo
        RETURN n.{prop}  AS valor,
               solicitudes,
               personas,
               nombres,
               ids       AS solicitudes_ids
        ORDER BY personas DESC, valor
        """.format(
            etiqueta=tipo,
            rel=HUBS_SOPORTADOS[tipo],
            prop=PROPIEDAD_PII[tipo],
        ),
        minimo=minimo_personas,
    )


# --------------------------------------------------------------------------
# 6. Barrido global: todos los atributos compartidos de la base
# --------------------------------------------------------------------------
def anillos_globales(min_solicitudes: int = 2) -> List[Dict[str, Any]]:
    """Barrido de la base: todo atributo compartido por varias solicitudes.

    A escala de produccion el equivalente seria Weakly Connected Components
    con GDS; esta version no necesita el plugin.
    """
    return ejecutar_lectura(
        """
        MATCH (s:Solicitud)-[:{rel}*1..2]->(pii)
        WHERE {filtro}
        WITH pii,
             collect(DISTINCT s.id) AS solicitudes
        WHERE size(solicitudes) >= $minimo
        RETURN labels(pii)[0] AS tipo,
               {valor}        AS valor,
               size(solicitudes) AS n,
               solicitudes
        ORDER BY n DESC, tipo
        """.format(rel=REL_PII, filtro=_FILTRO_PII, valor=_VALOR_PII),
        minimo=min_solicitudes,
    )
