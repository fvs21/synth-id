"""CRUD completo sobre la instancia real, limpiando lo que crea.

Las solicitudes de prueba usan el prefijo SOL-TEST y PII propio, asi que no
tocan los datos legitimos ni los anillos.
"""

import pytest

from src.db import ejecutar_escritura
from src.detection import atributos_compartidos
from src.repository import (
    SolicitudNueva,
    actualizar_estatus,
    actualizar_telefono,
    contar_solicitudes,
    crear_solicitud,
    eliminar_solicitud,
    guardar_score,
    listar_solicitudes,
    obtener_solicitud,
    purgar_huerfanos,
)

TELEFONO_COMPARTIDO = "5599000001"


def _solicitud(sufijo: str, **overrides) -> SolicitudNueva:
    datos = dict(
        id="SOL-TEST-{}".format(sufijo),
        fecha="2026-11-17",
        monto_solicitado=100_000.0,
        persona_id="PER-TEST-{}".format(sufijo),
        nombre_completo="Prueba Numero {}".format(sufijo),
        fecha_nacimiento="1990-01-01",
        curp="TEST{}0101HDFXXX01".format(sufijo),
        telefono="559900{}".format(sufijo.zfill(4)),
        email="prueba{}@ejemplo.test".format(sufijo),
        calle="Calle de Prueba {}".format(sufijo),
        cp="99999",
        ciudad="Ciudad de Prueba",
        fingerprint="test{}".format(sufijo.zfill(12)),
        clabe="9999{}".format(sufijo.zfill(14)),
        tipo_dispositivo="Android",
        empleador="Empleador de Prueba",
    )
    datos.update(overrides)
    return SolicitudNueva(**datos)


PREFIJO_PRUEBA = "SOL-TEST-"


def _borra_rastros_de_prueba() -> int:
    """Borra toda solicitud de prueba y el PII que quede huerfano.

    Por prefijo y no sobre un listado paginado: SOL-TEST ordena despues de
    las 427 reales, asi que un listado corto no lo alcanzaria y la limpieza
    fallaria en silencio.
    """
    filas = ejecutar_escritura(
        """
        MATCH (s:Solicitud)
        WHERE s.id STARTS WITH $prefijo
        DETACH DELETE s
        RETURN count(*) AS eliminadas
        """,
        prefijo=PREFIJO_PRUEBA,
    )
    purgar_huerfanos()
    return filas[0]["eliminadas"] if filas else 0


@pytest.fixture
def limpia():
    """Limpia antes y despues de cada test."""
    _borra_rastros_de_prueba()
    yield
    _borra_rastros_de_prueba()


def test_ciclo_completo_de_vida(limpia):
    antes = contar_solicitudes()

    # CREATE
    creada = crear_solicitud(_solicitud("01"))
    assert creada == "SOL-TEST-01"
    assert contar_solicitudes() == antes + 1

    # READ
    expediente = obtener_solicitud("SOL-TEST-01")
    assert expediente is not None
    assert expediente["solicitante"] == "Prueba Numero 01"
    assert expediente["curp"] == "TEST010101HDFXXX01"
    assert expediente["estatus"] == "EN_REVISION"
    assert expediente["score_riesgo"] is None

    # UPDATE
    assert actualizar_estatus("SOL-TEST-01", "FRAUDE_CONFIRMADO")["estatus"] == (
        "FRAUDE_CONFIRMADO"
    )
    assert guardar_score("SOL-TEST-01", 87.5)["score_riesgo"] == 87.5

    releida = obtener_solicitud("SOL-TEST-01")
    assert releida["estatus"] == "FRAUDE_CONFIRMADO"
    assert releida["score_riesgo"] == 87.5

    # DELETE
    assert eliminar_solicitud("SOL-TEST-01") == "SOL-TEST-01"
    assert obtener_solicitud("SOL-TEST-01") is None
    assert contar_solicitudes() == antes

    # El PII quedo huerfano y se purga aparte
    purga = purgar_huerfanos()
    assert purga["personas"] >= 1
    assert purga["nodos_pii"] >= 1


def test_estatus_invalido_se_rechaza(limpia):
    crear_solicitud(_solicitud("02"))

    with pytest.raises(ValueError):
        actualizar_estatus("SOL-TEST-02", "APROBADISIMA")


def test_operaciones_sobre_solicitud_inexistente_devuelven_none():
    assert obtener_solicitud("SOL-NO-EXISTE") is None
    assert actualizar_estatus("SOL-NO-EXISTE", "APROBADA") is None
    assert eliminar_solicitud("SOL-NO-EXISTE") is None
    assert actualizar_telefono("SOL-NO-EXISTE", "5500000000") is None


def test_listado_paginado_no_se_repite(limpia):
    primera = listar_solicitudes(limite=5, desplazamiento=0)
    segunda = listar_solicitudes(limite=5, desplazamiento=5)

    assert len(primera) == 5
    assert len(segunda) == 5
    assert not {f["id"] for f in primera} & {f["id"] for f in segunda}


def test_listado_filtra_por_estatus(limpia):
    crear_solicitud(_solicitud("03"))
    actualizar_estatus("SOL-TEST-03", "RECHAZADA")

    rechazadas = {f["id"] for f in listar_solicitudes(limite=100, estatus="RECHAZADA")}

    assert "SOL-TEST-03" in rechazadas


def test_reapuntar_el_telefono_cambia_el_vecindario(limpia):
    """Cambiar un atributo reconfigura el grafo, no solo un campo.

    Al reapuntar el telefono de una de las dos, la vecindad desaparece sin
    que se haya tocado nada mas.
    """
    crear_solicitud(_solicitud("04", telefono=TELEFONO_COMPARTIDO))
    crear_solicitud(_solicitud("05", telefono=TELEFONO_COMPARTIDO))

    senales = {s["tipo"]: s for s in atributos_compartidos("SOL-TEST-04")}
    assert senales["Telefono"]["comparten"] == 1
    assert senales["Telefono"]["valor"] == TELEFONO_COMPARTIDO

    cambio = actualizar_telefono("SOL-TEST-04", "5599999999")
    assert cambio["telefono_anterior"] == TELEFONO_COMPARTIDO
    assert cambio["telefono_nuevo"] == "5599999999"

    assert atributos_compartidos("SOL-TEST-04") == []
    assert obtener_solicitud("SOL-TEST-04")["telefono"] == "5599999999"
    # La otra solicitud conserva el telefono original
    assert obtener_solicitud("SOL-TEST-05")["telefono"] == TELEFONO_COMPARTIDO
