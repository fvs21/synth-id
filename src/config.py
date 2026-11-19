"""Carga y validacion de las credenciales desde el .env.

El archivo que descarga Aura se usa tal cual, sin normalizar: en AuraDB el
usuario y la base se llaman como el ID de la instancia, no 'neo4j'.
"""

import os
from pathlib import Path
from typing import NamedTuple, Optional

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_ENV = RAIZ_PROYECTO / ".env"


class Settings(NamedTuple):
    """Credenciales de conexion a AuraDB."""

    uri: str
    user: str
    password: str
    database: Optional[str]  # None = home database de la instancia


class ConfiguracionInvalida(RuntimeError):
    """Falta alguna variable de entorno obligatoria."""


def _leer(*nombres: str) -> str:
    """Primer valor no vacio entre varios nombres de variable."""
    for nombre in nombres:
        valor = os.getenv(nombre)
        if valor and valor.strip():
            return valor.strip()
    return ""


def cargar_settings() -> Settings:
    """Lee el .env y devuelve los settings validados."""
    load_dotenv(dotenv_path=RUTA_ENV, override=False)

    uri = _leer("NEO4J_URI")
    user = _leer("NEO4J_USERNAME", "NEO4J_USER")
    password = _leer("NEO4J_PASSWORD")

    faltantes = [
        nombre
        for nombre, valor in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", user),
            ("NEO4J_PASSWORD", password),
        )
        if not valor
    ]

    if faltantes:
        raise ConfiguracionInvalida(
            "Faltan variables de entorno: {}.\n"
            "Renombra a .env el archivo de credenciales que descargaste de "
            "Aura al crear la instancia (ya viene con este formato):\n"
            "    cp ~/Downloads/<archivo-de-aura> .env".format(
                ", ".join(faltantes)
            )
        )

    if not uri.startswith(
        ("neo4j+s://", "neo4j+ssc://", "bolt+s://", "neo4j://", "bolt://")
    ):
        raise ConfiguracionInvalida(
            "NEO4J_URI no parece valido: {!r}. "
            "Una instancia de AuraDB usa el esquema neo4j+s://".format(uri)
        )

    return Settings(
        uri=uri,
        user=user,
        password=password,
        database=_leer("NEO4J_DATABASE") or None,
    )
