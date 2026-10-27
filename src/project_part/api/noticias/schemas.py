import uuid
from datetime import datetime
from typing import Any, Optional
from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from project_part.model.models import CategoriaNoticiaEnum


class LimitNoticia(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)
    skip: int = Field(default=0, ge=0)


class UgradeStatusNoticia(BaseModel):
    nome: str = Field(min_length=5, max_length=20, strip_whitespace=True)

    @field_validator('nome')
    @classmethod
    def validar_nome(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O status não pode ser vazio")
        if v not in [e.value for e in CategoriaNoticiaEnum]:
            raise ValueError(f"Status inválido. Valores válidos: {[e.value for e in CategoriaNoticiaEnum]}")
        return v



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
    categoria: str
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


# class CategoriaResponse(BaseModel):
#     id: int
#     name: str
#     noticias: list[NoticiaResponse] = []
#     model_config = ConfigDict(from_attributes=True)


# class UpgradeCategoria(CreateCategoria): ...


class CreateNoticia(BaseModel):
    titulo: str = Field(..., max_length=200, strip_whitespace=True, min_length=5)
    slug: str = Field(..., max_length=500)
    subtitulo: str | None = Field(None, strip_whitespace=True)
    lead: str | None = None
    corpo: str = Field(..., min_length=10, max_length=10000, strip_whitespace=True)
    nome_provincia: str | None = Field(None, min_length=2, max_length=100, strip_whitespace=True)
    nome_municipio: str | None = Field(None, min_length=2, max_length=100, strip_whitespace=True)

    @field_validator('titulo')
    @classmethod
    def validar_titulo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O título não pode ser vazio")
        return v

    @field_validator('subtitulo')
    @classmethod
    def validar_subtitulo(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O subtítulo não pode ser vazio")
        return v

    @field_validator('corpo')
    @classmethod
    def validar_corpo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O corpo não pode ser vazio")
        return v

    @field_validator('nome_provincia')
    @classmethod 
    def validar_nome_provincia(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O nome da província não pode ser vazio")
        return v

    @field_validator('nome_municipio')
    @classmethod
    def validar_nome_municipio(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O nome do município não pode ser vazio")
        return v



class UpgradeNoticia(BaseModel):
    titulo: str = Field(..., max_length=200, strip_whitespace=True, min_length=5)
    subtitulo: str | None = Field(None, max_length=255, strip_whitespace=True, min_length=5)
    slug: str = Field(..., max_length=255)
    lead: str | None = None
    corpo: str = Field(..., strip_whitespace=True)
    image_url: UploadFile | None = None
    # categoria: CategoriaNoticiaEnum = Field(default=CategoriaNoticiaEnum.DESTAQUE)
    nome_municipio: str | None = Field(None, min_length=2, max_length=100, strip_whitespace=True)
    nome_provincia: str | None = Field(None, min_length=2, max_length=100, strip_whitespace=True)

    @field_validator('titulo')
    @classmethod
    def validar_titulo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O título não pode ser vazio")
        return v

    @field_validator('subtitulo')
    @classmethod
    def validar_subtitulo(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O subtítulo não pode ser vazio")
        return v

    @field_validator('corpo')
    @classmethod
    def validar_corpo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O corpo não pode ser vazio")
        return v

    @field_validator('nome_provincia')
    @classmethod
    def validar_nome_provincia(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O nome da província não pode ser vazio")
        return v

    @field_validator('nome_municipio')
    @classmethod
    def validar_nome_municipio(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O nome do município não pode ser vazio")
        return v

    # status: str
