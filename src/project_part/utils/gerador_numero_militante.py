import secrets
import logging
from sqlalchemy import select
from fastapi import status, HTTPException
from project_part.model.models import User


logger = logging.getLogger(__name__)

async def atribuir_codigo_militante(session):
    tentativas = 0
    while tentativas < 5:

        # 1. Gera o código de 7 dígitos
        novo_codigo = str(secrets.randbelow(9000000) + 1000000)
        
        existe = await session.scalar(
            select(User).where(User.militante_numero == novo_codigo)
        )

        if not existe:
            logger.info(f"Código de militante gerado com sucesso: {novo_codigo}")
            return novo_codigo
        tentativas += 1
    else:
        logger.error("Falha crítica: Excedeu o limite de tentativas para gerar um número de cartão único.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro de infraestrutura ao gerar número de cartão."
        )
