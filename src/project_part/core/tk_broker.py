"""project_part/core/tk_broker.py: broker central do Taskiq.

RedisStreamBroker (e não ListQueueBroker): as mensagens só são confirmadas (ack) depois
de a tarefa correr, por isso uma tarefa não se perde se o worker cair a meio.
Não há result backend de propósito: os argumentos (incluindo o token de recuperação)
não devem ficar guardados no Redis depois de a tarefa terminar.
"""

from taskiq import SimpleRetryMiddleware
from taskiq_redis import RedisStreamBroker

from project_part.core.setting import settings

broker = RedisStreamBroker(
    url=settings.REDIS_QUEUE_URL,   # ex.: redis://:SENHA@redis_queue:6379/0
    maxlen=100000,           # Trunca o Stream em aproximadamente 100k mensagens para evitar estouro de memória
    approximate=True,
    queue_name='unita:tasks',
).with_middlewares(
    # Só repete tarefas marcadas com retry_on_error=True.
    SimpleRetryMiddleware(default_retry_count=3),
)