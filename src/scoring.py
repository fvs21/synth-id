"""Score de riesgo a partir de las senales del grafo (Fase 4).

COMO SE COMBINAN LAS SENALES
----------------------------
No se suman los pesos: se combinan como probabilidades independientes
(noisy-OR). La razon es que sumar desborda rapido y obliga a recortar en 100,
con lo que dos senales fuertes y cinco se vuelven indistinguibles. Con
noisy-OR cada senal nueva aporta cada vez menos, que es como realmente
funciona la evidencia acumulada:

    riesgo = 1 - (1 - p1)(1 - p2)...(1 - pn)

El peso de cada tipo de atributo refleja cuanto cuesta compartirlo por
casualidad. Compartir CURP es practicamente imposible sin fraude; compartir
domicilio es cotidiano.

LA MITIGACION FAMILIAR
----------------------
Un domicilio y un telefono fijo compartidos por tres personas del mismo
apellido es una familia, no un anillo. Sin esta regla el anillo E de los
datos semilla sale con riesgo ALTO, que seria un falso positivo costoso: se
le niega el credito a tres clientes legitimos. La regla es deliberadamente
estrecha (solo aplica si NO hay ningun identificador fuerte compartido),
porque una familia tambien puede cometer fraude.
"""

from typing import Any, Dict, List, Optional

from src.detection import anillo_de, atributos_compartidos, personas_del_anillo

# Probabilidad de que compartir este atributo indique fraude, por si solo.
PESOS = {
    "Curp": 0.50,
    "CuentaBanco": 0.45,
    "Dispositivo": 0.40,
    "Telefono": 0.30,
    "Email": 0.30,
    "Domicilio": 0.10,
}

# Atributos que una familia comparte sin que sea sospechoso.
COMPARTIBLES_EN_FAMILIA = {"Domicilio", "Telefono"}

# Cuantas solicitudes extra siguen aportando senal por un mismo atributo.
TOPE_REPETICIONES = 5

# Peso del tamano del anillo, que crece con cada miembro hasta un tope.
PESO_POR_MIEMBRO = 0.15
TOPE_PESO_ANILLO = 0.60

FACTOR_MITIGACION_FAMILIAR = 0.25

UMBRAL_MEDIO = 30.0
UMBRAL_ALTO = 65.0


def _nivel(score: float) -> str:
    if score >= UMBRAL_ALTO:
        return "ALTO"
    if score >= UMBRAL_MEDIO:
        return "MEDIO"
    return "BAJO"


def _apellido(nombre: str) -> str:
    """Ultimo token del nombre. Heuristica, suficiente para la regla familiar."""
    partes = nombre.split()
    return partes[-1].upper() if partes else ""


def _es_familia(senales: List[Dict[str, Any]], nombres: List[str]) -> bool:
    """Cierto si el parecido se explica por parentesco y nada mas.

    Exige las tres condiciones: que solo se compartan atributos de hogar, que
    haya al menos dos personas, y que TODAS compartan el mismo apellido.
    """
    tipos = {s["tipo"] for s in senales}
    if not tipos or not tipos.issubset(COMPARTIBLES_EN_FAMILIA):
        return False
    if len(nombres) < 2:
        return False
    apellidos = {_apellido(n) for n in nombres}
    return len(apellidos) == 1 and "" not in apellidos


def evaluar(solicitud_id: str, profundidad: int = 8) -> Dict[str, Any]:
    """Calcula el score de riesgo de una solicitud y explica por que.

    Devuelve siempre los motivos: un score sin explicacion no sirve para que
    un analista tome una decision, ni para defenderla ante el cliente.
    """
    senales = atributos_compartidos(solicitud_id)
    anillo = anillo_de(solicitud_id, profundidad=profundidad)

    motivos: List[str] = []
    complemento = 1.0  # producto de (1 - p) de cada senal

    for senal in senales:
        peso = PESOS.get(senal["tipo"])
        if peso is None:
            continue

        repeticiones = min(senal["comparten"], TOPE_REPETICIONES)
        p = 1.0 - (1.0 - peso) ** repeticiones
        complemento *= 1.0 - p

        motivos.append(
            "{} compartido con {} solicitud(es) mas".format(
                senal["tipo"], senal["comparten"]
            )
        )

    if len(anillo) >= 2:
        p_anillo = min(TOPE_PESO_ANILLO, PESO_POR_MIEMBRO * len(anillo))
        complemento *= 1.0 - p_anillo
        motivos.append(
            "pertenece a un cluster de {} solicitudes conectadas".format(
                len(anillo) + 1
            )
        )

    score = (1.0 - complemento) * 100.0

    # Mitigacion familiar
    nombres = [fila["nombre"] for fila in personas_del_anillo(
        solicitud_id, profundidad=profundidad
    )]
    familia = _es_familia(senales, nombres)
    if familia:
        score *= FACTOR_MITIGACION_FAMILIAR
        motivos.append(
            "MITIGADO: solo comparte atributos de hogar y todos los "
            "solicitantes llevan el apellido {} (probable familia)".format(
                _apellido(nombres[0])
            )
        )

    score = round(min(score, 100.0), 1)

    return {
        "solicitud_id": solicitud_id,
        "score": score,
        "nivel": _nivel(score),
        "mitigado_como_familia": familia,
        "tamano_anillo": len(anillo) + 1,
        "senales": senales,
        "motivos": motivos or ["sin atributos compartidos con otras solicitudes"],
    }


def evaluar_varias(
    solicitud_ids: List[str], profundidad: int = 8
) -> List[Dict[str, Any]]:
    """Evalua varias solicitudes y las devuelve de mayor a menor riesgo."""
    resultados = [evaluar(sid, profundidad=profundidad) for sid in solicitud_ids]
    return sorted(resultados, key=lambda r: r["score"], reverse=True)
