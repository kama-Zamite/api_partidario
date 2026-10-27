from pydantic import BaseModel
from uuid import UUID
from typing import List

class UsuarioAutenticado(BaseModel):
    id: UUID
    email: str
    ativo: bool
    bloqueado_permanente: bool
    # password_hash: str
    scopes: List[str] = []

    class Config:
        from_attributes = True
