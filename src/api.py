"""API HTTP de SynthID.

    uvicorn src.api:app --reload   ->   http://127.0.0.1:8000/docs

Los endpoints son `def` y no `async def`: el driver de Neo4j es bloqueante,
asi que FastAPI los corre en su threadpool y no serializa las peticiones.
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path, Query

from src import detection, repository, scoring
from src.db import cerrar_driver, verificar_conectividad
from src.models import (
    AltaOut,
    BorradoOut,
    EstatusIn,
    ListadoOut,
    RiesgoOut,
    RutaOut,
    SolicitudIn,
    SolicitudOut,
    TelefonoIn,
)
from src.repository import ESTATUS_VALIDOS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Falla al arrancar si la base no responde, no en la primera peticion."""
    verificar_conectividad()
    yield
    cerrar_driver()


app = FastAPI(
    title="SynthID",
    version="1.0",
    summary="Deteccion de identidades sinteticas y anillos de fraude en grafo",
    description=(
        "Operaciones CRUD sobre solicitudes de credito y las consultas "
        "especializadas de grafo: vecindades, traversals de longitud "
        "variable, caminos mas cortos y deteccion de nodos hub."
    ),
    lifespan=lifespan,
)


def _o_404(solicitud_id: str) -> Dict[str, Any]:
    """Expediente, o 404.

    Sin esto un id inexistente devolveria score 0 / BAJO: plausible y falso.
    """
    expediente = repository.obtener_solicitud(solicitud_id)
    if expediente is None:
        raise HTTPException(404, "No existe la solicitud {}".format(solicitud_id))
    return expediente


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
@app.post("/solicitudes", response_model=AltaOut, status_code=201, tags=["CRUD"])
def crear_solicitud(entrada: SolicitudIn) -> AltaOut:
    """Alta de una solicitud, con su riesgo recien calculado.

    Van juntas porque el score depende del grafo que el alta acaba de
    modificar.
    """
    if repository.obtener_solicitud(entrada.id) is not None:
        raise HTTPException(409, "Ya existe la solicitud {}".format(entrada.id))

    creada = repository.crear_solicitud(entrada.a_repositorio())
    riesgo = scoring.evaluar(creada)
    repository.guardar_score(creada, riesgo["score"])

    return AltaOut(id=creada, riesgo=RiesgoOut(**riesgo))


@app.get("/solicitudes", response_model=ListadoOut, tags=["CRUD"])
def listar_solicitudes(
    limite: int = Query(20, ge=1, le=200),
    desplazamiento: int = Query(0, ge=0),
    estatus: Optional[str] = Query(None, description="Filtra por estatus"),
) -> ListadoOut:
    """Listado paginado de solicitudes."""
    if estatus is not None and estatus not in ESTATUS_VALIDOS:
        raise HTTPException(
            422,
            "Estatus invalido: {}. Validos: {}".format(
                estatus, ", ".join(ESTATUS_VALIDOS)
            ),
        )

    return ListadoOut(
        total=repository.contar_solicitudes(estatus),
        limite=limite,
        desplazamiento=desplazamiento,
        solicitudes=repository.listar_solicitudes(limite, desplazamiento, estatus),
    )


@app.get("/solicitudes/{solicitud_id}", response_model=SolicitudOut, tags=["CRUD"])
def obtener_solicitud(solicitud_id: str = Path(...)) -> SolicitudOut:
    """Expediente con todo su PII."""
    return SolicitudOut(**_o_404(solicitud_id))


@app.patch("/solicitudes/{solicitud_id}/estatus", tags=["CRUD"])
def actualizar_estatus(
    entrada: EstatusIn, solicitud_id: str = Path(...)
) -> Dict[str, Any]:
    """Registra la decision del analista."""
    _o_404(solicitud_id)

    if entrada.estatus not in ESTATUS_VALIDOS:
        raise HTTPException(
            422,
            "Estatus invalido: {}. Validos: {}".format(
                entrada.estatus, ", ".join(ESTATUS_VALIDOS)
            ),
        )

    return repository.actualizar_estatus(solicitud_id, entrada.estatus)


@app.patch("/solicitudes/{solicitud_id}/telefono", tags=["CRUD"])
def actualizar_telefono(
    entrada: TelefonoIn, solicitud_id: str = Path(...)
) -> Dict[str, Any]:
    """Reapunta la relacion USA_TELEFONO a otro nodo.

    No es un UPDATE de columna: la solicitud cambia de vecindario, asi que su
    riesgo puede cambiar. Consulta /riesgo antes y despues para verlo.
    """
    _o_404(solicitud_id)
    return repository.actualizar_telefono(solicitud_id, entrada.telefono)


@app.delete("/solicitudes/{solicitud_id}", response_model=BorradoOut, tags=["CRUD"])
def eliminar_solicitud(solicitud_id: str = Path(...)) -> BorradoOut:
    """Baja de la solicitud y purga del PII sin dueno."""
    _o_404(solicitud_id)
    eliminada = repository.eliminar_solicitud(solicitud_id)
    return BorradoOut(id=eliminada, huerfanos_purgados=repository.purgar_huerfanos())


# --------------------------------------------------------------------------
# Consultas especializadas de grafo
# --------------------------------------------------------------------------
@app.get(
    "/solicitudes/{solicitud_id}/riesgo",
    response_model=RiesgoOut,
    tags=["Deteccion"],
)
def riesgo(
    solicitud_id: str = Path(...),
    profundidad: int = Query(8, ge=1, le=12),
) -> RiesgoOut:
    """Score de riesgo, siempre con las senales y motivos que lo explican."""
    _o_404(solicitud_id)
    return RiesgoOut(**scoring.evaluar(solicitud_id, profundidad=profundidad))


@app.get("/solicitudes/{solicitud_id}/anillo", tags=["Deteccion"])
def anillo(
    solicitud_id: str = Path(...),
    profundidad: int = Query(8, ge=1, le=12),
) -> Dict[str, Any]:
    """Cluster de solicitudes conectadas, via traversal `*1..n`."""
    _o_404(solicitud_id)
    miembros = detection.anillo_de(solicitud_id, profundidad=profundidad)
    return {
        "solicitud_id": solicitud_id,
        "profundidad": profundidad,
        "tamano": len(miembros) + 1,
        "miembros": miembros,
    }


@app.get("/investigacion/ruta", response_model=RutaOut, tags=["Deteccion"])
def ruta(
    a: str = Query(..., description="Solicitud de origen"),
    b: str = Query(..., description="Solicitud de destino"),
    max_saltos: int = Query(10, ge=1, le=12),
) -> RutaOut:
    """Camino mas corto entre dos solicitudes: la cadena de evidencia."""
    _o_404(a)
    _o_404(b)

    encontrada = detection.ruta_entre(a, b, max_saltos=max_saltos)
    if encontrada is None:
        raise HTTPException(
            404,
            "No hay camino entre {} y {} en {} saltos o menos".format(
                a, b, max_saltos
            ),
        )
    return RutaOut(**encontrada)


# --------------------------------------------------------------------------
# Alertas: barridos que no parten de una solicitud concreta
# --------------------------------------------------------------------------
@app.get("/alertas/curps-multiples", tags=["Alertas"])
def curps_multiples(
    min_variantes: int = Query(2, ge=2, le=50),
) -> List[Dict[str, Any]]:
    """CURPs usadas por mas de un nombre."""
    return detection.curps_multiples(min_variantes)


@app.get("/alertas/hubs", tags=["Alertas"])
def hubs(
    tipo: str = Query("Dispositivo", description="Tipo de atributo"),
    minimo_personas: int = Query(3, ge=2, le=50),
) -> List[Dict[str, Any]]:
    """Atributos de identidad con grado anomalo."""
    if tipo not in detection.HUBS_SOPORTADOS:
        raise HTTPException(
            422,
            "Tipo no soportado: {}. Validos: {}".format(
                tipo, ", ".join(sorted(detection.HUBS_SOPORTADOS))
            ),
        )
    return detection.hubs(tipo, minimo_personas)


@app.get("/alertas/anillos", tags=["Alertas"])
def anillos_globales(
    min_solicitudes: int = Query(2, ge=2, le=50),
) -> List[Dict[str, Any]]:
    """Barrido de la base: atributos compartidos por varias solicitudes."""
    return detection.anillos_globales(min_solicitudes)


# --------------------------------------------------------------------------
# Salud
# --------------------------------------------------------------------------
@app.get("/salud", tags=["Salud"])
def salud() -> Dict[str, Any]:
    """Confirma que la API alcanza la instancia en la nube."""
    return {
        "estado": "ok",
        "motor": verificar_conectividad(),
        "solicitudes": repository.contar_solicitudes(),
    }
