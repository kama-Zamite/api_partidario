import asyncio
import os



# Semaphore to limit the number of concurrent hash operations
_CORES_DISPONIVEIS = os.cpu_count() or 0

# Limit of concurrent hash operations
_LIMIT_COMCORRENCIA = max(1, _CORES_DISPONIVEIS - 1)

# Semaphore to limit the number of concurrent hash operations
HASH_SEM = asyncio.Semaphore(_LIMIT_COMCORRENCIA)   # no topo do módulo de login
