import uuid
import re
from enum import Enum
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Dict, Optional, Annotated
from project_part.model.models import (
    CadastrarComo,
    EstadoCivil,
    Genero,
    RoleCategoriaNotificacao,
    RoleMensagemSuporte,
    MetodoPagamentoEnum,
    DonationStatusEnum,
    QuotaStatusEnum,
    FinalidadeFundoEnum,
    DespesaStatusEnum,
    StatusSolicitacao,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

class AdminScopeBase(BaseModel):
    nome_provincia: str | None
    nome_municipio: str | None
    email: EmailStr


class CreateAdminScope(AdminScopeBase): ...


class ResponseAdminScopeBase(BaseModel):
    provincia_id: uuid.UUID | None
    municipio_id: uuid.UUID | None
    user_id: uuid.UUID




class ResponseAdminScope(BaseModel):
    id: uuid.UUID
    provincia: str | None = None
    municipio: str | None = None
    user_id: uuid.UUID

    nome_completo: str
    email: EmailStr
    data_nascimento: date | None = None
    militante_numero: str | None = None
    telefone: str | None = None
    genero: str | None = None
    estado_civil: str | None = None
    foi_militante: bool

    nome_provincia: str | None = None
    nome_municipio: str | None = None

    ativo: bool

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')
    
        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')
    
    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    usuario_id: Optional[uuid.UUID]
    accao: str
    entidade: str
    entidade_id: str
    ultimo_valores: Optional[Dict[str, Any]] = None  # Transforma JSONB em dicionário Python
    novo_valores: Optional[Dict[str, Any]] = None  # Transforma JSONB em dicionário Python
    ip_endereco: Optional[str]
    user_agent: Optional[str]
    criado_as: datetime

    class Config:
        from_attributes = True


class PaginatedAuditLogs(BaseModel):
    total: int
    page: int
    limit: int
    results: list[AuditLogResponse]


class UsuarioNotificacaoSchema(BaseModel):
    nome_completo: str
    email: str

    model_config = ConfigDict(from_attributes=True)

# 2. Define a estrutura da Notificação enviada para o Frontend
class NotificationResponse(BaseModel):
    id: uuid.UUID
    titulo: str
    mensagem: str
    destinatario: str | None
    criado_as: datetime
    motivo: str | None
    lido_as: datetime | None
    categoria: RoleCategoriaNotificacao | None = None

    # Aqui acontece a magia: injetamos o schema do utilizador dentro da resposta
    solicitante: UsuarioNotificacaoSchema | None 

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    total: int
    results: list[NotificationResponse]



class SolicitanteCartaoResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    image_url: str
    numero_cartao: str
    nome_militante: str
    data_emissao: datetime
    data_nascimento: date
    status: StatusSolicitacao 
    ativo: bool


    model_config = ConfigDict(from_attributes=True)

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)
    municipio: str
    provincia: str

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')

class CardSolicitante(BaseModel):
    total: int
    results: list[SolicitanteCartaoResponse]




class MensagemSuporteResponse(BaseModel):
    id: uuid.UUID
    categoria: str
    assunto: str
    mensagem: str
    status: RoleMensagemSuporte
    criado_as: datetime
    user_id: uuid.UUID | None = None
    admin_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class MensagensSuportePaginadasResponse(BaseModel):
    # total: int
    results: list[MensagemSuporteResponse]

EmailValided = Annotated[EmailStr, StringConstraints(to_lower=True, strip_whitespace=True)]


class ValidarFilterSimpatizante(BaseModel):
    email: EmailValided | None = Field(max_length=255)
    nif: str | None = None

    @field_validator('nif')
    @classmethod
    def validar_nif(cls, val_nif: str) -> str:
        nif_limpo = val_nif.strip().upper()

        padrao_nif = r'^(\d{9}[A-Z]{2}\d{3}|\d{9}[A-Z]\d{3}[A-Z])$'
        if not re.match(padrao_nif, nif_limpo):
            raise ValueError('NIF inválido! Certifique-se de introduzir um NIF de Angola válido com 14 caracteres')
        return nif_limpo

class UserResponse(BaseModel):
    nome_completo: str
    genero: Genero | None = None
    criado_em: datetime
    ativo: bool
    provincia: str
    municipio: str


    model_config = ConfigDict(from_attributes=True, ser_json_circular_logic='ignore')

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')


class RegistrosRecentes(BaseModel):
    total: int
    results: list[UserResponse]

class DistribuicaoGenero(BaseModel):
    total: int
    masculino: int
    feminino: int
    percentual_masculino: float
    percentual_feminino: float


class RegistrosFinanceirosResponse(BaseModel):
    total_registros: int  # soma dos três


class MilitantesTerritorioItem(BaseModel):
    id: int
    nome: str
    masculino: int
    feminino: int
    idade: str          # ex: "18-45"
    total: int


class MilitantesTerritorioResponse(BaseModel):
    total_geral: int
    results: list[MilitantesTerritorioItem]


class DoacaoResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    quantia: Decimal
    moeda: str
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None
    id_transacao: str | None
    status: DonationStatusEnum
    observacao: str | None
    data_doacao: datetime
    aprovado_por: uuid.UUID | None
    aprovado_em: datetime | None
    recibo_url: str | None
    recibo_gerado_em: datetime | None
    atualizado_em: datetime
    nome_doador: str | None = None

    provincia: str


    model_config = ConfigDict(from_attributes=True, ser_json_circular_logic='ignore')

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')


class DoacaoList(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[DoacaoResponse]

class DoacaoRejeitar(BaseModel):
    observacao: str = Field(..., min_length=3, max_length=500)



class QuotaResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    quantia: Decimal
    moeda: str
    militante_numero: str | None
    periodo: str
    metodo_pagamento: MetodoPagamentoEnum
    referencia: str | None
    id_transacao: str | None
    status: QuotaStatusEnum
    observacao: str | None
    data_pagamento: datetime
    aprovado_por: uuid.UUID | None
    aprovado_em: datetime | None
    atualizado_em: datetime
    nome_militante: str | None = None

    model_config = ConfigDict(from_attributes=True)


class QuotaList(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[QuotaResponse]

class QuotaRejeitar(BaseModel):
    observacao: str = Field(..., min_length=3, max_length=500)




class SolicitacaoFundoCreate(BaseModel):
    finalidade: FinalidadeFundoEnum
    descricao: str = Field(..., min_length=5, max_length=500)
    quantia: Decimal = Field(..., gt=0, decimal_places=2)
    observacao: str | None = Field(None, max_length=500)


class SolicitacaoFundoRejeitar(BaseModel):
    observacao: str = Field(..., min_length=3, max_length=500)


class SolicitacaoFundoResponse(BaseModel):
    id: uuid.UUID
    provincia_id: int
    municipio_id: int | None
    finalidade: FinalidadeFundoEnum
    descricao: str
    quantia: Decimal
    moeda: str
    status: DespesaStatusEnum
    observacao: str | None
    solicitado_por: uuid.UUID | None
    aprovado_por: uuid.UUID | None
    data_solicitacao: datetime
    aprovado_em: datetime | None
    nome_provincia: str | None = None
    nome_solicitante: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SolicitacaoFundoList(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[SolicitacaoFundoResponse]



class ResumoFinanceiroResponse(BaseModel):
    receitas: Decimal
    despesas: Decimal
    saldo: Decimal
    moeda: str = 'AOA'


class SolicitacoesFundoContadores(BaseModel):
    pendentes: int
    aprovadas: int
    rejeitadas: int

class TipoMovimentacaoUI(str, Enum):
    RECEITA = 'RECEITA'
    DESPESA = 'DESPESA'


class MovimentacaoItem(BaseModel):
    tipo: TipoMovimentacaoUI
    descricao: str
    provincia: str | None
    data: datetime
    valor: Decimal  # positivo = receita; o front pode mostrar despesa a vermelho


class MovimentacoesList(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[MovimentacaoItem]



class ReativarUserResponse(BaseModel):
    msg: str
    user_id: uuid.UUID
    email: str
    ativo: bool