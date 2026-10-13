from pydantic import BaseModel, Field, ConfigDict, field_validator
from project_part.model.models import CategoriaMensagemSuporte
from enum import Enum
import uuid



class MensagemSuporteCreate(BaseModel):
    categoria: CategoriaMensagemSuporte = Field(
        ...,
        examples=[CategoriaMensagemSuporte.PROBLEMA_DE_CONTA],
    )
    assunto: str = Field(
        ...,
        min_length=5,
        max_length=200,
        examples=["Não consigo entrar na minha conta"],
        strip_whitespace=True,
    )
    mensagem: str = Field(
        ...,
        min_length=10,
        max_length=3000,
        examples=["Descreva o seu problema ou pedido com o máximo de detalhe possível..."],
        strip_whitespace=True,
    )

    @field_validator('assunto', 'mensagem')
    @classmethod
    def validar_campos(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O campo não pode ser vazio")
        return v
    
    # Opcional: se o utilizador estiver autenticado
    # email: Optional[EmailStr] = None
    # nome: Optional[str] = None


class MensagemSuporteResponse(BaseModel):
    mensagem: str = "Mensagem enviada com sucesso. A nossa equipa responderá em breve."
    model_config = ConfigDict(from_attributes=True)

