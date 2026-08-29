import logging.config
import os


def setup_logging():
    log_dir = 'logs'
    # Cria a pasta de logs na raiz do projeto se ela não existir
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
        },
        'handlers': {
            # Mantém os logs aparecendo no terminal do Docker
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'stream': 'ext://sys.stdout',
            },
            # Salva os logs em arquivo físico com rotação automática
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'default',
                'filename': os.path.join(log_dir, 'api_production.log'),
                'maxBytes': 10485760,  # 10MB por arquivo
                'backupCount': 5,  # Mantém no máximo 5 arquivos antigos de histórico
                'encoding': 'utf-8',
            },
        },
        'loggers': {
            # Captura os logs do seu middleware e segurança
            'project_part': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
            # Captura os logs do FastAPI/Uvicorn
            'uvicorn': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
        },
    }
    logging.config.dictConfig(logging_config)
