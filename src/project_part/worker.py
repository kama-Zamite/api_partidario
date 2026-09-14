#producao


# # src/project_part/worker.py
# import asyncio
# import logging
# import signal
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from apscheduler.triggers.cron import CronTrigger
# from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

# from project_part.core.logging_config import setup_logging
# from project_part.core.setting import settings
# from project_part.core.jobs import verificar_e_notificar_quotas_vencidas

# setup_logging()
# logger = logging.getLogger('apscheduler')

# sync_db_url = settings.BASE_URL.replace("postgresql+asyncpg://", "postgresql://")
# jobstores = {'default': SQLAlchemyJobStore(url=sync_db_url)}

# scheduler = AsyncIOScheduler(jobstores=jobstores)

# async def main():
#     logger.info("Iniciando processo isolado do APScheduler Worker...")
    
#     # Garante a tabela no banco
#     try:
#         default_store = scheduler._jobstores.get('default')
#         if default_store and hasattr(default_store, 'engine'):
#             default_store.jobs_t.create(default_store.engine, checkfirst=True)
#     except Exception as e:
#         logger.warning("Tabela já existente ou erro DDL: %s", e)

#     # Agenda o Job no processo único
#     scheduler.add_job(
#         verificar_e_notificar_quotas_vencidas,
#         trigger=CronTrigger(day=15, hour=2, minute=0),
#         id='job_verificar_quotas',
#         replace_existing=True,
#         max_instances=1,  
#         coalesce=True,    
#         misfire_grace_time=3600  
#     )

#     scheduler.start()
#     logger.info("APScheduler Worker ativo e monitorizando tarefas.")

#     # Mantém o processo vivo escutando sinais de encerramento do Docker
#     stop_event = asyncio.Event()
    
#     def stop():
#         logger.info("Encerrando Worker...")
#         scheduler.shutdown(wait=False)
#         stop_event.set()

#     loop = asyncio.get_running_loop()
#     for sig in (signal.SIGINT, signal.SIGTERM):
#         loop.add_signal_handler(sig, stop)

#     await stop_event.wait()

# if __name__ == "__main__":
#     asyncio.run(main())
