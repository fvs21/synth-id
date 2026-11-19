"""Esquemas Pydantic de entrada y salida de la API.

Van aparte del repositorio para que la validacion de formato viva en el borde
y el repositorio pueda usarse desde un script sin arrastrar FastAPI.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.repository import ESTATUS_VALIDOS, SolicitudNueva


class SolicitudIn(BaseModel):
    id: str = Field(..., min_length=3, max_length=40, examples=["SOL-X-01"])
    fecha: date = Field(default_factory=date.today)
    monto_solicitado: float = Field(..., gt=0, le=10_000_000)

    persona_id: str = Field(..., min_length=3, max_length=40)
    nombre_completo: str = Field(..., min_length=3, max_length=120)
    fecha_nacimiento: date

    curp: str = Field(..., min_length=18, max_length=18)
    telefono: str = Field(..., pattern=r"^\d{10}$")
    email: str = Field(..., min_length=5, max_length=120)
    calle: str = Field(..., min_length=3, max_length=160)
    cp: str = Field(..., pattern=r"^\d{5}$")
    ciudad: str = Field(..., min_length=2, max_length=80)
    fingerprint: str = Field(..., min_length=8, max_length=64)
    tipo_dispositivo: str = Field("Android", max_length=40)
    clabe: str = Field(..., pattern=r"^\d{18}$")
    empleador: str = Field(..., min_length=2, max_length=160)

    def a_repositorio(self) -> SolicitudNueva:
        """Traduce al tipo del repositorio."""
        return SolicitudNueva(
            id=self.id,
            fecha=self.fecha.isoformat(),
            monto_solicitado=self.monto_solicitado,
            persona_id=self.persona_id,
            nombre_completo=self.nombre_completo,
            fecha_nacimiento=self.fecha_nacimiento.isoformat(),
            curp=self.curp.upper(),
            telefono=self.telefono,
            email=self.email.lower(),
            calle=self.calle,
            cp=self.cp,
            ciudad=self.ciudad,
            fingerprint=self.fingerprint,
            tipo_dispositivo=self.tipo_dispositivo,
            clabe=self.clabe,
            empleador=self.empleador,
        )


class EstatusIn(BaseModel):
    estatus: str = Field(..., examples=list(ESTATUS_VALIDOS))


class TelefonoIn(BaseModel):
    telefono: str = Field(..., pattern=r"^\d{10}$")


class SolicitudResumen(BaseModel):
    id: str
    fecha: Optional[str] = None
    monto_solicitado: Optional[float] = None
    estatus: Optional[str] = None
    score_riesgo: Optional[float] = None
    solicitante: Optional[str] = None


class SolicitudOut(SolicitudResumen):
    persona_id: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    curp: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    calle: Optional[str] = None
    cp: Optional[str] = None
    ciudad: Optional[str] = None
    dispositivo: Optional[str] = None
    tipo_dispositivo: Optional[str] = None
    cuenta_deposito: Optional[str] = None
    empleador: Optional[str] = None


class Senal(BaseModel):
    tipo: str
    valor: Optional[str] = None
    comparten: int
    solicitudes: List[str] = []


class RiesgoOut(BaseModel):
    solicitud_id: str
    score: float
    nivel: str
    mitigado_como_familia: bool
    tamano_anillo: int
    senales: List[Senal] = []
    motivos: List[str] = []


class AltaOut(BaseModel):
    id: str
    riesgo: RiesgoOut


class PasoRuta(BaseModel):
    tipo: str
    valor: Optional[str] = None


class RutaOut(BaseModel):
    saltos: int
    cadena: List[PasoRuta]


class ListadoOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    solicitudes: List[SolicitudResumen]


class BorradoOut(BaseModel):
    id: str
    huerfanos_purgados: Dict[str, int]


class Alerta(BaseModel):
    model_config = {"extra": "allow"}

    def __init__(self, **datos: Any) -> None:
        super().__init__(**datos)
