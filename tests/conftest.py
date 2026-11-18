"""Configuracion de pytest: hace importable `src` y carga la referencia.

Estos son tests de INTEGRACION: hablan con la instancia real de AuraDB
configurada en el .env y esperan que el seed ya este cargado. No son tests
unitarios con mocks, porque lo que hay que verificar es precisamente que el
Cypher se comporta como se cree contra el motor real.
"""

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

REFERENCIA = RAIZ / "docs" / "anillos_sembrados.json"


@pytest.fixture(scope="session")
def anillos():
    """Metadata de los anillos sembrados, indexada por letra."""
    if not REFERENCIA.exists():
        pytest.skip(
            "Falta {}. Corre antes: python scripts/seed.py".format(REFERENCIA)
        )
    datos = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    return {meta["anillo"]: meta for meta in datos}


@pytest.fixture(scope="session", autouse=True)
def _cierra_driver():
    """Cierra el pool de conexiones al terminar la sesion de tests."""
    yield
    from src.db import cerrar_driver

    cerrar_driver()
