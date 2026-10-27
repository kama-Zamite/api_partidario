from datetime import datetime, date 
from pydantic import BaseModel, ConfigDict, Field, EmailStr
from uuid import UUID
from project_part.model.models import EstadoCivil, Genero, CadastrarComo
from typing import Optional


class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    ativo: bool
    bloqueado_permanente: bool | None = False
    scopes: list[str] = []