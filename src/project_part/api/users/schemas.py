import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from project_part.model.models import (
    CadastrarComo,
    EstadoCivil,
    Genero,
)

EmailValided = Annotated[EmailStr, StringConstraints(to_lower=True, strip_whitespace=True)]

class UserBase(BaseModel):
    nome_completo: str = Field(max_length=50)
    email: EmailValided = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    confirmar_password: str = Field(min_length=8, max_length=128)
    data_nascimento: date
    nif: str = Field(min_length=14, max_length=14)
    militante_numero: Optional[str]
    telefone: str = Field(max_length=20)
    genero: Genero | None = Field(default=Genero.HOMEM)
    nome_provincia: str
    nome_municipio: str

    foi_militante: bool = Field(default=False)
    cadastrar_militante: CadastrarComo = Field(default=CadastrarComo.MILITANTE)

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)
    # ativo: Optional[bool] = Field(default=True)

    @field_validator('nome_completo')
    @classmethod
    def validar_nome(cls, nome_complet: str) -> str:
        nomes = nome_complet.strip().split()
        if len(nomes) < 2:
            raise ValueError('O nome completo deve conter pelo menos um nome e um apelido/sobrenome.')
        return ' '.join(nomes)

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
    
    @model_validator(mode='after')
    def validar_nova_senha(self) -> 'UserBase':
        # No modo 'after', self já é a instância com os dados validados
        if self.password != self.confirmar_password:
            raise ValueError('As senhas são incompatíveis.')
        return self
    
    @field_validator('telefone')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
        numero_limpo = re.sub(r'[^\d+]', '', tel_number.strip())
        if numero_limpo.startswith('+244'):
            filtrar_numero = numero_limpo[4:]
        elif numero_limpo.startswith('244'):
            filtrar_numero = numero_limpo[3:]
        else:
            filtrar_numero = numero_limpo

        angola_padrao_valido = r'^(91|92|93|94|95|99)\d{7}$'

        if not re.match(angola_padrao_valido, filtrar_numero):
            raise ValueError(
                'Número de telefone inválido. Deve ser um número de Angola válido com 9 dígitos '
                '(ex: 923000000) ou incluir o prefixo +244.'
            )
        return f'+244{filtrar_numero}'

    @field_validator('nif')
    @classmethod
    def validar_nif(cls, val_nif: str) -> str:
        nif_limpo = val_nif.strip().upper()

        padrao_nif = r'^(\d{9}[A-Z]{2}\d{3}|\d{9}[A-Z]\d{3}[A-Z])$'
        if not re.match(padrao_nif, nif_limpo):
            raise ValueError('NIF inválido! Certifique-se de introduzir um NIF de Angola válido com 14 caracteres')
        return nif_limpo

    @field_validator('data_nascimento')
    @classmethod
    def validar_maioridade(cls, date_nasc: date) -> date:
        hoje = date.today()

        idade = hoje.year - date_nasc.year - ((hoje.month, hoje.day) < (date_nasc.month, date_nasc.day))

        if idade < 18:
            raise ValueError('O usuário deve ser maior de 18 anos.')

        return date_nasc


class DeleteUser(BaseModel):
    valid: str = Field(min_length=8, max_length=9)

class ConfirmarEmailSchema(BaseModel):
    email: EmailStr
    codigo: int


class CreateUser(UserBase): ...


class UpgradePassWord(BaseModel):
    senha_atual: str = Field(min_length=8, max_length=30)
    nova_senha: str = Field(min_length=8, max_length=30)
    confirmar_nova_senha: str = Field(min_length=8, max_length=30)

    @model_validator(mode='after')
    def validar_nova_senha(self):
        if self.nova_senha != self.confirmar_nova_senha:
            raise ValueError('A nova senha e a confirmação não são iguais.')
        return self


class UpgradeUser(BaseModel):
    nome_completo: str = Field(max_length=50)
    email: EmailValided = Field(max_length=255)
    telefone: str = Field(max_length=20)
    nome_provincia: str
    nome_municipio: str

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)

    @field_validator('nome_completo')
    @classmethod
    def validar_nome(cls, nome_complet: str) -> str:
        nomes = nome_complet.strip().split()
        if len(nomes) < 2:
            raise ValueError('O nome completo deve conter pelo menos um nome e um apelido/sobrenome.')
        return ' '.join(nomes)

    @field_validator('telefone')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
        numero_limpo = re.sub(r'[^\d+]', '', tel_number.strip())
        if numero_limpo.startswith('+244'):
            filtrar_numero = numero_limpo[4:]
        elif numero_limpo.startswith('244'):
            filtrar_numero = numero_limpo[3:]
        else:
            filtrar_numero = numero_limpo

        angola_padrao_valido = r'^(91|92|93|94|95|99)\d{7}$'

        if not re.match(angola_padrao_valido, filtrar_numero):
            raise ValueError(
                'Número de telefone inválido. Deve ser um número de Angola válido com 9 dígitos '
                '(ex: 923000000) ou incluir o prefixo +244.'
            )
        return f'+244{filtrar_numero}'


# class DeleteUser(BaseModel):
#     email: EmailStr = Field(max_length=255)


class AdminScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provincia_id: Optional[uuid.UUID] = None
    municipio_id: Optional[uuid.UUID] = None


class ListarUserBaseAdmin(BaseModel):
    nome_completo: str = Field(max_length=50)
    # id: uuid.UUID
    image_url: str | None = None
    email: EmailStr = Field(max_length=255)
    data_nascimento: date
    nif: str = Field(max_length=30)
    militante_numero: str | None
    telefone: str = Field(max_length=20)
    genero: Genero = Field(default=Genero.HOMEM)
    criado_em: datetime
    deletado_em: datetime | None
    foi_militante: bool
    cadastrar_militante: str

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)
    ativo: bool | None = Field(default=True)

    provincia: str
    municipio: str
    role: str

    model_config = ConfigDict(from_attributes=True, ser_json_circular_logic='ignore')

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')

    @field_validator('role', mode='before')
    @classmethod
    def extrair_nome_role(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome'):
            return getattr(v, 'nome')
        if isinstance(v, str):
            return v
        raise ValueError('Função inválida ou ausente')


class ListarUserBase(BaseModel):
    nome_completo: str = Field(max_length=50)
    id: uuid.UUID
    image_url: str | None = None
    email: EmailStr = Field(max_length=255)
    data_nascimento: date
    criado_em: datetime
    nif: str = Field(max_length=30)
    militante_numero: str | None
    telefone: str = Field(max_length=20)
    genero: Genero = Field(default=Genero.HOMEM)
    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)
    ativo: bool | None = Field(default=True)


    provincia: str
    municipio: str
    role: str
    # scope: list[AdminScopeResponse]

    model_config = ConfigDict(from_attributes=True, ser_json_circular_logic='ignore')

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')

    @field_validator('role', mode='before')
    @classmethod
    def extrair_nome_role(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome'):
            return getattr(v, 'nome')
        if isinstance(v, str):
            return v
        raise ValueError('Função inválida ou ausente')


class LimitUser(BaseModel):
    limit: int = Field(ge=10, default=10, le=100)
    skip: int = Field(ge=0, default=0)


class ListarUser(BaseModel):
    total_user: int
    total_homens: int
    total_mulheres: int
    usuarios: List[ListarUserBaseAdmin]

    model_config = ConfigDict(from_attributes=True)


class CardBase(BaseModel):
    id: uuid.UUID
    numero_cartao: str
    nome_militante: str
    data_emissao: datetime
    ativo: bool

    model_config = ConfigDict(from_attributes=True)

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)
    municipio: str
    provincia: str

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')

        if isinstance(v, str):
            return v
        raise ValueError('Província inválida ou ausente')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str):
            return v
        raise ValueError('Município inválido ou ausente')


class UsuarioNotificacaoSchema(BaseModel):
    nome_completo: str
    email: str

    model_config = ConfigDict(from_attributes=True)

# 2. Define a estrutura da Notificação enviada para o Frontend
class NotificationResponse(BaseModel):
    id: uuid.UUID
    titulo: str
    mensagem: str
    destinatario: str | None
    criado_as: datetime
    lido_as: datetime | None
    
    # Aqui acontece a magia: injetamos o schema do utilizador dentro da resposta
    solicitante: UsuarioNotificacaoSchema | None 

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    total: int
    results: list[NotificationResponse]





