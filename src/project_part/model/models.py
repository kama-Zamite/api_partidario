from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    TEXT,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from src.project_part.db.base import Base

role_permissoes = Table(
    'role_permissoes',
    Base.metadata,
    Column(
        'role_id',
        Integer,
        ForeignKey('roles.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'permissoes_id',
        Integer,
        ForeignKey('permissoes.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    extend_existing=True,
)


event_participants = Table(
    'event_participants',
    Base.metadata,
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('events_id', UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), primary_key=True),
    Column('attendance_status', String(20), nullable=False, default='Registrado'),
    extend_existing=True,
)


class StatusSolicitacao(str, Enum):
    PENDENTE = 'PENDENTE'
    APROVADO = 'APROVADO'
    REJEITADO = 'REJEITADO'


class StatusSolicitacaoMilitancia(str, Enum):
    PENDENTE = 'PENDENTE'
    APROVADO = 'APROVADO'
    REJEITADO = 'REJEITADO'


class CadastrarComo(str, Enum):
    MILITANTE = 'MILITANTE'
    SIMPATIZANTE = 'SIMPATIZANTE'


class Genero(str, Enum):
    MULHER = 'MULHER'
    HOMEM = 'HOMEM'


class EstadoCivil(str, Enum):
    SOLTEIRO = 'SOLTEIRO'
    CASADO = 'CASADO'
    DIVORCIADO = 'DIVORCIADO'
    VIUVO = 'VIUVO'


class EventStatusEnum(str, Enum):
    RASCUNHO = 'RASCUNHO'
    PUBLICADO = 'PUBLICADO'
    CANCELADO = 'CANCELADO'
    CONCLUIDO = 'CONCLUIDO'

class EventoCategoriaEnum(str, Enum):
    # Categorias Existentes
    POLITICA = 'POLITICA'
    SOCIAL = 'SOCIAL'
    CULTURAL = 'CULTURAL'
    ESPORTIVO = 'ESPORTIVO'
    
    # Novas Categorias Adicionadas
    CONFERENCIA = 'CONFERENCIA'
    COMICIO = 'COMICIO'
    REUNIAO = 'REUNIAO'
    FORMACAO = 'FORMACAO'
    CONGRESSO = 'CONGRESSO'
    ACTO_PUBLICO = 'ACTO_PUBLICO'
    VISITA = 'VISITA'
    WORKSHOP = 'WORKSHOP'
    DESTAQUE = 'DESTAQUE'

    OUTROS = 'OUTROS'



class NoticiasStatusEnum(str, Enum):
    RASCUNHO = 'RASCUNHO'
    PUBLICADO = 'PUBLICADO'
    CANCELADO = 'CANCELADO'
    CONCLUIDO = 'CONCLUIDO'


class RoleCategoriaNotificacao(str, Enum):
    SOLICITACAO_CARTAO = 'SOLICITACAO_CARTAO'
    BEM_VINDO = 'BEM_VINDO'
    EVENTOS = 'EVENTOS'
    NOTICIAS = 'NOTICIAS'
    QUOTA = 'QUOTA'

class RoleMensagemSuporte(str, Enum):
    PENDENTE = 'Pendente'
    EM_ANDAMENTO = 'Em_andamento'
    RESOLVIDO = 'resolvido'

class CategoriaMensagemSuporte(str, Enum):
    PAGAMENTOS_QUOTAS = "Pagamento_de_Quota"
    SUGESTOES = "Sugestoes"
    SUPORTE_TECNICO = "Suporte_Tecnico"
    PROBLEMA_DE_CONTA = "Problema_de_Conta"
    OUTROS = "Outros"



    


# ROLE_HIERARCHY = {
#     "super_admin": 3,
#     "provincial_admin": 2,
#     "municipal_admin": 1,
#     "usuario": 0
# }


class Provincia(Base):
    __tablename__ = 'provincias'

    nome_provincia: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )
    municipio: Mapped[List[Municipio]] = relationship(back_populates='provincia', cascade='all, delete-orphan')


class Municipio(Base):
    __tablename__ = 'municipios'

    nome_municipio: Mapped[str] = mapped_column(String(100), nullable=False)
    id_provincia: Mapped[int] = mapped_column(ForeignKey('provincias.id', ondelete='RESTRICT'), nullable=False)
    provincia: Mapped[Provincia] = relationship(back_populates='municipio')
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )
    __table_args__ = (UniqueConstraint('nome_municipio', 'id_provincia', name='uq_municipio_provincia'),)


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[int] = mapped_column(Integer, index=True, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    permissoes: Mapped[List[Permissao]] = relationship(secondary=role_permissoes)


class Permissao(Base):
    __tablename__ = 'permissoes'

    id: Mapped[int] = mapped_column(Integer, index=True, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, primary_key=True, default=uuid.uuid4)
    # Aumentado para 150 para suportar apelidos longos
    nome_completo: Mapped[str] = mapped_column(String(150), nullable=False)

    image_url: Mapped[None|str] = mapped_column(TEXT, nullable=True)
    email: Mapped[str] = mapped_column(String(255), index=True, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(TEXT, nullable=False)
    data_nascimento: Mapped[date] = mapped_column(Date, nullable=False)
    nif: Mapped[str] = mapped_column(String(14), index=True, unique=True, nullable=False)
    # codigo_verificacao_email: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)
    # whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    genero: Mapped[Genero] = mapped_column(default=Genero.HOMEM, nullable=False)
    cadastrar_militante: Mapped[CadastrarComo] = mapped_column(default=CadastrarComo.MILITANTE, nullable=True)

    provincia_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('provincias.id', ondelete='RESTRICT'), nullable=False
    )
    municipio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('municipios.id', ondelete='RESTRICT'), nullable=False
    )
    role_id: Mapped[int] = mapped_column(ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    foi_militante: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    militante_numero: Mapped[None | str] = mapped_column(
        String(20), unique=True, index=True, nullable=True, default=None
    )

    #privacy
    partilha_dados: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cookies_personalizacao: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 2FA
    two_factor_secret: Mapped[None | str] = mapped_column(String(255), nullable=True, default=None)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


    #notificacoes
    notificacoes_gerais: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comunicados_oficiais: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    eventos_mobilizacoes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    contribuicoes_quota: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    noticias_partido: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


    # Relacionamentos
    scope: Mapped[Optional['AdminScope']] = relationship(
        uselist=False, back_populates='user', cascade='all, delete-orphan'
    )
    refresh_tokens = relationship("UserRefreshToken", back_populates="user")

    # CORREÇÃO: Especificar qual chave estrangeira liga o User aos seus cartões habituais
    cards: Mapped[List['CartaoMilitante']] = relationship(
        'CartaoMilitante', back_populates='user', foreign_keys='CartaoMilitante.user_id'
    )
    provincia: Mapped[Provincia] = relationship()
    municipio: Mapped[Municipio] = relationship()
    role: Mapped[Optional[Role]] = relationship()


    criado_em: Mapped[None | datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    password_alterado_em: Mapped[None | datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deletado_em: Mapped[None | datetime] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    ultimo_login: Mapped[None | datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True, default=None
    )

    # Segurança e Bloqueios
    estado_civil: Mapped[EstadoCivil] = mapped_column(nullable=True, default=EstadoCivil.SOLTEIRO)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    tentativa_acertos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_ate: Mapped[None | datetime] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    tentativas_apos_bloqueio: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    bloqueado_permanente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)

    __table_args__ = (
        CheckConstraint('email = lower(email) AND length(trim(email)) > 0', name='check_email_valido'),
        CheckConstraint("data_nascimento <= CURRENT_DATE - INTERVAL '18 years'", name='check_maior_idade'),
        CheckConstraint('nif = upper(nif) AND length(trim(nif)) = 14', name='check_nif_angola'),
        CheckConstraint('length(trim(telefone)) > 0', name='check_telefone_preenchido'),
    )


class UserRefreshToken(Base):
    __tablename__ = "user_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identificador único do refresh token dentro do JWT.
    token_jti: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        index=True,
        nullable=False,
    )

    # Metadados para auditoria.
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Estado.
    revogado: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    utilizado: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Datas.
    criado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expira_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    revogado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    utilizado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="refresh_tokens",
    )


class PasswordResetToken(Base):
    __tablename__ = 'password_reset_tokens'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False
    )
    usado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CartaoMilitante(Base):
    __tablename__ = 'cartao_militantes'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, primary_key=True, default=uuid.uuid4)
    nome_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    militante_numero: Mapped[str] = mapped_column(String(20), index=True, unique=True, nullable=False)
    image_url: Mapped[str] = mapped_column(TEXT, nullable=False)
    url_qrcode: Mapped[str] = mapped_column(TEXT, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False
    )

    gerado_por: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    provincia_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('provincias.id', ondelete='RESTRICT'), nullable=False
    )
    municipio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('municipios.id', ondelete='RESTRICT'), nullable=False
    )

    # numero_cartao: Mapped[str] = mapped_column(String(50), index=True, unique=True, nullable=False)
    qr_code_assinatura: Mapped[str] = mapped_column(TEXT, nullable=False)

    data_emissao: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped['User'] = relationship('User', back_populates='cards', foreign_keys=[user_id])
    emissor: Mapped['User'] = relationship('User', foreign_keys=[gerado_por])
    provincia: Mapped[Provincia] = relationship()
    municipio: Mapped[Municipio] = relationship()


class AdminScope(Base):
    __tablename__ = 'admin_scopes'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    provincia_id: Mapped[None | int] = mapped_column(
        Integer, ForeignKey('provincias.id', ondelete='CASCADE'), nullable=True, default=None
    )
    municipio_id: Mapped[None | int] = mapped_column(
        Integer, ForeignKey('municipios.id', ondelete='CASCADE'), nullable=True, default=None
    )

    user: Mapped[User] = relationship(back_populates='scope')
    provincia: Mapped[Provincia] = relationship()
    municipio: Mapped[Municipio] = relationship()



# class EventoCategoria(Base):
#     __tablename__ = 'evento_categorias'

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

#     eventos: Mapped[List[Event]] = relationship(back_populates='categoria', cascade='all, delete-orphan')


class Event(Base):
    __tablename__ = 'events'

    titulo: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    descricao: Mapped[str] = mapped_column(TEXT, nullable=False)
    localizacao: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    data_inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # data_fim: Mapped[datetime] = mapped_column(
    #     DateTime,
    #     nullable=False
    # )
    criado_por: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    # participantes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    provincia_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('provincias.id'), nullable=False
    )
    municipio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('municipios.id'), nullable=False
    )
    categoria: Mapped[str] = mapped_column(
        default=EventoCategoriaEnum.OUTROS, nullable=False
    )

    max_participantes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    status: Mapped[EventStatusEnum] = mapped_column(default=EventStatusEnum.RASCUNHO)
    criado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)

    provincia: Mapped[Optional[Provincia]] = relationship()
    municipio: Mapped[Optional[Municipio]] = relationship()

    __table_args__ = (
        # CheckConstraint('data_fim > data_inicio', name='check_datas_evento_cronologia'),
        CheckConstraint('max_participantes > 0', name='check_max_participantes_positivo'),
    )


class Noticia(Base):
    __tablename__ = 'noticias'

    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    subtitulo: Mapped[None | str] = mapped_column(String(255), nullable=True)
    lead: Mapped[None | str] = mapped_column(TEXT, nullable=True)
    corpo: Mapped[str] = mapped_column(TEXT, nullable=False)
    image_url: Mapped[None | str] = mapped_column(TEXT, nullable=True)

    categoria_id: Mapped[int] = mapped_column(ForeignKey('noticia_categorias.id', ondelete='CASCADE'), nullable=False)
    autor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    provincia_id: Mapped[int] = mapped_column(
        ForeignKey('provincias.id', ondelete='CASCADE'), nullable=True
    )
    municipio_id: Mapped[int] = mapped_column(
        ForeignKey('municipios.id', ondelete='CASCADE'), nullable=True
    )

    publicado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    atualizado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    status: Mapped[str] = mapped_column(String(20), default=NoticiasStatusEnum.RASCUNHO, nullable=False)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    categoria: Mapped[NoticiaCategoria] = relationship(back_populates='noticias')
    provincia: Mapped[Optional[Provincia]] = relationship()
    municipio: Mapped[Optional[Municipio]] = relationship()


class NoticiaCategoria(Base):
    __tablename__ = 'noticia_categorias'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    noticias: Mapped[List[Noticia]] = relationship(back_populates='categoria', cascade='all, delete-orphan')


class AuditLog(Base):
    """Armazena logs estruturados usando JSONB para consultas rápidas e auditorias jurídicas"""

    __tablename__ = 'audit_logs'

    usuario_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    accao: Mapped[str] = mapped_column(String(50), nullable=False)
    entidade: Mapped[str] = mapped_column(String(50), nullable=False)
    entidade_id: Mapped[str] = mapped_column(String(50), nullable=False)
    ultimo_valores: Mapped[None |dict] = mapped_column(JSONB, nullable=True)
    novo_valores: Mapped[None |dict] = mapped_column(JSONB, nullable=True)
    ip_endereco: Mapped[None |str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[None |str] = mapped_column(TEXT, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)


class SolicitacaoCartao(Base):
    __tablename__ = 'solicitacoes_cartao'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    status: Mapped[StatusSolicitacao] = mapped_column(default=StatusSolicitacao.PENDENTE, index=True, nullable=False)
    observacao: Mapped[None | str] = mapped_column(TEXT, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped["User"] = relationship("User")
    __table_args__ = (
        Index(
            'uq_cartao_pendente_usuario',
            'user_id',
            unique=True,
            postgresql_where=(status == StatusSolicitacao.PENDENTE.value),
        ),
    )


class SolicitacaoMilitancia(Base):
    __tablename__ = 'solicitacoes_militancia'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    status: Mapped[StatusSolicitacaoMilitancia] = mapped_column(
        default=StatusSolicitacaoMilitancia.PENDENTE, index=True, nullable=False
    )
    observacao: Mapped[None | str] = mapped_column(TEXT, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            'uq_solicitacao_pendente_usuario',
            'user_id',
            unique=True,
            postgresql_where=(status == StatusSolicitacaoMilitancia.PENDENTE.value),
        ),
    )


class Notification(Base):
    __tablename__ = 'notifications'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        index=True,
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        index=True,
        nullable=True,
    )
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    mensagem: Mapped[str] = mapped_column(TEXT, nullable=False)
    lido_as: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    destinatario: Mapped[str | None] = mapped_column(String(20), default='MILITANTE', index=True, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    categoria: Mapped[str | None] = mapped_column(default=RoleCategoriaNotificacao.SOLICITACAO_CARTAO, nullable=True)


    solicitante: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class MensagemSuporte(Base):
    __tablename__ = "mensagens_suporte"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    categoria: Mapped[CategoriaMensagemSuporte] = mapped_column(default=CategoriaMensagemSuporte.OUTROS, nullable=False)
    assunto: Mapped[str] = mapped_column(String(200), nullable=False)
    mensagem: Mapped[str] = mapped_column(TEXT, nullable=False)
    status: Mapped[RoleMensagemSuporte] = mapped_column(String(30), nullable=False, default=RoleMensagemSuporte.PENDENTE)
    criado_as: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    admin_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    solicitante: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[user_id], lazy="selectin"
    )
    admin: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[admin_id], lazy="selectin"
    )


class BackupCode(Base):
    __tablename__ = "user_backup_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey('users.id', ondelete='CASCADE'),
            index=True,
            nullable=True,
        )
    # Guarda o HASH do código (nunca o texto limpo)
    code_hash: Mapped[str] = mapped_column(TEXT, nullable=False)
    used: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now(), nullable=False)




