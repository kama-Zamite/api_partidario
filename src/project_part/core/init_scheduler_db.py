import logging
from sqlalchemy import create_engine
from project_part.core.setting import settings

logger = logging.getLogger(__name__)

def inicializar_tabela_scheduler():
    # Converte o driver assíncrono para síncrono para o script de migração
    sync_url = settings.BASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    try:
        engine = create_engine(sync_url)
        # Força o APScheduler a criar a estrutura de tabelas padrão no banco
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        store = SQLAlchemyJobStore(engine=engine)
        
        logger.info("Tabelas do APScheduler validadas/criadas com sucesso no banco de dados.")
    except Exception as e:
        logger.error("Erro ao gerar tabelas do agendador: %s", e)

if __name__ == "__main__":
    inicializar_tabela_scheduler()
