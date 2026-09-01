import asyncio
import sys
import os

from logging.config import fileConfig

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from src.project_part.db.base import Base
from src.project_part.core.setting import settings
from src.project_part.model.models import (
    User,
    Provincia,
    Municipio,
    Role,
    Permissao,
    AdminScope,
    Noticia,
    NoticiaCategoria,
    AuditLog,
    CartaoMilitante,
    Genero,
    EstadoCivil,
    MensagemSuporte,
    CadastrarComo,
    SolicitacaoMilitancia,
    StatusSolicitacaoMilitancia,
    UserRefreshToken,
    RoleCategoriaNotificacao,
    Notification,
    CategoriaMensagemSuporte,
    RoleMensagemSuporte,
    )
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option('sqlalchemy.url', settings.BASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection, target_metadata=target_metadata
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    
    await connectable.dispose()

def run_migrations_online():
    if sys.platform == 'win32':
        asyncio.run(run_async_migrations(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
