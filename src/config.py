"""Carga y validacion de la configuracion desde el archivo .env.

Fase 0 del plan. Si falta una credencial el programa falla de inmediato con
un mensaje claro, en lugar de reventar mas adelante con un error de
autenticacion del driver que no dice nada util.

LECCION APRENDIDA (verificado contra una instancia real)
---------------------------------------------------------
El archivo de credenciales que descarga Aura es correcto tal cual: no hay que
editarlo ni "corregirlo". En la instancia probada, el usuario y la base de
datos NO se llaman 'neo4j' sino como el ID de la instancia (p.ej. ab0cd36a);
`SHOW DATABASES` confirma que la unica base de usuario es ab0cd36a y que no
existe ninguna llamada 'neo4j'.

Por eso este modulo NO normaliza ni adivina esos valores: usa exactamente lo
que dice el archivo. Si alguna vez conectas contra un Neo4j propio donde la
base se llama 'neo4j', basta con que el .env lo diga.
"""

import os
from pathlib import Path
from typing import NamedTuple, Optional

from dotenv import load_dotenv

# Raiz del proyecto (un nivel arriba de src/)
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_ENV = RAIZ_PROYECTO / ".env"


class Settings(NamedTuple):
    """Credenciales de conexion a AuraDB."""

    uri: str
    user: str
    password: str
    # None = usar la "home database" que la instancia tenga configurada.
    database: Optional[str]


class ConfiguracionInvalida(RuntimeError):
    """Falta alguna variable de entorno obligatoria."""


def _leer(*nombres: str) -> str:
    """Primer valor no vacio entre varios nombres de variable.

    Aura nombra al usuario NEO4J_USERNAME en el archivo que descarga; otros
    ejemplos de la documentacion usan NEO4J_USER. Se aceptan los dos para que
    el archivo descargado funcione sin editarse.
    """
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
