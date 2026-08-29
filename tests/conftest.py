import asyncio
import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# 1. Importa a base estrutural
# Os modelos importam a Base por ``src.project_part``; usar a mesma instância
# evita criar as tabelas em um metadata diferente durante os testes SQLite.
from src.project_part.db.base import Base

# 2. Importa os modelos originais
from project_part.model.models import Provincia, Municipio, Role, User

from project_part.main import app, limiter
from project_part.db.session import get_session

DATABASE_URL_TEST = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="session", autouse=True)
def desativar_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True

@pytest.fixture
async def session_test():
    """Garante que as tabelas existem forçando a leitura dos metadados."""
    engine = create_async_engine(
        DATABASE_URL_TEST, 
        connect_args={"check_same_thread": False}
    )
    
    # FORÇA O PYTHON A MAPEAR OS METADADOS: Aceder às propriedades garante o registo em Base
    _ = [Provincia.__table__, Municipio.__table__, Role.__table__, User.__table__]

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Mantém a ligação persistente aberta para o SQLite em memória não expirar
    async with engine.connect() as connection:
        
        # Agora o metadata vai conter as tabelas 'provincias', 'municipios', etc.
        await connection.run_sync(Base.metadata.create_all)
        
        async with async_session_factory(bind=connection) as session:
            
            # --- POPULAÇÃO DA SEMENTE DE TESTE ---
            id_luanda = uuid.uuid4()
            id_viana = uuid.uuid4()
            
            provincia = Provincia(id=id_luanda, nome_provincia="Luanda")
            session.add(provincia)
            await session.flush()  

            municipio = Municipio(id=id_viana, nome_municipio="Viana", id_provincia=id_luanda)
            session.add(municipio)

            role_militante = Role(id=1, nome="MILITANTE")
            role_simpatizante = Role(id=2, nome="SIMPATIZANTE")
            session.add_all([role_militante, role_simpatizante])
            
            await session.commit()
            # -------------------------------------

            yield session

        await connection.run_sync(Base.metadata.drop_all)
        
    await engine.dispose()

@pytest.fixture
def clientTest(session_test):
    async def override_get_session():
        yield session_test

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
