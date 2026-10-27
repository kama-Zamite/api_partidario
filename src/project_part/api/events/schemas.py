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
    titulo: str = Field(min_length=10, max_length=200, strip_whitespace=True)
    descricao: str = Field(min_length=10, max_length=1000, strip_whitespace=True)
    categoria: EventoCategoriaEnum
    localizacao: str = Field(min_length=4, max_length=255, strip_whitespace=True)

    data_inicio: datetime
    image_url: str | None = Field(default=None)
    nome_provincia: str = Field(min_length=2, max_length=255, strip_whitespace=True)
    nome_municipio: str = Field(min_length=2, max_length=255, strip_whitespace=True)
    max_participantes: int | None = Field(ge=0, default=None, description="Número máximo de participantes. Se None, não há limite.")

    @field_validator('data_inicio')
    @classmethod
    def validar_data_inicio(cls, v: datetime) -> datetime:
        if v is None:
            raise ValueError("A data de início não pode ser nula")
        if v < datetime.now():
            raise ValueError("A data de início não pode ser no passado")
        return v

    @field_validator('max_participantes')
    @classmethod
    def validar_max_participantes(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("O número máximo de participantes não pode ser negativo")
        return v

    @field_validator('titulo')
    @classmethod
    def validar_titulo(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("O título não pode ser vazio")
        return v.strip()

    @field_validator('descricao')
    @classmethod
    def validar_descricao(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("A descrição não pode ser vazia")
        return v.strip()

    @field_validator('localizacao')
    @classmethod
    def validar_localizacao(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("A localização não pode ser vazia")
        return v.strip()

    @field_validator('nome_provincia')
    @classmethod
    def validar_nome_provincia(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("O nome da província não pode ser vazio")
        return v.strip()

    @field_validator('nome_municipio')
    @classmethod
    def validar_nome_municipio(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("O nome do município não pode ser vazio")
        return v.strip()


class CreateEvent(EventBase): ...


class LimitEvent(BaseModel):
    limit: int = Field(ge=10, le=100, default=10)
    skip: int = Field(ge=0, default=0)

    model_config = ConfigDict(from_attributes=True)


class UpgradeEvent(EventBase): ...
