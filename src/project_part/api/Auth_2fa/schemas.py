from pydantic import BaseModel, Field

class Code2FA(BaseModel):
    codigo: str = Field(min_length=6, max_length=6)