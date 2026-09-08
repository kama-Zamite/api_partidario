from decimal import Decimal
from datetime import datetime
import uuid
import re
from pydantic import BaseModel, Field, ConfigDict, field_validator
from project_part.model.models import MetodoPagamentoEnum, DonationStatusEnum


class DoacaoCreate(BaseModel):
    quantia: Decimal = Field(..., gt=0, decimal_places=2)
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None = None
    id_transacao: str | None = None
    observacao: str | None = None


class DoacaoRejeitar(BaseModel):
    observacao: str = Field(..., min_length=3, max_length=500)


class QuotaCreate(BaseModel):
    quantia: Decimal = Field(..., gt=200, decimal_places=2, description='Valor mínimo de 200 AOA')
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None = None
    id_transacao: str | None = None
    meses_pagar: int = Field(..., gt=0, description='Número de meses a pagar (deve ser maior que 0)')
    observacao: str | None = None  

    @field_validator('referencia')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
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
