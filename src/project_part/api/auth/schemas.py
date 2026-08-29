from typing import Annotated, List
import uuid
import re
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
    field_validator
)

# from sqlalchemy import

EmailValided = Annotated[EmailStr, StringConstraints(to_lower=True, strip_whitespace=True)]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str

class Login2FARequest(BaseModel):
    user_id: uuid.UUID
    codigo: str = Field(min_length=6, max_length=8)

class PermissaoBase(BaseModel):
    nome: str = Field(min_length=3, max_length=100)


class CreatePermissao(PermissaoBase): ...


class UpgradePermissao(PermissaoBase): ...


class ResponsePermissao(PermissaoBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    nome: str = Field(max_length=50)


class CreateRole(RoleBase):
    permissoes_nome: List[str] = Field(default=[])


class UpgradeRole(RoleBase): ...


class Code2FA(BaseModel):
    codigo: str = Field(min_length=6, max_length=6)

class Limit(BaseModel):
    limit: int = Field(ge=0, le=100, default=10)
    skip: int = Field(ge=0, default=0)


class ResponseRole(RoleBase):
    id: int
    permissoes: List[PermissaoBase] = []

    model_config = ConfigDict(from_attributes=True)


class PedidoRecuperacao(BaseModel):
    email: EmailStr

class RedefinirSenhaSchema(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=128)
    confirmar_password: str

    @field_validator("password")
    @classmethod
    def validar_complexidade(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("A senha deve conter pelo menos um número")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("A senha deve conter pelo menos um caractere especial")
        return v

    @model_validator(mode="after")
    def senhas_iguais(self):
        if self.password != self.confirmar_password:
            raise ValueError("As senhas não coincidem")
        return self


