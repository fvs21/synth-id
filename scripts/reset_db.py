#!/usr/bin/env python3
"""Borra TODOS los datos del grafo. Destructivo, pide confirmacion.

Conserva el esquema salvo que se pase --todo.

Uso:
    python scripts/reset_db.py
    python scripts/reset_db.py --todo
    python scripts/reset_db.py --si      # sin preguntar (para automatizacion)
"""

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.config import cargar_settings  # noqa: E402
from src.db import cerrar_driver, ejecutar_escritura, ejecutar_lectura  # noqa: E402
from src.schema import listar_esquema  # noqa: E402


def borrar_datos(tamano_lote: int = 10_000) -> int:
    """Borra nodos y relaciones por lotes, para no agotar la memoria."""
    borrados = 0
    while True:
        filas = ejecutar_escritura(
            """
            MATCH (n)
            WITH n LIMIT $limite
            DETACH DELETE n
            RETURN count(*) AS borrados
            """,
            limite=tamano_lote,
        )
        n = filas[0]["borrados"] if filas else 0
        borrados += n
        if n == 0:
            return borrados


def borrar_esquema() -> int:
    esquema = listar_esquema()
    total = 0
    for fila in esquema["constraints"]:
        ejecutar_escritura("DROP CONSTRAINT {} IF EXISTS".format(fila["name"]))
        total += 1
    for fila in esquema["indices"]:
        # Los que respaldan una constraint ya se fueron con ella.
        try:
            ejecutar_escritura("DROP INDEX {} IF EXISTS".format(fila["name"]))
            total += 1
        except Exception:  # noqa: BLE001
            pass
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Vacia la base de SynthID.")
    parser.add_argument(
        "--todo",
        action="store_true",
        help="Tambien elimina constraints e indices.",
    )
    parser.add_argument(
        "--si", action="store_true", help="No pedir confirmacion."
    )
    args = parser.parse_args()

    try:
        settings = cargar_settings()
        filas = ejecutar_lectura("MATCH (n) RETURN count(n) AS total")
        total_nodos = filas[0]["total"] if filas else 0

        print("Instancia : {}".format(settings.uri))
        print("Nodos     : {}".format(total_nodos))
        print("Alcance   : {}".format(
            "datos + esquema" if args.todo else "solo datos"
        ))

        if total_nodos == 0 and not args.todo:
            print("\nLa base ya esta vacia. Nada que hacer.")
            return 0

        if not args.si:
            print("\nEsta operacion NO se puede deshacer.")
            respuesta = input("Escribe BORRAR para continuar: ").strip()
            if respuesta != "BORRAR":
                print("Cancelado.")
                return 1

        borrados = borrar_datos()
        print("\n[ok] {} nodos eliminados".format(borrados))

        if args.todo:
            n = borrar_esquema()
            print("[ok] {} objetos de esquema eliminados".format(n))
            print("\nSiguiente paso:  python scripts/init_db.py")
        else:
            print("\nSiguiente paso:  python scripts/seed.py")

        return 0

    finally:
        cerrar_driver()


if __name__ == "__main__":
    raise SystemExit(main())
