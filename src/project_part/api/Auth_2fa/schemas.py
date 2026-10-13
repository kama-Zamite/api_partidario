import re

from pydantic import BaseModel, Field, field_validator

class Code2FA(BaseModel):
    codigo: str = Field(min_length=6, max_length=6)

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O código não pode ser vazio")
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("O código deve ter 6 dígitos")
        return v
