from datetime import datetime, timezone
from hashlib import sha256
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_part.db.session import get_session
from project_part.core.setting import settings
from project_part.core.secury import create_token


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:

    common = {
        "httponly": True,
        "secure": settings.SECURE_COOKIES,
        "samesite": settings.SAMESITE_COOKIE,
        "path": "/",
    }

    response.set_cookie(
        # key="__Host-access_token", producao
        key="access_token",
        value=access_token,
        max_age=settings.TIME_TOKEN_EXPIRE,
        **common,
    )

    response.set_cookie(
        # key="__Host-refresh_token", producao
        key="refresh_token",
        value=refresh_token,
        max_age=settings.TIME_REFRESH_TOKEN,
        **common,
    )