import uuid
from datetime import datetime
from typing import Any, Optional, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_part.model.models import (
    EventStatusEnum,
    EventoCategoriaEnum,
)


class EventResponse(BaseModel):
    id: uuid.UUID
    titulo: str = Field(max_length=200)
    descricao: str
    localizacao: str

    data_inicio: datetime
    image_url: str

    provincia: str
    municipio: str
    categoria: EventoCategoriaEnum

    max_participantes: int | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        return None

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')

        if isinstance(v, str):
            return v
        return None

class EventosPaginadosResponse(BaseModel):
    total: int
    eventos: List[EventResponse]


class EventBase(BaseModel):
    titulo: str = Field(max_length=200)
    descricao: str
    categoria: EventoCategoriaEnum
    localizacao: str = Field(max_length=255)

    data_inicio: datetime
    image_url: str | None = Field(default=None)
    nome_provincia: str
    nome_municipio: str
    max_participantes: int | None = Field(ge=0, default=None)


class CreateEvent(EventBase): ...


class LimitEvent(BaseModel):
    limit: int = Field(ge=10, le=100, default=10)
    skip: int = Field(ge=0, default=0)

    model_config = ConfigDict(from_attributes=True)


class UpgradeEvent(EventBase): ...
