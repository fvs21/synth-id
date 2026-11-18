#!/usr/bin/env python3
"""Verifica que la instancia de AuraDB en la nube responde (Fase 0).

Es el primer script que debes correr. Si esto funciona, el resto del
proyecto tiene con que trabajar.

Uso:
    python scripts/check_conexion.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.config import ConfiguracionInvalida, cargar_settings  # noqa: E402
from src.db import cerrar_driver, ejecutar_lectura, verificar_conectividad  # noqa: E402


def main() -> int:
    try:
        settings = cargar_settings()
    except ConfiguracionInvalida as error:
        print("[X] Configuracion invalida\n")
        print(error)
        return 1

    # El password nunca se imprime.
    print("URI      : {}".format(settings.uri))
    print("Usuario  : {}".format(settings.user))
    print("Database : {}".format(settings.database or "(home database)"))
    print()

    try:
        info = verificar_conectividad()
        print("[ok] Conexion establecida")
        if info:
            print("     {} {} ({})".format(
                info.get("componente", "neo4j"),
                info.get("version", "?"),
                info.get("edicion", "?"),
            ))

        filas = ejecutar_lectura("RETURN 1 AS prueba")
        print("[ok] Consulta de prueba: RETURN 1 -> {}".format(filas[0]["prueba"]))
        return 0

    except Exception as error:  # noqa: BLE001 - diagnostico para el usuario
        texto = str(error)

        if "Unauthorized" in texto or "authentication failure" in texto:
            # Llegamos al servidor y nos rechazo: la instancia existe, esta
            # despierta y el URI es correcto. Lo unico que falla es el password.
            print("[X] Credenciales rechazadas por el servidor")
            print()
            print("La instancia responde (el URI es correcto y NO esta pausada),")
            print("pero el usuario o el password no son los suyos.")
            print()
            print("Revisa, en este orden:")
            print("  1. Que NEO4J_USERNAME sea EXACTAMENTE el del archivo que")
            print("     descargaste de Aura. En AuraDB el usuario suele ser el")
            print("     ID de la instancia, no 'neo4j': no lo 'corrijas'.")
            print("  2. Que el .env sea de ESTA instancia y no de una anterior")
            print("     (compara el host del URI con el ID en console.neo4j.io).")
            print("  3. Que no sea una instancia recien creada: Aura pide")
            print("     esperar unos minutos antes de conectarse.")
            print("  4. Si perdiste el password: console.neo4j.io -> la")
            print("     instancia -> Reset password.")
            return 1

        print("[X] No se pudo conectar: {}".format(error))
        print()
        print("Revisa:")
        print("  1. Que la instancia de Aura NO este pausada (se pausa tras")
        print("     3 dias de inactividad). Entra a console.neo4j.io y")
        print("     presiona 'Resume'.")
        print("  2. Que el URI del .env sea el de la instancia.")
        print("  3. Que tengas conexion a internet.")
        return 1

    finally:
        cerrar_driver()


if __name__ == "__main__":
    raise SystemExit(main())
