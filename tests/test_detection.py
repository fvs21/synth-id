"""Verifica que cada consulta encuentre el anillo que fue disenada para cazar.

Los datos semilla son deterministas, asi que estos tests son reproducibles:
cada anillo se sembro con un patron concreto y aqui se comprueba que la
consulta correspondiente lo recupera, y que NO recupera a las legitimas.
"""

import pytest

from src.db import ejecutar_lectura
from src.detection import (
    REL_PII,
    anillo_de,
    anillos_globales,
    atributos_compartidos,
    curps_multiples,
    hubs,
    ruta_entre,
)
from src.scoring import evaluar

LEGITIMA = "SOL-L-0001"


# --------------------------------------------------------------------------
# Anillo A: granja de CURP
# --------------------------------------------------------------------------
def test_anillo_a_una_curp_con_seis_identidades(anillos):
    esperada = anillos["A"]["valor_compartido"]["Curp"]

    resultado = {fila["curp"]: fila for fila in curps_multiples()}

    assert esperada in resultado, "no se detecto la CURP sembrada del anillo A"
    assert resultado[esperada]["variantes"] == 6
    assert len(set(resultado[esperada]["nombres"])) == 6


# --------------------------------------------------------------------------
# Anillo B: dispositivo compartido
# --------------------------------------------------------------------------
def test_anillo_b_hub_de_dispositivo(anillos):
    esperado = anillos["B"]["valor_compartido"]["Dispositivo"]

    resultado = {fila["valor"]: fila for fila in hubs("Dispositivo", 3)}

    assert esperado in resultado
    assert resultado[esperado]["solicitudes"] == 8
    assert resultado[esperado]["personas"] == 8


def test_anillo_b_se_recupera_completo_desde_un_miembro(anillos):
    miembros = set(anillos["B"]["solicitudes"])
    origen = anillos["B"]["solicitudes"][0]

    alcanzadas = {fila["id"] for fila in anillo_de(origen)}

    assert alcanzadas == miembros - {origen}


# --------------------------------------------------------------------------
# Anillo C: cadena larga
# --------------------------------------------------------------------------
def test_anillo_c_traversal_alcanza_toda_la_cadena(anillos):
    miembros = set(anillos["C"]["solicitudes"])
    origen = anillos["C"]["extremos"]["desde"]

    alcanzadas = {fila["id"] for fila in anillo_de(origen, profundidad=8)}

    assert alcanzadas == miembros - {origen}


def test_anillo_c_camino_mas_corto_entre_extremos(anillos):
    extremos = anillos["C"]["extremos"]

    ruta = ruta_entre(extremos["desde"], extremos["hasta"])

    assert ruta is not None, "no se encontro camino entre los extremos"
    assert ruta["saltos"] == extremos["saltos_esperados"] == 8
    # La cadena alterna solicitud, atributo, solicitud...
    tipos = [paso["tipo"] for paso in ruta["cadena"]]
    assert tipos[0] == tipos[-1] == "Solicitud"
    assert len([t for t in tipos if t == "Solicitud"]) == 5


def test_anillo_c_cota_insuficiente_no_alcanza_el_otro_extremo(anillos):
    """Los extremos estan a 8 saltos: con cota 6 no deben verse.

    Documenta por que las consultas de anillo usan *1..8 y no *1..6.
    """
    extremos = anillos["C"]["extremos"]

    alcanzadas = {fila["id"] for fila in anillo_de(extremos["desde"], profundidad=6)}

    assert extremos["hasta"] not in alcanzadas


# --------------------------------------------------------------------------
# Anillo D: mula de deposito
# --------------------------------------------------------------------------
def test_anillo_d_vecindad_detecta_cuenta_compartida(anillos):
    esperada = anillos["D"]["valor_compartido"]["CuentaBanco"]
    origen = anillos["D"]["solicitudes"][0]

    senales = {s["tipo"]: s for s in atributos_compartidos(origen)}

    assert "CuentaBanco" in senales
    assert senales["CuentaBanco"]["valor"] == esperada
    assert senales["CuentaBanco"]["comparten"] == 4


# --------------------------------------------------------------------------
# Anillo E: el falso positivo
# --------------------------------------------------------------------------
def test_anillo_e_solo_comparte_atributos_de_hogar(anillos):
    origen = anillos["E"]["solicitudes"][0]

    tipos = {s["tipo"] for s in atributos_compartidos(origen)}

    assert tipos == {"Telefono", "Domicilio"}, (
        "la familia no deberia compartir ningun identificador fuerte"
    )


def test_el_anillo_no_se_incluye_a_si_mismo(anillos):
    """Regresion: el origen aparecia en su propio anillo si habia un ciclo.

    La familia del anillo E se conecta por DOS atributos (telefono y
    domicilio), asi que existe el ciclo E-01 -tel- E-02 -domicilio- E-01.
    Son cuatro relaciones distintas, por lo que la unicidad de relaciones de
    Cypher no lo impide y `otra` hacia match con el propio origen, inflando
    el tamano del cluster. Los anillos B y C no tienen ciclos, que es la
    razon por la que los demas tests no lo detectaron.
    """
    for letra in "ABCDE":
        for solicitud in anillos[letra]["solicitudes"]:
            alcanzadas = {fila["id"] for fila in anillo_de(solicitud)}

            assert solicitud not in alcanzadas, (
                "{} se incluye en su propio anillo".format(solicitud)
            )


def test_anillo_e_tamano_real_del_cluster(anillos):
    """La familia son tres solicitudes, ni una mas."""
    resultado = evaluar(anillos["E"]["solicitudes"][0])

    assert resultado["tamano_anillo"] == 3


def test_anillo_e_se_mitiga_como_familia(anillos):
    for solicitud in anillos["E"]["solicitudes"]:
        resultado = evaluar(solicitud)

        assert resultado["mitigado_como_familia"] is True
        assert resultado["nivel"] == "BAJO", (
            "{} quedo en {} ({} puntos): un falso positivo costoso".format(
                solicitud, resultado["nivel"], resultado["score"]
            )
        )


# --------------------------------------------------------------------------
# Controles: las legitimas no se marcan
# --------------------------------------------------------------------------
def test_legitima_no_comparte_nada():
    assert atributos_compartidos(LEGITIMA) == []
    assert anillo_de(LEGITIMA) == []


def test_legitima_sale_con_riesgo_bajo():
    resultado = evaluar(LEGITIMA)

    assert resultado["score"] == 0.0
    assert resultado["nivel"] == "BAJO"


def test_empleador_queda_fuera_del_traversal():
    """La medicion que justifica excluir TRABAJA_EN de la lista blanca.

    Sin el, una solicitud legitima no alcanza ninguna otra. Con el, arrastra
    decenas, porque cientos de personas comparten los mismos 25 empleadores.
    """
    sin_empleador = ejecutar_lectura(
        "MATCH (s:Solicitud {{id: $id}})-[:{rel}*1..8]-(otra:Solicitud) "
        "RETURN count(DISTINCT otra) AS n".format(rel=REL_PII),
        id=LEGITIMA,
    )[0]["n"]

    con_empleador = ejecutar_lectura(
        "MATCH (s:Solicitud {{id: $id}})-[:{rel}|TRABAJA_EN*1..8]-(otra:Solicitud) "
        "RETURN count(DISTINCT otra) AS n".format(rel=REL_PII),
        id=LEGITIMA,
    )[0]["n"]

    assert sin_empleador == 0
    assert con_empleador > 50, (
        "se esperaba que TRABAJA_EN conectara el grafo; medido: {}".format(
            con_empleador
        )
    )


# --------------------------------------------------------------------------
# Scoring: los anillos de fraude deben salir altos
# --------------------------------------------------------------------------
@pytest.mark.parametrize("letra", ["A", "B", "C", "D"])
def test_los_anillos_de_fraude_salen_con_riesgo_alto(anillos, letra):
    for solicitud in anillos[letra]["solicitudes"]:
        resultado = evaluar(solicitud)

        assert resultado["nivel"] == "ALTO", (
            "anillo {}: {} quedo en {} con {} puntos".format(
                letra, solicitud, resultado["nivel"], resultado["score"]
            )
        )
        assert resultado["motivos"]


# --------------------------------------------------------------------------
# Barrido global
# --------------------------------------------------------------------------
def test_el_barrido_global_solo_encuentra_los_anillos(anillos):
    sembradas = {
        solicitud
        for meta in anillos.values()
        for solicitud in meta["solicitudes"]
    }

    marcadas = {
        solicitud
        for fila in anillos_globales()
        for solicitud in fila["solicitudes"]
    }

    assert marcadas, "el barrido no encontro nada"
    assert marcadas <= sembradas, (
        "el barrido marco solicitudes legitimas: {}".format(
            sorted(marcadas - sembradas)[:10]
        )
    )
