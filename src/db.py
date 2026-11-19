"""Capa de conexion al driver oficial de Neo4j.

El driver es costoso y thread-safe: uno por proceso, con su propio pool. Las
sesiones son baratas: una por unidad de trabajo.
"""

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from neo4j import Driver, GraphDatabase, Session

from src.config import Settings, cargar_settings

_driver: Optional[Driver] = None
_settings: Optional[Settings] = None


def obtener_driver() -> Driver:
    """Devuelve el driver compartido, creandolo en el primer uso."""
    global _driver, _settings

    if _driver is None:
        _settings = cargar_settings()
        _driver = GraphDatabase.driver(
            _settings.uri,
            auth=(_settings.user, _settings.password),
            connection_timeout=30.0,  # una instancia pausada tarda en despertar
            max_connection_lifetime=3600,
        )

    return _driver


def obtener_database() -> Optional[str]:
    """Base destino segun el .env. None = home database de la instancia."""
    if _settings is None:
        obtener_driver()
    assert _settings is not None
    return _settings.database


def cerrar_driver() -> None:
    """Cierra el driver y libera el pool, al terminar el proceso."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


@contextmanager
def sesion() -> Iterator[Session]:
    """Context manager de sesion contra la base configurada."""
    driver = obtener_driver()
    with driver.session(database=obtener_database()) as s:
        yield s


def ejecutar_lectura(cypher: str, **params: Any) -> List[Dict[str, Any]]:
    """Corre una consulta de lectura y devuelve los registros como dicts."""
    with sesion() as s:
        resultado = s.execute_read(
            lambda tx: [registro.data() for registro in tx.run(cypher, **params)]
        )
    return resultado


def ejecutar_escritura(cypher: str, **params: Any) -> List[Dict[str, Any]]:
    """Escritura en transaccion gestionada: reintenta fallos de red."""
    with sesion() as s:
        resultado = s.execute_write(
            lambda tx: [registro.data() for registro in tx.run(cypher, **params)]
        )
    return resultado


def verificar_conectividad() -> Dict[str, Any]:
    """Confirma que la instancia en la nube responde."""
    driver = obtener_driver()
    driver.verify_connectivity()

    # La version es informativa: si Aura no expone el procedimiento, no es
    # un fallo de conectividad.
    try:
        filas = ejecutar_lectura(
            """
            CALL dbms.components() YIELD name, versions, edition
            RETURN name AS componente, versions[0] AS version, edition AS edicion
            """
        )
        return filas[0] if filas else {}
    except Exception:  # noqa: BLE001
        return {}
