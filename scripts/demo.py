#!/usr/bin/env python3
"""Recorrido narrado de SynthID para la evaluacion (Fase 5).

Seis pasos que muestran, en orden, el CRUD y las cuatro consultas de grafo
que justifican el paradigma. Cada paso imprime la pregunta de negocio, la
operacion y el resultado.

Las solicitudes que crea usan el prefijo SOL-DEMO y se borran al final, asi
que la base queda como estaba (427 solicitudes). Si el recorrido se
interrumpe a medias, `--limpiar` quita los restos.

Uso:
    python scripts/demo.py
    python scripts/demo.py --limpiar
    python scripts/demo.py --pausar     # espera Enter entre pasos
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import detection, repository, scoring  # noqa: E402
from src.db import cerrar_driver, ejecutar_escritura  # noqa: E402

REFERENCIA = RAIZ / "docs" / "anillos_sembrados.json"
PREFIJO = "SOL-DEMO-"
ANCHO = 74


# --------------------------------------------------------------------------
# Presentacion
# --------------------------------------------------------------------------
def titulo(n: int, texto: str) -> None:
    print("\n" + "=" * ANCHO)
    print("PASO {} - {}".format(n, texto))
    print("=" * ANCHO)


def pregunta(texto: str) -> None:
    print('\n  Pregunta de negocio: "{}"'.format(texto))


def operacion(texto: str) -> None:
    print("  Operacion: {}".format(texto))


def riesgo_en_claro(resultado: Dict[str, Any]) -> None:
    print(
        "\n  >>> {}  score {}  nivel {}".format(
            resultado["solicitud_id"], resultado["score"], resultado["nivel"]
        )
    )
    for motivo in resultado["motivos"]:
        print("      - {}".format(motivo))


def pausa(activa: bool) -> None:
    if activa:
        input("\n  [Enter para continuar]")


# --------------------------------------------------------------------------
# Datos de la demo
# --------------------------------------------------------------------------
def solicitud_demo(sufijo: str, **overrides) -> repository.SolicitudNueva:
    datos = dict(
        id="{}{}".format(PREFIJO, sufijo),
        fecha="2026-11-18",
        monto_solicitado=250_000.0,
        persona_id="PER-DEMO-{}".format(sufijo),
        nombre_completo="Demo Solicitante {}".format(sufijo),
        fecha_nacimiento="1992-05-14",
        curp="DEMO920514HDFXXX{}".format(sufijo),
        telefono="558800{}".format(sufijo.zfill(4)),
        email="demo{}@ejemplo.test".format(sufijo),
        calle="Avenida Demo {}".format(sufijo),
        cp="11000",
        ciudad="Ciudad de Mexico",
        fingerprint="demo{}".format(sufijo.zfill(12)),
        tipo_dispositivo="iPhone",
        clabe="8888{}".format(sufijo.zfill(14)),
        empleador="Empleador Demo",
    )
    datos.update(overrides)
    return repository.SolicitudNueva(**datos)


def limpiar() -> int:
    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud)
        WHERE s.id STARTS WITH $prefijo
        DETACH DELETE s
        RETURN count(*) AS eliminadas
        """,
        prefijo=PREFIJO,
    )
    repository.purgar_huerfanos()
    return filas[0]["eliminadas"] if filas else 0


# --------------------------------------------------------------------------
# Los seis pasos
# --------------------------------------------------------------------------
def paso_1_alta_limpia() -> None:
    titulo(1, "Alta de una solicitud legitima")
    pregunta("Llega una solicitud nueva. Le presto?")
    operacion("POST /solicitudes  ->  score calculado en el alta")

    repository.crear_solicitud(solicitud_demo("01"))
    resultado = scoring.evaluar("{}01".format(PREFIJO))
    repository.guardar_score("{}01".format(PREFIJO), resultado["score"])
    riesgo_en_claro(resultado)

    print("\n  Su PII no toca a nadie en el grafo. Decision: seguir el flujo")
    print("  normal de evaluacion crediticia.")


def paso_2_alta_en_anillo(anillos: Dict[str, Any]) -> None:
    titulo(2, "Alta de una solicitud que cae en un anillo")
    fingerprint = anillos["B"]["valor_compartido"]["Dispositivo"]

    pregunta("Llega otra solicitud, con expediente impecable. Le presto?")
    operacion(
        "la misma alta, pero el dispositivo ya existe en el grafo\n"
        "             (fingerprint {})".format(fingerprint)
    )

    repository.crear_solicitud(solicitud_demo("02", fingerprint=fingerprint))
    resultado = scoring.evaluar("{}02".format(PREFIJO))
    repository.guardar_score("{}02".format(PREFIJO), resultado["score"])
    riesgo_en_claro(resultado)

    print("\n  Nada en el expediente estaba mal: CURP valida, telefono propio,")
    print("  domicilio real. Lo que la delata es la RED, no el registro.")


def paso_3_traversal(anillos: Dict[str, Any]) -> None:
    titulo(3, "El anillo completo: traversal de longitud variable")
    origen = "{}02".format(PREFIJO)

    pregunta("Quienes mas estan dentro de esto?")
    operacion("GET /solicitudes/{}/anillo  ->  MATCH (s)-[:...*1..8]-(otra)".format(origen))

    miembros = detection.anillo_de(origen)
    print("\n  Alcanzadas desde {} en <=8 saltos: {}".format(origen, len(miembros)))
    for fila in miembros:
        print("      {}".format(fila["id"]))

    print("\n  Una sola clausula devolvio el cluster entero. En SQL esto exige")
    print("  un CTE recursivo sobre la union de cinco tablas puente, con")
    print("  control manual de nodos ya visitados.")


def paso_4_cadena_de_evidencia(anillos: Dict[str, Any]) -> None:
    titulo(4, "La cadena de evidencia: camino mas corto")
    extremos = anillos["C"]["extremos"]

    pregunta(
        "{} y {} dicen no conocerse. Como se conectan?".format(
            extremos["desde"], extremos["hasta"]
        )
    )
    operacion("GET /investigacion/ruta  ->  shortestPath()")

    ruta = detection.ruta_entre(extremos["desde"], extremos["hasta"])
    print("\n  {} saltos:\n".format(ruta["saltos"]))
    for i, paso in enumerate(ruta["cadena"]):
        flecha = "      " if i == 0 else "        |\n        v\n      "
        print("{}{:<12} {}".format(flecha, paso["tipo"], paso["valor"]))

    print("\n  No comparten NINGUN atributo directo. El camino es la evidencia")
    print("  que se lleva al comite: cada salto es un dato verificable.")


def paso_5_alertas(anillos: Dict[str, Any]) -> None:
    titulo(5, "Barrido de la base: identidades sinteticas")
    pregunta("Sin partir de ninguna solicitud: que hay podrido en la cartera?")
    operacion("GET /alertas/curps-multiples  y  GET /alertas/hubs")

    print("\n  CURPs usadas por mas de un nombre:")
    for fila in detection.curps_multiples():
        print("      {}  ->  {} identidades".format(fila["curp"], fila["variantes"]))
        for nombre in fila["nombres"]:
            print("            {}".format(nombre))

    print("\n  Dispositivos usados por 3+ personas distintas:")
    for fila in detection.hubs("Dispositivo", 3):
        print(
            "      {}  {} solicitudes / {} personas".format(
                fila["valor"], fila["solicitudes"], fila["personas"]
            )
        )

    print("\n  Cuentas de deposito usadas por 3+ personas distintas:")
    for fila in detection.hubs("CuentaBanco", 3):
        print(
            "      {}  {} personas".format(fila["valor"], fila["personas"])
        )

    print("\n  Una CURP con seis nombres es imposible sin fraude: es el")
    print("  fragmento real recombinado con identidades inventadas.")


def paso_6_falso_positivo(anillos: Dict[str, Any]) -> None:
    titulo(6, "El falso positivo: donde poner el umbral")
    familia = anillos["E"]["solicitudes"]

    pregunta("Tres personas comparten domicilio y telefono. Es un anillo?")
    operacion("GET /solicitudes/{}/riesgo".format(familia[0]))

    resultado = scoring.evaluar(familia[0])
    riesgo_en_claro(resultado)

    senales = {s["tipo"]: s["comparten"] for s in resultado["senales"]}
    print("\n  Atributos compartidos: {}".format(senales))
    print("  CURP, dispositivo y cuenta: propios de cada uno.")
    print("  Apellido: el mismo para los tres.")
    sin_mitigar = resultado["score"] / scoring.FACTOR_MITIGACION_FAMILIAR
    print("\n  Sin la mitigacion familiar esta solicitud sale en {:.1f} puntos".format(
        sin_mitigar
    ))
    print("  (ALTO) y se le niega el credito a tres clientes legitimos. Ese")
    print("  es el costo real de un falso positivo, y la razon de que el")
    print("  sistema distinga atributos IDENTIFICADORES de atributos de")
    print("  HOGAR en lugar de contar coincidencias.")


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Demo guiada de SynthID.")
    parser.add_argument(
        "--limpiar",
        action="store_true",
        help="Solo borra los restos de una demo interrumpida.",
    )
    parser.add_argument(
        "--pausar", action="store_true", help="Espera Enter entre pasos."
    )
    args = parser.parse_args()

    try:
        if args.limpiar:
            print("Restos eliminados: {}".format(limpiar()))
            return 0

        if not REFERENCIA.exists():
            print("Falta {}.\nCorre antes: python scripts/seed.py".format(REFERENCIA))
            return 1

        anillos = {
            meta["anillo"]: meta
            for meta in json.loads(REFERENCIA.read_text(encoding="utf-8"))
        }

        limpiar()  # por si una corrida anterior quedo a medias

        print("\n" + "=" * ANCHO)
        print("SynthID - deteccion de identidades sinteticas en grafo".center(ANCHO))
        print("Neo4j AuraDB  |  {} solicitudes en la base".format(
            repository.contar_solicitudes()
        ).center(ANCHO))
        print("=" * ANCHO)

        paso_1_alta_limpia();                pausa(args.pausar)
        paso_2_alta_en_anillo(anillos);      pausa(args.pausar)
        paso_3_traversal(anillos);           pausa(args.pausar)
        paso_4_cadena_de_evidencia(anillos); pausa(args.pausar)
        paso_5_alertas(anillos);             pausa(args.pausar)
        paso_6_falso_positivo(anillos)

        print("\n" + "=" * ANCHO)
        print("Limpiando las solicitudes de la demo...")
        print("  eliminadas: {}".format(limpiar()))
        print("  solicitudes en la base: {}".format(repository.contar_solicitudes()))
        print("=" * ANCHO + "\n")

    finally:
        cerrar_driver()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
