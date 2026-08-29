import uuid
import re
from datetime import date, datetime
from typing import Any, Dict, Optional
from project_part.model.models import (
    CadastrarComo,
    EstadoCivil,
    Genero,
    RoleCategoriaNotificacao,
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
    lido_as: datetime | None
    categoria: RoleCategoriaNotificacao | None = None

    # Aqui acontece a magia: injetamos o schema do utilizador dentro da resposta
    solicitante: UsuarioNotificacaoSchema | None 

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    total: int
    results: list[NotificationResponse]
