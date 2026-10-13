from decimal import Decimal
from datetime import datetime
import uuid
import re
from pydantic import BaseModel, Field, ConfigDict, field_validator
from project_part.model.models import MetodoPagamentoEnum, DonationStatusEnum


class DoacaoCreate(BaseModel):
    quantia: Decimal = Field(..., gt=0, decimal_places=2)
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None = Field(
        default=None,
        min_length=9,
        max_length=9,
        pattern=r"^\d+$",
        description="Referência numérica obrigatória com exatamente 9 dígitos",
        strip_whitespace=True
    )
    id_transacao: str | None = Field(
        default=None, 
        min_length=8, 
        max_length=8, 
        pattern=r"^\d+$",
        description="Identificador da transação (máx 8 dígitos)",
        strip_whitespace=True
    )
    observacao: str | None =Field(default=None, max_length=500, strip_whitespace=True)
    @field_validator('referencia')
    @classmethod
    def validar_referencia(cls, v: str) -> str :
        if v is None or v == "":
            raise ValueError("A referência não pode ser vazia")
        if not re.fullmatch(r"\d{9}", v):
            raise ValueError("A referência deve ter exatamente 9 dígitos")
        return v

    @field_validator('id_transacao')
    @classmethod
    def validar_id_transacao(cls, v: str) -> str :
        if v is None or v == "":
            raise ValueError("O identificador da transação não pode ser vazio")
        if not re.fullmatch(r"\d{8}", v):
            raise ValueError("O identificador da transação deve ter exatamente 8 dígitos")
        return v
    @field_validator('observacao')
    @classmethod
    def validar_observacao(cls, v: str | None) -> str | None:
        if v == "":
            raise ValueError("A observação não pode ser vazia")
        return v


class DoacaoRejeitar(BaseModel):
    observacao: str = Field(..., min_length=3, max_length=500, strip_whitespace=True)

    @field_validator('observacao')
    @classmethod
    def validar_observacao(cls, v: str) -> str:
        if v == "":
            raise ValueError("A observação não pode ser vazia")
        return v


class QuotaCreate(BaseModel):
    quantia: Decimal = Field(
        ...,
        ge=200,
        decimal_places=2,
        description='Valor mínimo de 200 AOA',
        strip_whitespace=True
    )
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None = Field(
        default=None,
        min_length=9,
        max_length=9,
        pattern=r"^\d+$",
        description="Referência numérica obrigatória com exatamente 9 dígitos",
        strip_whitespace=True
    )
    id_transacao: str | None = Field(
        default=None, 
        min_length=8, 
        max_length=8, 
        pattern=r"^\d+$",
        description="Identificador da transação (máx 8 dígitos)",
        strip_whitespace=True
    )
    meses_pagar: int = Field(
        ...,
        gt=0,
        le=24,
        description='Número de meses a pagar (1 a 24)',
        strip_whitespace=True
    )
    observacao: str | None = None

    @field_validator('referencia')
    @classmethod
    def validar_referencia(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("A referência não pode ser vazia")
        return v

    @field_validator('id_transacao')
    @classmethod
    def validar_id_transacao(cls, v: str | None) -> str | None:
        if v is None or v == "":
            raise ValueError("O identificador da transação não pode ser vazio")
        return v

    @field_validator('observacao')
    @classmethod
    def validar_observacao(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v == "":
            raise ValueError("A observação não pode ser vazia")
        return v

    @field_validator('meses_pagar')
    @classmethod
    def validar_meses_pagar(cls, v: int) -> int:
        if v < 1 or v > 24:
            raise ValueError("O número de meses a pagar deve estar entre 1 e 24")
        return v
    @field_validator('referencia')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str | None) -> str | None:
        if tel_number is None or tel_number == "":
            raise ValueError("O número de telefone não pode ser vazio")

        numero_limpo = re.sub(r'[^\d+]', '', tel_number.strip())

        if numero_limpo.startswith('+244'):
            filtrar_numero = numero_limpo[4:]
        elif numero_limpo.startswith('244'):
            filtrar_numero = numero_limpo[3:]
        else:
            filtrar_numero = numero_limpo

        angola_padrao_valido = r'^(91|92|93|94|95|99)\d{7}$'

        if not re.match(angola_padrao_valido, filtrar_numero):
            raise ValueError(
                'Número de telefone inválido. Deve ser um número de Angola válido com 9 dígitos '
                '(ex: 923000000) ou incluir o prefixo +244.'
            )
        return f'+244{filtrar_numero}'