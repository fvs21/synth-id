"""Score de riesgo a partir de las senales del grafo.

Los pesos no se suman: se combinan como probabilidades independientes
(noisy-OR), riesgo = 1 - (1-p1)(1-p2)...(1-pn), asi cada senal nueva aporta
menos en lugar de desbordar el tope. La mitigacion familiar, estrecha a
proposito, no marca como anillo a quien solo comparte atributos de hogar.
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
    """Ultimo token del nombre: heuristica suficiente para la regla familiar."""
    partes = nombre.split()
    return partes[-1].upper() if partes else ""


def _es_familia(senales: List[Dict[str, Any]], nombres: List[str]) -> bool:
    """Cierto si solo se comparten atributos de hogar, entre dos personas o
    mas, y todas llevan el mismo apellido."""
    tipos = {s["tipo"] for s in senales}
    if not tipos or not tipos.issubset(COMPARTIBLES_EN_FAMILIA):
        return False
    if len(nombres) < 2:
        return False
    apellidos = {_apellido(n) for n in nombres}
    return len(apellidos) == 1 and "" not in apellidos


def evaluar(solicitud_id: str, profundidad: int = 8) -> Dict[str, Any]:
    """Score de riesgo de una solicitud, siempre con los motivos que lo explican."""
    senales = atributos_compartidos(solicitud_id)
    anillo = anillo_de(solicitud_id, profundidad=profundidad)

    motivos: List[str] = []
    complemento = 1.0  # producto de (1 - p)

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
    """Varias solicitudes, de mayor a menor riesgo."""
    resultados = [evaluar(sid, profundidad=profundidad) for sid in solicitud_ids]
    return sorted(resultados, key=lambda r: r["score"], reverse=True)
