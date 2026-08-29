from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from project_part.core.setting import settings
from project_part.db.audit_helper import processar_auditoria_sessao

engine = create_async_engine(settings.BASE_URL)


async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        # Criamos um "interceptador" local do método commit nativo da sessão
        orig_commit = session.commit

        async def audit_and_commit():
            # Dispara a varredura e injeta os registros de log na transação aberta
            await processar_auditoria_sessao(session)
            # Executa o commit real agregando todas as alterações na mesma transação atômica
            return await orig_commit()

        # Substitui dinamicamente o método commit para esta instância de sessão
        session.commit = audit_and_commit

        try:
            yield session
        finally:
            await session.close()
