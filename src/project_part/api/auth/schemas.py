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

# class Login2FARequest(BaseModel):
#     user_id: uuid.UUID
#     codigo: str = Field(min_length=6, max_length=8)

class Login2FARequest(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=128, strip_whitespace=True)  # [FIX-2FA] substitui user_id
    codigo: str = Field(min_length=6, max_length=8, strip_whitespace=True)

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O código não pode ser vazio")
        
        if not re.fullmatch(r"\d{6}|\d{8}", v):
            raise ValueError("O código deve ter 6 ou 8 dígitos")
        return v

    @field_validator("challenge_token")
    @classmethod
    def validar_challenge_token(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O challenge_token não pode ser vazio")
        if not re.fullmatch(r"[A-Za-z0-9_\-]{20,128}", v):
            raise ValueError("O challenge_token deve ter entre 20 e 128 caracteres alfanuméricos, incluindo '_' e '-'")
        return v



 
class PermissaoBase(BaseModel):
    nome: str = Field(min_length=3, max_length=100, strip_whitespace=True)

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O nome não pode ser vazio")
        return v


class CreatePermissao(PermissaoBase): ...


class UpgradePermissao(PermissaoBase): ...


class ResponsePermissao(PermissaoBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    nome: str = Field(max_length=50, strip_whitespace=True)

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O nome não pode ser vazio")
        return v


class CreateRole(RoleBase):
    permissoes_nome: List[str] = Field(default=[])

    

class UpgradeRole(RoleBase): ...


class Code2FA(BaseModel):
    codigo: str = Field(min_length=6, max_length=6,
                         strip_whitespace=True)
    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O código não pode ser vazio")
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("O código deve ter 6 dígitos")
        return v
    

class Limit(BaseModel):
    limit: int = Field(ge=0, le=100, default=10)
    skip: int = Field(ge=0, default=0)


class ResponseRole(RoleBase):
    id: int
    permissoes: List[PermissaoBase] = []

    model_config = ConfigDict(from_attributes=True)


class PedidoRecuperacao(BaseModel):
    email: EmailValided = Field(max_length=255)

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O email não pode ser vazio")
        return v
    
class RedefinirSenhaSchema(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=128, strip_whitespace=True)
    confirmar_password: str = Field(..., min_length=8, max_length=128, strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def validar_complexidade(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A senha não pode ser vazia")
        if not re.search(r"[A-Z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("A senha deve conter pelo menos um número")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("A senha deve conter pelo menos um caractere especial")
        return v

    @field_validator("confirmar_password")
    @classmethod
    def validar_confirmar_password(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A confirmação de senha não pode ser vazia")
        return v

    @model_validator(mode="after")
    def senhas_iguais(self):
        if self.password != self.confirmar_password:
            raise ValueError("As senhas não coincidem")
        return self


