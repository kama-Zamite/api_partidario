import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Any

from sqlalchemy import (
    String, Text, ForeignKey, Numeric, DateTime, Integer,
    CheckConstraint, Index, func,
)


from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from project_part.db.base import Base
# from project_part.model.models import User
from .models import User


class MetodoPagamentoEnum(str, Enum):
    MCX = 'MCX'
    TRANSFERENCIA = 'TRANSFERENCIA'
    IBAN = 'IBAN'


class DonationStatusEnum(str, Enum):
    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'


class QuotaStatusEnum(str, Enum):
    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'


class TipoMovimentoEnum(str, Enum):
    DOACAO = 'DOACAO'
    QUOTA = 'QUOTA'


class AcaoMovimentoEnum(str, Enum):
    CRIADA = 'CRIADA'
    APROVADA = 'APROVADA'
    REJEITADA = 'REJEITADA'
    CANCELADA = 'CANCELADA'
    ATUALIZADA = 'ATUALIZADA'


class Doacao(Base):
    __tablename__ = 'doacoes'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    quantia: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    moeda: Mapped[str] = mapped_column(String(3), default='AOA', nullable=False)
    metodo_pagamento: Mapped[MetodoPagamentoEnum] = mapped_column(nullable=False)
    referencia: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    id_transacao: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    status: Mapped[DonationStatusEnum] = mapped_column(
        default=DonationStatusEnum.PENDING, nullable=False, index=True
    )
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_doacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    aprovado_por: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    aprovado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
        )
    recibo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recibo_gerado_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    doador: Mapped[Optional['User']] = relationship(
        'User', foreign_keys=[user_id], back_populates='doacoes'
    )
    aprovador: Mapped[Optional['User']] = relationship('User', foreign_keys=[aprovado_por])

    __table_args__ = (
        CheckConstraint('quantia > 0', name='ck_doacao_quantia_positiva'),
        Index('ix_doacoes_status_data', 'status', 'data_doacao'),
    )


class PagamentoQuota(Base):
    __tablename__ = 'pagamentos_quota'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    quantia: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    moeda: Mapped[str] = mapped_column(String(3), default='AOA', nullable=False)
    # Ex.: "2026-01" ou "2026"
    periodo: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    metodo_pagamento: Mapped[MetodoPagamentoEnum] = mapped_column(nullable=False)
    referencia: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    id_transacao: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    status: Mapped[QuotaStatusEnum] = mapped_column(
        default=QuotaStatusEnum.PENDING, nullable=False, index=True
    )
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_pagamento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    aprovado_por: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    aprovado_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    militante: Mapped['User'] = relationship('User', foreign_keys=[user_id], back_populates='pagamentos_quota')
    aprovador: Mapped[Optional['User']] = relationship('User', foreign_keys=[aprovado_por])

    __table_args__ = (
        CheckConstraint('quantia > 0', name='ck_quota_quantia_positiva'),
        Index('ix_quota_user_periodo', 'user_id', 'periodo'),
        Index('ix_quota_status_data', 'status', 'data_pagamento'),
    )


class MovimentoFinanceiro(Base):
    """Auditoria append-only. Nunca atualizar/apagar em produção."""
    __tablename__ = 'movimentos_financeiros'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tipo: Mapped[TipoMovimentoEnum] = mapped_column(nullable=False, index=True)
    origem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True
    )
    quantia: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    moeda: Mapped[str] = mapped_column(String(3), default='AOA', nullable=False)
    status_anterior: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status_novo: Mapped[str] = mapped_column(String(20), nullable=False)
    acao: Mapped[AcaoMovimentoEnum] = mapped_column(nullable=False, index=True)
    ator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    detalhe: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index('ix_mov_tipo_origem', 'tipo', 'origem_id'),
        Index('ix_mov_acao_data', 'acao', 'criado_em'),
    )