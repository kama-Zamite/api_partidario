from datetime import datetime, date 
from pydantic import BaseModel, ConfigDict, Field, EmailStr
from uuid import UUID
from project_part.model.models import EstadoCivil, Genero, CadastrarComo
from typing import Optional

class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome_completo: str
    image_url: Optional[str] = None

    # Contactos
    email: EmailStr
    email_recuperacao: Optional[EmailStr] = None
    telefone: str

    # Dados pessoais
    data_nascimento: date
    nif: str
    genero: Genero
    estado_civil: Optional[EstadoCivil] = None

    # Associação geográfica e permissões
    provincia_id: int
    municipio_id: int
    role_id: int

    # Dados de militância
    cadastrar_militante: Optional[CadastrarComo] = None
    foi_militante: Optional[bool] = False
    militante_numero: Optional[str] = None

    # Privacidade
    partilha_dados: bool = False
    cookies_personalizacao: bool = False
    consentimento_lpd: Optional[bool] = False
    concedido_em: Optional[datetime] = None
    versao_politica_apd: Optional[str] = None

    # Autenticação de dois fatores
    two_factor_enabled: bool = False

    # Notificações
    notificacoes_gerais: bool = True
    comunicados_oficiais: bool = True
    eventos_mobilizacoes: bool = True
    contribuicoes_quota: bool = True
    noticias_partido: bool = True

    # Quotas
    data_expiracao_quota: Optional[date] = None
    notificado_quota_atraso_em: Optional[date] = None

    # Estado da conta e bloqueios
    ativo: bool = True
    bloqueado_permanente: Optional[bool] = False
    bloqueado_ate: Optional[datetime] = None
    tentativa_acertos: int = 0
    tentativas_apos_bloqueio: Optional[int] = 0

    # Datas de auditoria
    criado_em: Optional[datetime] = None
    atualizado_em: Optional[datetime] = None
    deletado_em: Optional[datetime] = None
    ultimo_login: Optional[datetime] = None
    password_alterado_em: Optional[datetime] = None