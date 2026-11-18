"""Esquema del grafo: constraints de unicidad e indices.

Fase 1 del plan.

NOTA DE DISENO (importante para la defensa del proyecto)
---------------------------------------------------------
Las constraints de unicidad no son un adorno: son el mecanismo que hace que
`MERGE (t:Telefono {numero: ...})` REUTILICE el nodo existente en lugar de
crear un duplicado. Sin ellas el grafo nunca se conecta, cada solicitud queda
en su propia isla y NINGUNA consulta de deteccion encuentra nada.

Se usa unicidad de UNA sola propiedad porque las node key compuestas son
exclusivas de Neo4j Enterprise. Para `Domicilio`, que naturalmente seria una
llave compuesta (calle + cp + ciudad), se deriva una propiedad `clave`
normalizada y la unicidad se aplica sobre ella.
"""

from typing import Any, Dict, List

from src.db import ejecutar_escritura, ejecutar_lectura

CONSTRAINTS: List[str] = [
    "CREATE CONSTRAINT solicitud_id IF NOT EXISTS "
    "FOR (s:Solicitud) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT persona_id IF NOT EXISTS "
    "FOR (p:Persona) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT curp_valor IF NOT EXISTS "
    "FOR (c:Curp) REQUIRE c.valor IS UNIQUE",
    "CREATE CONSTRAINT telefono_numero IF NOT EXISTS "
    "FOR (t:Telefono) REQUIRE t.numero IS UNIQUE",
    "CREATE CONSTRAINT email_direccion IF NOT EXISTS "
    "FOR (e:Email) REQUIRE e.direccion IS UNIQUE",
    "CREATE CONSTRAINT domicilio_clave IF NOT EXISTS "
    "FOR (d:Domicilio) REQUIRE d.clave IS UNIQUE",
    "CREATE CONSTRAINT dispositivo_fingerprint IF NOT EXISTS "
    "FOR (d:Dispositivo) REQUIRE d.fingerprint IS UNIQUE",
    "CREATE CONSTRAINT cuenta_clabe IF NOT EXISTS "
    "FOR (b:CuentaBanco) REQUIRE b.clabe IS UNIQUE",
    "CREATE CONSTRAINT empleador_nombre IF NOT EXISTS "
    "FOR (e:Empleador) REQUIRE e.nombre IS UNIQUE",
]

INDICES: List[str] = [
    "CREATE INDEX solicitud_fecha IF NOT EXISTS FOR (s:Solicitud) ON (s.fecha)",
    "CREATE INDEX solicitud_estatus IF NOT EXISTS FOR (s:Solicitud) ON (s.estatus)",
    "CREATE INDEX solicitud_score IF NOT EXISTS FOR (s:Solicitud) ON (s.score_riesgo)",
    "CREATE INDEX persona_nombre IF NOT EXISTS FOR (p:Persona) ON (p.nombre_completo)",
]


def aplicar_esquema(verboso: bool = True) -> None:
    """Crea constraints e indices. Idempotente (IF NOT EXISTS)."""
    for sentencia in CONSTRAINTS + INDICES:
        ejecutar_escritura(sentencia)
        if verboso:
            nombre = sentencia.split()[2]
            tipo = "constraint" if "CONSTRAINT" in sentencia else "index"
            print("  [ok] {:<10} {}".format(tipo, nombre))


def listar_esquema() -> Dict[str, List[Dict[str, Any]]]:
    """Devuelve el esquema vigente en la instancia, para verificacion."""
    constraints = ejecutar_lectura(
        "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties, type "
        "RETURN name, labelsOrTypes, properties, type ORDER BY name"
    )
    indices = ejecutar_lectura(
        "SHOW INDEXES YIELD name, labelsOrTypes, properties, type "
        "RETURN name, labelsOrTypes, properties, type ORDER BY name"
    )
    return {"constraints": constraints, "indices": indices}
