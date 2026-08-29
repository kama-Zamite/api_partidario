import contextvars
from typing import Optional

client_ip_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('client_ip', default=None)
user_agent_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('user_agent', default=None)
current_user_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('current_user_id', default=None)
