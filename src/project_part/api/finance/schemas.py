from decimal import Decimal
from datetime import datetime
import uuid
from pydantic import BaseModel, Field, ConfigDict
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
    quantia: Decimal = Field(..., gt=0, decimal_places=2)
    periodo: str = Field(..., pattern=r'^\d{4}(-\d{2})?$', description='YYYY ou YYYY-MM')
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None = None
    id_transacao: str | None = None
    observacao: str | None = None
