import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LimitNoticia(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)
    skip: int = Field(default=0, ge=0)


class CreateCategoria(BaseModel):
    name: str = Field(max_length=100)


class UgradeStatusNoticia(BaseModel):
    nome: str = Field(min_length=5, max_length=20)


class RelacaoNomeSchema(BaseModel):
    nome: str

    model_config = ConfigDict(from_attributes=True)


class NoticiaResponse(BaseModel):
    id: uuid.UUID
    titulo: str
    slug: str
    subtitulo: Optional[str] = None
    lead: Optional[str] = None
    corpo: str
    image_url: Optional[str] = None
    status: str
    publicado_as: Optional[datetime] = None

    provincia: Optional[str] = None
    municipio: Optional[str] = None
    categoria_id: int
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
    
    # @field_validator('categoria', mode='before')
    # @classmethod
    # def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
    #         if v and hasattr(v, 'name'):
    #             return getattr(v, 'name')
    #         if isinstance(v, str):
    #             return v
    #         return None


class CategoriaResponse(BaseModel):
    id: int
    name: str
    noticias: list[NoticiaResponse] = []
    model_config = ConfigDict(from_attributes=True)


class UpgradeCategoria(CreateCategoria): ...


class CreateNoticia(BaseModel):
    titulo: str = Field(..., max_length=200)
    slug: str = Field(..., max_length=255)
    subtitulo: Optional[str] = Field(None, max_length=255)
    lead: Optional[str] = None
    corpo: str
    image_url: Optional[str] = None
    categoria_id: int
    nome_provincia: Optional[str] = None
    nome_municipio: Optional[str] = None
    status: str = 'rascunho'


class UpgradeNoticia(BaseModel):
    titulo: str = Field(min_length=10, max_length=200)
    slug: str = Field(min_length=10, max_length=255)
    subtitulo: Optional[str] = Field(None, min_length=20, max_length=255)
    lead: Optional[str] = None
    corpo: str
    categoria_id: int
    nome_municipio: Optional[str] = None
    nome_provincia: Optional[str] = None
    status: str
