from pydantic import BaseModel, Field, EmailStr, ConfigDict
from project_part.model.models import CategoriaMensagemSuporte
from typing import Optional
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
    )
    mensagem: str = Field(
        ...,
        min_length=10,
        max_length=3000,
        examples=["Descreva o seu problema ou pedido com o máximo de detalhe possível..."],
    )
    # Opcional: se o utilizador estiver autenticado
    # email: Optional[EmailStr] = None
    # nome: Optional[str] = None


class MensagemSuporteResponse(BaseModel):
    id: uuid.UUID
    mensagem: str = "Mensagem enviada com sucesso. A nossa equipa responderá em breve."
    user_id: Optional[uuid.UUID] = None
    model_config = ConfigDict(from_attributes=True)

