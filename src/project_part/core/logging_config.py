import logging.config
import os


import logging
import logging.config
import os


def setup_logging():
    # Por defeito: só stdout (o Docker/Render recolhem). Ficheiro só se LOG_FILE estiver definido.
    log_file = os.getenv('LOG_FILE')

    handlers = {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout',
        },
    }
    active_handlers = ['console']

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers['file'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'default',
            'filename': log_file,
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'encoding': 'utf-8',
        }
        active_handlers.append('file')

    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
        },
        'handlers': handlers,
        'loggers': {
            'project_part': {
                'handlers': active_handlers,
                'level': 'INFO',
                'propagate': False,
            },
            'uvicorn': {
                'handlers': active_handlers,
                'level': 'INFO',
                'propagate': False,
            },
        },
    }
    logging.config.dictConfig(logging_config)


