from decimal import Decimal
from uuid import UUID
from typing import Any, Optional, Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from project_part.db.session import get_session

from project_part.model.models import (
    MovimentoFinanceiro,
    TipoMovimentoEnum,
    AcaoMovimentoEnum,
)

Session = Annotated[AsyncSession, Depends(get_session)]


async def registar_movimento(
    session: Session,
    *,
    tipo: TipoMovimentoEnum,
    origem_id: UUID,
    quantia: Decimal,
    moeda: str,
    acao: AcaoMovimentoEnum,
    status_novo: str,
    status_anterior: Optional[str] = None,
    user_id: Optional[UUID] = None,
    ator_id: Optional[UUID] = None,
    detalhe: Optional[dict[str, Any]] = None,
) -> MovimentoFinanceiro:
    mov = MovimentoFinanceiro(
        tipo=tipo,
        origem_id=origem_id,
        user_id=user_id,
        quantia=quantia,
        moeda=moeda,
        status_anterior=status_anterior,
        status_novo=status_novo,
        acao=acao,
        ator_id=ator_id,
        detalhe=detalhe,
    )
    session.add(mov)
    return mov