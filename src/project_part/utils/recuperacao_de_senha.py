from datetime import datetime, timezone
import math

def como_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def segundos_de_bloqueio_restantes(user, agora: datetime) -> int:
    """0 se a conta não está temporariamente bloqueada."""
    bloqueado_ate = como_utc(user.bloqueado_ate)
    if bloqueado_ate and agora < bloqueado_ate:
        return math.ceil((bloqueado_ate - agora).total_seconds())
    return 0