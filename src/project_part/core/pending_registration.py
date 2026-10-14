import hashlib
import hmac
import json
import os
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

TTL_S = 5 * 60
MAX_TENTATIVAS = 5
MAX_FOTO_BYTES = 5 * 1024 * 1024  # alinhado com settings.FILE_SIZE_LIMIT


@lru_cache
def _fernet() -> MultiFernet:
    chaves = [k.strip() for k in os.environ['REGISTRATION_ENC_KEYS'].split(',') if k.strip()]
    return MultiFernet([Fernet(k) for k in chaves])  # falha cedo se faltar/for inválida


@lru_cache
def _hmac_key() -> bytes:
    return os.environ['REGISTRATION_HMAC_KEY'].encode()


def _h(ref: str) -> str:
    # No Redis nunca fica a referência em si, só o seu hash
    return hashlib.sha256(ref.encode()).hexdigest()


def _keys(ref: str) -> tuple[str, str, str]:
    h = _h(ref)
    return f'reg:{h}:data', f'reg:{h}:foto', f'reg:{h}:tries'


def _mac_codigo(ref: str, codigo: str) -> str:
    return hmac.new(_hmac_key(), f'{ref}:{codigo}'.encode(), hashlib.sha256).hexdigest()


async def guardar(r, dados: dict, foto: bytes | None, codigo: str) -> str:
    """Devolve a referência opaca. `dados` NÃO pode conter a senha em claro."""
    if 'password' in dados:
        raise ValueError('Senha em claro não pode ir para o Redis')
    if foto is not None and len(foto) > MAX_FOTO_BYTES:
        raise ValueError('Foto demasiado grande')

    ref = secrets.token_urlsafe(32)
    data_key, foto_key, _ = _keys(ref)
    f = _fernet()

    payload = {'ref': ref, 'dados': dados, 'code_mac': _mac_codigo(ref, codigo)}
    blob = f.encrypt(json.dumps(payload).encode())

    pipe = r.pipeline(transaction=True)
    pipe.setex(data_key, TTL_S, blob)
    if foto:
        pipe.setex(foto_key, TTL_S, f.encrypt(foto))
    await pipe.execute()
    return ref


async def consumir(r, ref: str, codigo: str) -> tuple[dict, bytes | None] | None:
    """Valida o código e devolve (dados, foto) UMA só vez. None se inválido/expirado."""
    data_key, foto_key, tries_key = _keys(ref)

    tentativas = await r.incr(tries_key)
    if tentativas == 1:
        await r.expire(tries_key, TTL_S)
    if tentativas > MAX_TENTATIVAS:
        await r.delete(data_key, foto_key)
        return None

    blob = await r.get(data_key)
    if not blob:
        return None

    f = _fernet()
    try:
        payload = json.loads(f.decrypt(blob, ttl=TTL_S + 60))
    except (InvalidToken, ValueError):
        return None

    if not (
        hmac.compare_digest(payload['ref'], ref)
        and hmac.compare_digest(payload['code_mac'], _mac_codigo(ref, codigo))
    ):
        return None

    foto_blob = await r.get(foto_key)

    # Só a data_key decide quem "ganha": delete devolve 1 apenas para um pedido
    if await r.delete(data_key) == 0:
        return None
    await r.delete(foto_key, tries_key)

    foto = f.decrypt(foto_blob) if foto_blob else None
    return payload['dados'], foto


async def descartar(r, ref: str) -> None:
    """Apaga um registo pendente (ex.: falhou o envio do e-mail)."""
    await r.delete(*_keys(ref))