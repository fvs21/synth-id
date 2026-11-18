#!/usr/bin/env python3
"""Aplica el esquema del grafo: constraints e indices (Fase 1).

Correr ANTES del seed. Si se corre despues, los MERGE del seed ya habran
creado nodos PII duplicados y el grafo no se conectara.

Uso:
    python scripts/init_db.py
    python scripts/init_db.py --mostrar
"""

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.db import cerrar_driver  # noqa: E402
from src.schema import aplicar_esquema, listar_esquema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Aplica el esquema de SynthID.")
    parser.add_argument(
        "--mostrar",
        action="store_true",
        help="Solo lista el esquema vigente, sin modificar nada.",
    )
    args = parser.parse_args()

    try:
        if args.mostrar:
            esquema = listar_esquema()
            for seccion in ("constraints", "indices"):
                print("\n{} ({})".format(seccion.upper(), len(esquema[seccion])))
                for fila in esquema[seccion]:
                    print("  {:<28} {} {} [{}]".format(
                        fila["name"],
                        fila["labelsOrTypes"],
                        fila["properties"],
                        fila["type"],
                    ))
            return 0

        print("Aplicando esquema...")
        aplicar_esquema()

        esquema = listar_esquema()
        print("\nEsquema vigente: {} constraints, {} indices".format(
            len(esquema["constraints"]), len(esquema["indices"])
        ))
        print("\nSiguiente paso:  python scripts/seed.py")
        return 0

    finally:
        cerrar_driver()


if __name__ == "__main__":
    raise SystemExit(main())
