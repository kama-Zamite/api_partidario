from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
)
import pyotp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import select
from sqlalchemy.exc import IntegrityError
from project_part.db.session import get_session
from project_part.model.models import User
from project_part.core.setting import settings
from project_part.core.secury import (
    Get_current_user
)   
import logging

logger = logging.getLogger(__name__)

security_router = APIRouter(prefix="/security", tags=["Security-Password"])
