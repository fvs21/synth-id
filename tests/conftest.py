"""Configuracion de pytest: hace importable `src` y carga la referencia.

Son tests de INTEGRACION contra la instancia real, con el seed ya cargado:
lo que hay que verificar es el Cypher corriendo en el motor, no un mock.
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
    """Anillos sembrados, indexados por letra."""
    if not REFERENCIA.exists():
        pytest.skip(
            "Falta {}. Corre antes: python scripts/seed.py".format(REFERENCIA)
        )
    datos = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    return {meta["anillo"]: meta for meta in datos}


@pytest.fixture(scope="session", autouse=True)
def _cierra_driver():
    """Cierra el pool al terminar la sesion."""
    yield
    from src.db import cerrar_driver

    cerrar_driver()
