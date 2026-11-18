"""API HTTP de SynthID (Fase 5).

    uvicorn src.api:app --reload

Y el Swagger autogenerado queda en http://127.0.0.1:8000/docs, que es la
mejor superficie para la demo: el evaluador hace clic en los endpoints y ve
el CRUD y los traversals en vivo.

POR QUE LOS ENDPOINTS SON `def` Y NO `async def`
------------------------------------------------
El driver de Neo4j es sincrono y bloqueante. Un endpoint declarado
`async def` corre en el event loop, asi que una consulta lenta bloquearia
TODAS las peticiones concurrentes. Declarado `def`, FastAPI lo ejecuta en su
threadpool y el bloqueo queda aislado a ese hilo. Es la diferencia entre una
API que aguanta varias peticiones y una que se serializa.
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
    """Falla al arrancar si la base no responde, en lugar de en la primera
    peticion: es mejor enterarse al levantar el servidor."""
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
    """Devuelve el expediente o corta con 404.

    Importa para los endpoints de riesgo: sin esta verificacion, un id
    inexistente devolveria score 0 / nivel BAJO, que es una respuesta
    plausible y equivocada.
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
    """Da de alta una solicitud y devuelve su riesgo recien calculado.

    El alta y la evaluacion van juntas a proposito: es el momento en que la
    decision importa, y el score depende del grafo que la propia alta acaba
    de modificar.
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
    """Expediente completo con todo su PII."""
    return SolicitudOut(**_o_404(solicitud_id))


@app.patch("/solicitudes/{solicitud_id}/estatus", tags=["CRUD"])
def actualizar_estatus(
    entrada: EstatusIn, solicitud_id: str = Path(...)
) -> Dict[str, Any]:
    """Registra la decision del analista sobre la solicitud."""
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
    """Cambia el telefono REAPUNTANDO la relacion a otro nodo.

    No es un UPDATE de columna: la solicitud se desvincula de un vecindario y
    se vincula a otro, asi que su riesgo puede cambiar sin que nada mas en el
    grafo se haya tocado. Consulta /riesgo antes y despues para verlo.
    """
    _o_404(solicitud_id)
    return repository.actualizar_telefono(solicitud_id, entrada.telefono)


@app.delete("/solicitudes/{solicitud_id}", response_model=BorradoOut, tags=["CRUD"])
def eliminar_solicitud(solicitud_id: str = Path(...)) -> BorradoOut:
    """Baja de la solicitud y purga del PII que se quedo sin dueno."""
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
    """Score de riesgo con las senales que lo explican (vecindad a 2 saltos).

    Nunca devuelve un numero sin motivos: un score inexplicable no sirve para
    que un analista decida, ni para defender la decision ante el cliente.
    """
    _o_404(solicitud_id)
    return RiesgoOut(**scoring.evaluar(solicitud_id, profundidad=profundidad))


@app.get("/solicitudes/{solicitud_id}/anillo", tags=["Deteccion"])
def anillo(
    solicitud_id: str = Path(...),
    profundidad: int = Query(8, ge=1, le=12),
) -> Dict[str, Any]:
    """Clúster completo de solicitudes conectadas, via traversal `*1..n`."""
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
    """Camino mas corto entre dos solicitudes: la cadena de evidencia.

    Responde "estas dos personas dicen no conocerse, como estan conectadas?".
    """
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
    """CURPs usadas por mas de un nombre: la firma de la identidad sintetica."""
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
    """Barrido de la base: todo atributo compartido por varias solicitudes."""
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
