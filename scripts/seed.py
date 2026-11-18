#!/usr/bin/env python3
"""Generador de datos semilla para SynthID (Fase 2 del plan).

Produce DOS capas:

  Capa A - poblacion legitima: 400 solicitudes con PII totalmente unico.
           Es el ruido de fondo contra el que se mide la senal. Comparten
           empleador entre si, porque eso es normal y NO es sospechoso.

  Capa B - cinco anillos sembrados a proposito, cada uno disenado para que
           lo cace una consulta distinta de la Fase 4:

    A  Granja de CURP ....... 1 CURP, 6 personas con nombres distintos
    B  Dispositivo compartido  8 solicitudes, 8 personas, 1 fingerprint
    C  Cadena larga .......... S1-tel-S2-domicilio-S3-dispositivo-S4-clabe-S5
                               (S1 y S5 no comparten NADA entre si)
    D  Mula de deposito ...... 5 solicitudes sin relacion aparente, 1 CLABE
    E  Falso positivo ........ una familia real: 3 solicitudes que comparten
                               domicilio y telefono fijo. NINGUNA consulta
                               deberia marcarla como fraude.

DECISION DE DISENO: el nodo Empleador
--------------------------------------
Cientos de personas legitimas comparten empleador. Si el traversal de
deteccion recorriera la relacion TRABAJA_EN, todo el grafo quedaria conectado
a pocos saltos y la deteccion se volveria inutil (todo seria "sospechoso").
Por eso Empleador existe en el modelo pero queda FUERA de la lista blanca de
relaciones que recorren las consultas de deteccion. La leccion generalizable:
en un grafo de fraude hay que distinguir los atributos compartidos que son
*identificadores* (telefono, dispositivo, CURP) de los que son meras
*categorias* (empleador, ciudad, banco).

NOTA SOBRE LA PROFUNDIDAD: el anillo C tiene 8 saltos entre sus extremos
(S1 -> tel -> S2 -> dom -> S3 -> disp -> S4 -> clabe -> S5), asi que las
consultas de anillo usan cota *1..8, no *1..6.

Los datos son 100% sinteticos: las CURP, CLABE y telefonos tienen formato
plausible pero se generan al azar, no corresponden a personas reales.

Uso:
    python scripts/seed.py            # pobla la base
    python scripts/seed.py --solo-anillos
"""

import argparse
import json
import random
import string
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from faker import Faker  # noqa: E402

from src.db import cerrar_driver  # noqa: E402
from src.repository import (  # noqa: E402
    SolicitudNueva,
    contar_entidades,
    crear_solicitudes_lote,
)

# --------------------------------------------------------------------------
# Parametros reproducibles: con la misma semilla, el seed genera exactamente
# los mismos datos, asi que correrlo dos veces no duplica nada (los MERGE
# del repositorio dan con los mismos nodos).
# --------------------------------------------------------------------------
SEMILLA = 42
POBLACION_LEGITIMA = 400
FECHA_BASE = date(2026, 11, 17)
VENTANA_DIAS = 180

ESTADOS_CURP = [
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR",
    "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC", "PL", "QT", "QR", "SP",
    "SL", "SR", "TC", "TS", "TL", "VZ", "YN", "ZS",
]
CIUDADES = [
    "Ciudad de Mexico", "Guadalajara", "Monterrey", "Puebla", "Queretaro",
    "Merida", "Toluca", "Leon", "Tijuana", "Cancun",
]
TIPOS_DISPOSITIVO = [
    "iPhone", "Android", "Windows Desktop", "macOS", "Tablet Android",
]
DOMINIOS_EMAIL = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com.mx"]


class Generador:
    """Fabrica de solicitudes con PII unico y reproducible."""

    def __init__(self, semilla: int = SEMILLA) -> None:
        self.rnd = random.Random(semilla)
        self.fake = Faker("es_MX")
        Faker.seed(semilla)

        # Guardas de unicidad: evitan que una colision accidental cree un
        # vinculo no intencional que contaminaria la poblacion legitima.
        self._usados: Dict[str, set] = {
            "curp": set(), "telefono": set(), "email": set(),
            "domicilio": set(), "fingerprint": set(), "clabe": set(),
        }

        # Pool de empleadores compartido: ruido legitimo.
        self.empleadores = [self.fake.company() for _ in range(25)]

    # -- utilidades -------------------------------------------------------
    def _unico(self, tipo: str, fabrica) -> str:
        for _ in range(1000):
            valor = fabrica()
            if valor not in self._usados[tipo]:
                self._usados[tipo].add(valor)
                return valor
        raise RuntimeError("No se pudo generar un valor unico de {}".format(tipo))

    def curp(self) -> str:
        def fabrica() -> str:
            letras = "".join(self.rnd.choices(string.ascii_uppercase, k=4))
            nacimiento = self.fake.date_of_birth(minimum_age=18, maximum_age=70)
            cons = "".join(self.rnd.choices("BCDFGHJKLMNPQRSTVWXYZ", k=3))
            homoclave = "".join(self.rnd.choices(string.digits + "ABCDEFGHIJ", k=2))
            return "{}{}{}{}{}{}".format(
                letras,
                nacimiento.strftime("%y%m%d"),
                self.rnd.choice("HM"),
                self.rnd.choice(ESTADOS_CURP),
                cons,
                homoclave,
            )
        return self._unico("curp", fabrica)

    def telefono(self) -> str:
        return self._unico(
            "telefono",
            lambda: "{}{}".format(
                self.rnd.choice(["55", "33", "81", "22", "44"]),
                "".join(self.rnd.choices(string.digits, k=8)),
            ),
        )

    def email(self, nombre: str) -> str:
        base = unicodedata.normalize("NFKD", nombre.lower())
        base = "".join(c for c in base if c in string.ascii_lowercase + " ")
        base = ".".join(base.split()[:2]) or "usuario"
        return self._unico(
            "email",
            lambda: "{}{}@{}".format(
                base,
                self.rnd.randint(1, 9999),
                self.rnd.choice(DOMINIOS_EMAIL),
            ),
        )

    def domicilio(self) -> Tuple[str, str, str]:
        def fabrica() -> str:
            return "{}||{}||{}".format(
                self.fake.street_name() + " " + str(self.rnd.randint(1, 400)),
                "{:05d}".format(self.rnd.randint(1000, 99999)),
                self.rnd.choice(CIUDADES),
            )
        calle, cp, ciudad = self._unico("domicilio", fabrica).split("||")
        return calle, cp, ciudad

    def fingerprint(self) -> str:
        return self._unico(
            "fingerprint",
            lambda: "".join(self.rnd.choices("0123456789abcdef", k=16)),
        )

    def clabe(self) -> str:
        return self._unico(
            "clabe", lambda: "".join(self.rnd.choices(string.digits, k=18))
        )

    def fecha_solicitud(self) -> str:
        dias = self.rnd.randint(0, VENTANA_DIAS)
        return (FECHA_BASE - timedelta(days=dias)).isoformat()

    # -- fabrica principal ------------------------------------------------
    def solicitud(
        self,
        solicitud_id: str,
        persona_id: Optional[str] = None,
        nombre: Optional[str] = None,
        **overrides
    ) -> SolicitudNueva:
        """Crea una solicitud con PII nuevo; `overrides` permite COMPARTIR
        un atributo con otra solicitud (es asi como se siembra un anillo)."""
        nombre_completo = nombre or self.fake.name()
        calle, cp, ciudad = self.domicilio()

        datos = dict(
            id=solicitud_id,
            fecha=self.fecha_solicitud(),
            monto_solicitado=float(self.rnd.randrange(15_000, 450_000, 5_000)),
            persona_id=persona_id or "PER-" + solicitud_id.split("SOL-")[-1],
            nombre_completo=nombre_completo,
            fecha_nacimiento=self.fake.date_of_birth(
                minimum_age=18, maximum_age=70
            ).isoformat(),
            curp=self.curp(),
            telefono=self.telefono(),
            email=self.email(nombre_completo),
            calle=calle,
            cp=cp,
            ciudad=ciudad,
            fingerprint=self.fingerprint(),
            tipo_dispositivo=self.rnd.choice(TIPOS_DISPOSITIVO),
            clabe=self.clabe(),
            empleador=self.rnd.choice(self.empleadores),
            estatus="EN_REVISION",
        )
        datos.update(overrides)
        return SolicitudNueva(**datos)


# --------------------------------------------------------------------------
# Capa A: poblacion legitima
# --------------------------------------------------------------------------
def generar_poblacion_legitima(gen: Generador, n: int) -> List[SolicitudNueva]:
    return [gen.solicitud("SOL-L-{:04d}".format(i)) for i in range(1, n + 1)]


# --------------------------------------------------------------------------
# Capa B: los cinco anillos
# --------------------------------------------------------------------------
def anillo_a_granja_curp(gen: Generador) -> Tuple[List[SolicitudNueva], Dict]:
    """1 CURP reutilizada por 6 identidades con nombre distinto.

    Es la firma pura de la identidad sintetica: el fragmento real (la CURP)
    se recombina con nombres inventados.
    """
    curp_compartida = gen.curp()
    solicitudes = [
        gen.solicitud("SOL-A-{:02d}".format(i), curp=curp_compartida)
        for i in range(1, 7)
    ]
    return solicitudes, {
        "anillo": "A",
        "nombre": "Granja de CURP",
        "detecta_con": "consulta 4 (una CURP, varios nombres)",
        "valor_compartido": {"Curp": curp_compartida},
        "solicitudes": [s.id for s in solicitudes],
    }


def anillo_b_dispositivo(gen: Generador) -> Tuple[List[SolicitudNueva], Dict]:
    """8 solicitudes de 8 personas distintas desde el mismo dispositivo."""
    fp = gen.fingerprint()
    solicitudes = [
        gen.solicitud(
            "SOL-B-{:02d}".format(i), fingerprint=fp, tipo_dispositivo="Android"
        )
        for i in range(1, 9)
    ]
    return solicitudes, {
        "anillo": "B",
        "nombre": "Dispositivo compartido",
        "detecta_con": "consulta 5 (nodos hub con grado anomalo)",
        "valor_compartido": {"Dispositivo": fp},
        "solicitudes": [s.id for s in solicitudes],
    }


def anillo_c_cadena(gen: Generador) -> Tuple[List[SolicitudNueva], Dict]:
    """Cadena de 5 solicitudes encadenadas por un atributo distinto cada vez.

    S1 y S5 no comparten ningun atributo directo: solo un traversal de
    longitud variable (o shortestPath) revela que pertenecen al mismo anillo.
    Esta es LA consulta que no se puede escribir de forma mantenible en SQL.
    """
    s1 = gen.solicitud("SOL-C-01")
    s2 = gen.solicitud("SOL-C-02", telefono=s1.telefono)
    s3 = gen.solicitud("SOL-C-03", calle=s2.calle, cp=s2.cp, ciudad=s2.ciudad)
    s4 = gen.solicitud(
        "SOL-C-04", fingerprint=s3.fingerprint, tipo_dispositivo=s3.tipo_dispositivo
    )
    s5 = gen.solicitud("SOL-C-05", clabe=s4.clabe)

    return [s1, s2, s3, s4, s5], {
        "anillo": "C",
        "nombre": "Cadena larga",
        "detecta_con": "consulta 2 (traversal *1..8) y consulta 3 (shortestPath)",
        "extremos": {"desde": s1.id, "hasta": s5.id, "saltos_esperados": 8},
        "eslabones": [
            "{} -[Telefono {}]- {}".format(s1.id, s1.telefono, s2.id),
            "{} -[Domicilio {}]- {}".format(s2.id, s2.calle, s3.id),
            "{} -[Dispositivo {}]- {}".format(s3.id, s3.fingerprint, s4.id),
            "{} -[CuentaBanco {}]- {}".format(s4.id, s4.clabe, s5.id),
        ],
        "solicitudes": [s.id for s in (s1, s2, s3, s4, s5)],
    }


def anillo_d_mula_deposito(gen: Generador) -> Tuple[List[SolicitudNueva], Dict]:
    """5 solicitudes sin nada en comun salvo la cuenta donde cae el dinero."""
    clabe = gen.clabe()
    solicitudes = [
        gen.solicitud("SOL-D-{:02d}".format(i), clabe=clabe) for i in range(1, 6)
    ]
    return solicitudes, {
        "anillo": "D",
        "nombre": "Mula de deposito",
        "detecta_con": "consulta 1 (vecindad a 2 saltos)",
        "valor_compartido": {"CuentaBanco": clabe},
        "solicitudes": [s.id for s in solicitudes],
    }


def anillo_e_falso_positivo(gen: Generador) -> Tuple[List[SolicitudNueva], Dict]:
    """Una familia real. Comparten domicilio y telefono fijo, y eso es normal.

    Sirve para discutir umbrales: compartir domicilio NO es fraude. Lo que
    distingue a esta familia del anillo D es que cada integrante tiene CURP,
    dispositivo y cuenta propios, y que comparten apellido.
    """
    apellido = gen.fake.last_name()
    calle, cp, ciudad = gen.domicilio()
    telefono_fijo = gen.telefono()

    solicitudes = []
    for i, nombre_pila in enumerate(["Rosa Maria", "Jorge Luis", "Ana Sofia"], start=1):
        nombre = "{} {}".format(nombre_pila, apellido)
        solicitudes.append(
            gen.solicitud(
                "SOL-E-{:02d}".format(i),
                nombre=nombre,
                telefono=telefono_fijo,
                calle=calle,
                cp=cp,
                ciudad=ciudad,
            )
        )

    return solicitudes, {
        "anillo": "E",
        "nombre": "Falso positivo legitimo (familia)",
        "detecta_con": "NINGUNA consulta deberia marcarlo como fraude",
        "valor_compartido": {
            "Telefono": telefono_fijo,
            "Domicilio": "{}, {}".format(calle, ciudad),
        },
        "apellido_comun": apellido,
        "solicitudes": [s.id for s in solicitudes],
    }


CONSTRUCTORES_ANILLOS = (
    anillo_a_granja_curp,
    anillo_b_dispositivo,
    anillo_c_cadena,
    anillo_d_mula_deposito,
    anillo_e_falso_positivo,
)


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Pobla la base de SynthID.")
    parser.add_argument(
        "--solo-anillos",
        action="store_true",
        help="Siembra unicamente los anillos, sin la poblacion legitima.",
    )
    parser.add_argument(
        "--poblacion",
        type=int,
        default=POBLACION_LEGITIMA,
        help="Tamano de la poblacion legitima (default: {}).".format(
            POBLACION_LEGITIMA
        ),
    )
    args = parser.parse_args()

    gen = Generador()
    referencia: List[Dict] = []
    total = 0

    try:
        if not args.solo_anillos:
            print("Capa A - poblacion legitima ({} solicitudes)...".format(args.poblacion))
            legitimas = generar_poblacion_legitima(gen, args.poblacion)
            total += crear_solicitudes_lote(legitimas)
            print("  [ok] {} solicitudes legitimas".format(len(legitimas)))

        print("\nCapa B - anillos sembrados...")
        for constructor in CONSTRUCTORES_ANILLOS:
            solicitudes, meta = constructor(gen)
            total += crear_solicitudes_lote(solicitudes)
            referencia.append(meta)
            print(
                "  [ok] Anillo {} - {:<34} {} solicitudes".format(
                    meta["anillo"], meta["nombre"], len(solicitudes)
                )
            )

        # Archivo de referencia: la demo de la Fase 5 lo lee para saber que
        # valores usar, y a ti te sirve para copiar y pegar en Neo4j Browser.
        destino = RAIZ / "docs" / "anillos_sembrados.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(referencia, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print("\n" + "=" * 62)
        print("Solicitudes insertadas en esta corrida: {}".format(total))
        print("\nEstado del grafo:")
        conteo = contar_entidades()
        relaciones = conteo.pop("_relaciones", 0)
        for etiqueta, n in sorted(conteo.items()):
            print("  {:<14} {:>6}".format(etiqueta, n))
        print("  {:<14} {:>6}".format("relaciones", relaciones))
        print("\nReferencia de anillos -> {}".format(destino))
        print("=" * 62)

    finally:
        cerrar_driver()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
