import re
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MunicipioBase(BaseModel):
    nome_municipio: str = Field(max_length=200)


class CreateMunicipio(MunicipioBase):
    nome_provincia: str

    @field_validator('nome_provincia', 'nome_municipio', mode='before')
    @classmethod
    def formatar_iniciais(cls, v: str) -> str:
        if isinstance(v, str):
            v_limpo = v.strip()

            if not re.match(r'^[a-zA-ZÀ-ÿ\s]+$', v_limpo):
                raise ValueError('O campo deve conter apenas letras e espaços.')

            return v_limpo.title()
        return v


class DeleteMunicipio(BaseModel):
    nome_provincia: str

    @field_validator('nome_provincia', mode='before')
    @classmethod
    def formatar_iniciais(cls, v: str) -> str:
        if isinstance(v, str):
            v_limpo = v.strip()

            if not re.match(r'^[a-zA-ZÀ-ÿ\s]+$', v_limpo):
                raise ValueError('O campo deve conter apenas letras e espaços.')

            return v_limpo.title()
        return v


class UpgradeMunicipio(BaseModel):
    nome_provincia: str = Field(min_length=4, max_length=20)
    novo_nome_municipio: str = Field(max_length=200)

    @field_validator(
        'novo_nome_municipio',
        'nome_provincia',
        mode='before',
    )
    @classmethod
    def formatar_iniciais(cls, v: str) -> str:
        if isinstance(v, str):
            v_limpo = v.strip()

            if not re.match(r'^[a-zA-ZÀ-ÿ\s]+$', v_limpo):
                raise ValueError('O campo deve conter apenas letras e espaços.')

            return v_limpo.title()
        return v


class ResponseMunicipio(MunicipioBase):
    model_config = ConfigDict(from_attributes=True)


class ProvinciaBase(BaseModel):
    nome_provincia: str = Field(min_length=4, max_length=20)


class CreateProvincia(ProvinciaBase):
    @field_validator('nome_provincia', mode='before')
    @classmethod
    def formatar_iniciais(cls, v: str) -> str:
        if isinstance(v, str):
            v_limpo = v.strip()

            if not re.match(r'^[a-zA-ZÀ-ÿ\s]+$', v_limpo):
                raise ValueError('O campo deve conter apenas letras e espaços.')

            return v_limpo.title()
        return v


class FindProvincia(BaseModel):
    novo_nome: str = Field(min_length=4, max_length=20)

    @field_validator('novo_nome', mode='before')
    @classmethod
    def formatar_iniciais(cls, v: str) -> str:
        if isinstance(v, str):
            v_limpo = v.strip()

            if not re.match(r'^[a-zA-ZÀ-ÿ\s]+$', v_limpo):
                raise ValueError('O campo deve conter apenas letras e espaços.')

            return v_limpo.title()
        return v


class ResponseProvincia(ProvinciaBase):
    municipio: List[ResponseMunicipio] = []
    model_config = ConfigDict(from_attributes=True)
