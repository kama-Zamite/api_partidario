from pydantic import BaseModel

# Schema Pydantic para validar a alteração vinda do Frontend
class PartilharDados(BaseModel):
    partilha_dados: bool | None = None

class CookiesPersonalizacao(BaseModel):
    cookies_personalizacao: bool | None = None