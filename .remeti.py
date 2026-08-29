import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# 1. Base Declarativa
class Base(DeclarativeBase):
    pass


# ---- ENUMS ----
class GenderEnum(PyEnum):
    MALE = 'M'
    FEMALE = 'F'
    OTHER = 'O'


class MaritalStatusEnum(PyEnum):
    SINGLE = 'solteiro'
    MARRIED = 'casado'
    DIVORCED = 'divorciado'
    WIDOWED = 'viuvo'


class DonationStatusEnum(PyEnum):
    PENDING = 'pendente'
    APPROVED = 'aprovado'
    REJECTED = 'rejeitado'


class EventStatusEnum(PyEnum):
    DRAFT = 'rascunho'
    PUBLISHED = 'publicado'
    CANCELLED = 'cancelado'
    CONCLUDED = 'concluido'


# ---- TABELAS DE ASSOCIAÇÃO (N:N) ----

# Relação N:N entre Roles e Permissions
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column(
        'role_id',
        Integer,
        ForeignKey('roles.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'permission_id',
        Integer,
        ForeignKey('permissions.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)

# Relação N:N entre Eventos e Participantes
event_participants = Table(
    'event_participants',
    Base.metadata,
    Column(
        'event_id',
        UUID(as_uuid=True),
        ForeignKey('events.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'user_id',
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column('attendance_status', String(20), default='registered'),  # registered, attended, absent
)

# ---- MODELOS PRINCIPAIS ----


class Province(Base):
    __tablename__ = 'provinces'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    municipalities: Mapped[List['Municipality']] = relationship(back_populates='province')


class Municipality(Base):
    __tablename__ = 'municipalities'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    province_id: Mapped[int] = mapped_column(ForeignKey('provinces.id', ondelete='RESTRICT'), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    province: Mapped['Province'] = relationship(back_populates='municipalities')


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    permissions: Mapped[List['Permission']] = relationship(secondary=role_permissions)


class Permission(Base):
    __tablename__ = 'permissions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    nif: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    number_militant: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    gender: Mapped[GenderEnum] = mapped_column(nullable=False)

    province_id: Mapped[int] = mapped_column(ForeignKey('provinces.id', ondelete='RESTRICT'), nullable=False)
    municipality_id: Mapped[int] = mapped_column(ForeignKey('municipalities.id', ondelete='RESTRICT'), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    membership_status_id: Mapped[int] = mapped_column(
        ForeignKey('membership_status.id', ondelete='RESTRICT'), default=1
    )

    marital_status: Mapped[Optional[MaritalStatusEnum]] = mapped_column(nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps & Auditoria de Conta
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Soft Delete

    # Relacionamentos
    scope: Mapped[Optional['AdminScope']] = relationship(back_populates='user', uselist=False)
    # cards: Mapped[List['MilitantCard']] = relationship(back_populates='user')


class AdminScope(Base):
    """Garante o controle territorial isolado para os administradores regionais"""

    __tablename__ = 'admin_scopes'

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    province_id: Mapped[Optional[int]] = mapped_column(ForeignKey('provinces.id', ondelete='SET NULL'), nullable=True)
    municipality_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('municipalities.id', ondelete='SET NULL'), nullable=True
    )

    user: Mapped['User'] = relationship(back_populates='scope')


class Event(Base):
    __tablename__ = 'events'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(ForeignKey('provinces.id'), nullable=True)
    municipality_id: Mapped[Optional[int]] = mapped_column(ForeignKey('municipalities.id'), nullable=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_participants: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[EventStatusEnum] = mapped_column(default=EventStatusEnum.DRAFT)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class News(Base):
    __tablename__ = 'news'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lead: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('news_categories.id'), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('provinces.id'), nullable=True
    )  # Notícia Regionalizada
    status: Mapped[str] = mapped_column(String(20), default='draft')  # draft, published, archived
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NewsCategory(Base):
    __tablename__ = 'news_categories'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class AuditLog(Base):
    """Armazena logs estruturados usando JSONB para consultas rápidas e auditorias jurídicas"""

    __tablename__ = 'audit_logs'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE, UPDATE, DELETE, APPROVE
    entity: Mapped[str] = mapped_column(String(50), nullable=False)  # users, donations, news
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Estado anterior do registro
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Novo estado modificado
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MilitantCard(Base):
    __tablename__ = 'militant_cards'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    card_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    qr_code_signature: Mapped[str] = mapped_column(Text, nullable=False)  # Token criptográfico anti-fraude
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    expiration_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    user: Mapped['User'] = relationship(back_populates='cards', foreign_keys=[user_id])


class Notification(Base):
    __tablename__ = 'notifications'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    lido_as: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class Session(Base):
    __tablename__ = 'sessions'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = 'documents'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # estatutos, diretrizes, atas
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = 'settings'

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


# class Donation(Base):
#     __tablename__ = 'donations'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('users.id', ondelete='SET NULL'),
#         nullable=True,
#     )  # Anonimização se deletado
#     amount: Mapped[float] = mapped_column(
#         Numeric(15, 2), nullable=False
#     )  # Proteção Monetária exata
#     payment_method: Mapped[str] = mapped_column(
#         String(50), nullable=False
#     )  # MCX, Transferência, IBAN
#     reference: Mapped[Optional[str]] = mapped_column(
#         String(100), unique=True, nullable=True
#     )
#     transaction_id: Mapped[Optional[str]] = mapped_column(
#         String(100), unique=True, nullable=True
#     )
#     currency: Mapped[str] = mapped_column(String(3), default='AOA')
#     status: Mapped[DonationStatusEnum] = mapped_column(
#         default=DonationStatusEnum.PENDING
#     )
#     donated_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )
#     approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True), ForeignKey('users.id'), nullable=True
#     )

#     receipt: Mapped[Optional['DonationReceipt']] = relationship(
#         back_populates='donation', uselist=False
#     )


# class DonationReceipt(Base):
#     __tablename__ = 'donation_receipts'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     donation_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('donations.id', ondelete='CASCADE'),
#         nullable=False,
#     )
#     file_url: Mapped[str] = mapped_column(Text, nullable=False)
#     generated_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )

#     donation: Mapped['Donation'] = relationship(back_populates='receipt')


# class MembershipStatus(Base):
#     __tablename__ = 'membership_status'

#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     name: Mapped[str] = mapped_column(
#         String(50), unique=True, nullable=False
#     )  # pending, approved, suspended, rejected


# class MembershipRequest(Base):
#     """Guarda o histórico e fluxo operacional de solicitações de entrada"""

#     __tablename__ = 'membership_requests'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     user_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('users.id', ondelete='CASCADE'),
#         nullable=False,
#     )
#     request_type: Mapped[str] = mapped_column(
#         String(50), default='militancy'
#     )  # militancy, promotion
#     status: Mapped[str] = mapped_column(
#         String(30), default='pending'
#     )  # pending, approved, rejected
#     approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True), ForeignKey('users.id'), nullable=True
#     )
#     approved_at: Mapped[Optional[datetime]] = mapped_column(
#         DateTime, nullable=True
#     )
#     notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )
