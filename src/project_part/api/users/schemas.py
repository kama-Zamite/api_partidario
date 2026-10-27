import re
import uuid
import phonenumbers
from enum import Enum
from datetime import date, datetime
from typing import Annotated, Any, List, Optional
from decimal import Decimal
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
    DonationStatusEnum,
    MetodoPagamentoEnum
)

EmailValided = Annotated[EmailStr, StringConstraints(to_lower=True, strip_whitespace=True)]

class UpdateEmailRecuperacao(BaseModel):
    novo_email: EmailValided = Field(max_length=255,  strip_whitespace=True, description="Novo email para recuperação de conta")

    @field_validator('novo_email')
    @classmethod
    def validar_email(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O email não pode ser vazio")
        return v


class UserBase(BaseModel):
    nome_completo: str = Field(max_length=50, strip_whitespace=True)
    email: EmailValided = Field(max_length=255, strip_whitespace=True)
    password: str = Field(min_length=8, max_length=128, strip_whitespace=True)
    confirmar_password: str = Field(min_length=8, max_length=128, strip_whitespace=True)
    data_nascimento: date
    nif: str = Field(min_length=14, max_length=14, strip_whitespace=True)
    militante_numero: str | None = Field(default=None, max_length=20, strip_whitespace=True)
    telefone: str = Field(max_length=20, strip_whitespace=True)
    genero: Genero | None = Field(default=Genero.HOMEM)
    nome_provincia: str = Field(min_length=4, max_length=20, strip_whitespace=True)
    nome_municipio: str = Field(min_length=4, max_length=20, strip_whitespace=True)

    foi_militante: bool = Field(default=False)
    cadastrar_militante: CadastrarComo = Field(default=CadastrarComo.MILITANTE)

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)

    aceitou_termos: bool = Field(..., description="O utilizador deve aceitar as políticas de segurança.")
    # ativo: Optional[bool] = Field(default=True)

    @field_validator('aceitou_termos')
    @classmethod
    def validar_aceitacao_termos(cls, termos: bool) -> bool:
        if termos is not True:
            raise ValueError("O utilizador deve aceitar as políticas de segurança.")
        return termos

    
    @field_validator('nome_completo')
    @classmethod
    def validar_nome(cls, nome_complet: str) -> str:
        if nome_complet is None or nome_complet == "":
            raise ValueError("O nome completo não pode ser vazio")
        # Remove espaços extras no início/fim e divide em palavras
        nomes = nome_complet.split()
        
        # 1. Verifica se tem pelo menos um nome e um sobrenome
        if len(nomes) < 2:
            raise ValueError('O nome completo deve conter pelo menos um nome e um apelido/sobrenome.')
        
        # 2. Verifica se a primeira letra de CADA palavra é maiúscula
        for palavra in nomes:
            if not palavra[0].isupper():
                raise ValueError('O nome completo deve começar com letra maiúscula.')
                
        # Retorna o nome formatado apenas com um espaço simples entre as palavras
        return ' '.join(nomes)


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
    
    @model_validator(mode='after')
    def validar_nova_senha(self) -> 'UserBase':
        # No modo 'after', self já é a instância com os dados validados
        if self.password != self.confirmar_password:
            raise ValueError('As senhas são incompatíveis.')
        return self
    
    @field_validator('telefone')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
        if tel_number is None or tel_number == "":
            raise ValueError("O número de telefone não pode ser vazio")
        
        # 1. Limpa espaços e caracteres especiais
        numero_limpo = re.sub(r'[^\d+]', '', tel_number.strip())

        
        # 2. Mantém a conveniência para Angola (9 dígitos diretos)
        if len(numero_limpo) == 9 and numero_limpo.startswith(('91', '92', '93', '94', '95', '99')):
            numero_limpo = f"+244{numero_limpo}"
        
        if not numero_limpo.startswith('+'):
            numero_limpo = f"+{numero_limpo}"
            
        # angola_padrao_valido = r'^(91|92|93|94|95|99)\d{7}$'

        try:
            # 3. Parse com a biblioteca do Google
            parsed_number = phonenumbers.parse(numero_limpo, "AO")
            if not phonenumbers.is_valid_number(parsed_number):
                raise ValueError("Formato inválido")

            # 4. CAPTURA O CÓDIGO DO PAÍS (Ex: "AO", "PT", "BR", "US")
            codigo_pais = phonenumbers.region_code_for_number(parsed_number)

            # 5. [OPCIONAL] FILTRO DE RESTRIÇÃO DE PAÍSES
            paises_bloqueados = ["CN", "RU"] # Exemplo: China e Rússia bloqueados
            if codigo_pais in paises_bloqueados:
                raise ValueError(f"Envios para o país {codigo_pais} não são permitidos.")

            # paises_permitidos = ["AO", "PT"]
            # if codigo_pais not in paises_permitidos:
            #     raise ValueError("País não suportado.")

            # 6. Retorna o número formatado no padrão internacional E.164
            numero_final = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)  
            return numero_final
                    
        except Exception as e:
            # Mantém a mensagem de erro clara se for um bloqueio explícito feito acima
            erro_msg = str(e) if "permitidos" in str(e) or "suportado" in str(e) else \
                    'Número de telefone inválido. Insira um número válido com o prefixo internacional (ex: +244... ou +351...).'
            raise ValueError(erro_msg)

        
        # if not re.match(angola_padrao_valido, filtrar_numero):
        #     raise ValueError(
        #         'Número de telefone inválido. Deve ser um número de Angola válido com 9 dígitos '
        #         '(ex: 923000000) ou incluir o prefixo +244.'
        #     )
        # return f'+244{filtrar_numero}'

    @field_validator('nif')
    @classmethod
    def validar_nif(cls, val_nif: str) -> str:
        nif_limpo = val_nif.upper()

        if nif_limpo is None or nif_limpo == "":
            raise ValueError("O NIF não pode ser vazio")

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

    @field_validator('militante_numero')
    @classmethod
    def validar_militante_numero(cls, val_militante: str) -> str:
        if val_militante == "":
            raise ValueError("O número de militante não pode ser vazio")
        return val_militante

    @field_validator('nome_provincia', 'nome_municipio')
    @classmethod
    def validar_nomes_provincia_municipio(cls, val: str) -> str:
        if val is None or val == "":
            raise ValueError("O nome da província ou do município não pode ser vazio")
        return val

    

class DeleteUser(BaseModel):
    validar_campo: str = Field(min_length=8, max_length=8)
    confirmar_senha: str = Field(min_length=8, max_length=30)
    codigo_2fa: str | None = Field(default=None, pattern=r'^(\d{6}|\d{8})$')

    @field_validator("confirmar_senha")
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

    @field_validator("confirmar_senha")
    @classmethod
    def validar_confirmar_senha(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A confirmação de senha não pode ser vazia")
        return v



class Delete2FARequest(BaseModel):
    confirmar_senha: str
    codigo_2fa: str | None = Field(default=None, pattern=r'^(\d{6}|\d{8})$')

    @field_validator("confirmar_senha", "codigo_2fa")
    @classmethod
    def validar_confirmar_senha(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A confirmação de senha ou o código 2FA não pode ser vazio")
        return v


class ConfirmarEmailSchema(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    registration_ref: str = Field(
        min_length=40,
        max_length=64,
        pattern=r'^[A-Za-z0-9_-]+$',
    )
    codigo: str = Field(pattern=r'^\d{6}$')

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O código não pode ser vazio")
        return v

    @field_validator("registration_ref")
    @classmethod
    def validar_registration_ref(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A referência de registo não pode ser vazia")
        return v


class CreateUser(UserBase): ...


class UpgradePassWord(BaseModel):
    senha_atual: str = Field(min_length=8, max_length=30, strip_whitespace=True)
    nova_senha: str = Field(min_length=8, max_length=30, strip_whitespace=True)
    confirmar_nova_senha: str = Field(min_length=8, max_length=30, strip_whitespace=True)

    @field_validator("senha_atual")
    @classmethod
    def validar_senha_atual(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A senha atual não pode ser vazia")
        return v

    @field_validator("nova_senha")
    @classmethod
    def validar_complexidade(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A nova senha não pode ser vazia")
        if not re.search(r"[A-Z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("A senha deve conter pelo menos um número")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("A senha deve conter pelo menos um caractere especial")
        return v

    @field_validator("confirmar_nova_senha")
    @classmethod
    def validar_confirmar_nova_senha(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("A confirmação de senha não pode ser vazia")
        return v

    
    @model_validator(mode="after")
    def senhas_iguais(self):
        if self.nova_senha != self.confirmar_nova_senha:
            raise ValueError("A nova senha e a confirmação não são iguais.")
        return self


class UpgradeUser(BaseModel):
    nome_completo: str = Field(max_length=50, strip_whitespace=True)
    email: EmailValided = Field(max_length=255, strip_whitespace=True)
    telefone: str = Field(max_length=20, strip_whitespace=True)

    estado_civil: EstadoCivil = Field(default=EstadoCivil.SOLTEIRO)

    @field_validator('nome_completo')
    @classmethod
    def validar_nome(cls, nome_complet: str) -> str:
        if nome_complet is None or nome_complet == "":
            raise ValueError("O nome completo não pode ser vazio")
        # Remove espaços extras no início/fim e divide em palavras
        nomes = nome_complet.split()
        
        # 1. Verifica se tem pelo menos um nome e um sobrenome
        if len(nomes) < 2:
            raise ValueError('O nome completo deve conter pelo menos um nome e um apelido/sobrenome.')
        
        # 2. Verifica se a primeira letra de CADA palavra é maiúscula
        for palavra in nomes:
            if not palavra[0].isupper():
                raise ValueError('O nome completo deve começar com letra maiúscula.')
                
        # Retorna o nome formatado apenas com um espaço simples entre as palavras
        return ' '.join(nomes)


    @field_validator('telefone')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
        if tel_number is None or tel_number == "":
            raise ValueError("O número de telefone não pode ser vazio")
        numero_limpo = re.sub(r'[^\d+]', '', tel_number)
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

    # @field_validator('nome_provincia', 'nome_municipio')
    # @classmethod
    # def validar_nomes(cls, v: str) -> str:
    #     if v is None or v == "":
    #         raise ValueError("O nome da província ou município não pode ser vazio")
    #     return v

    @field_validator('email')
    @classmethod
    def validar_email(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("O email não pode ser vazio")
        return v

# class DeleteUser(BaseModel):
#     email: EmailStr = Field(max_length=255)


class AdminScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provincia_id: Optional[uuid.UUID] = None
    municipio_id: Optional[uuid.UUID] = None


class ListarUserBaseAdmin(BaseModel):
    nome_completo: str = Field(max_length=50)
    id: uuid.UUID
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
    # id: uuid.UUID
    image_url: str | None = None
    email: EmailStr = Field(max_length=255)
    email_recuperacao: EmailStr | None = Field(max_length=255)
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
    id: uuid.UUID | None = None
    numero_cartao: str | None = None
    nome_militante: str | None = None
    data_emissao: datetime | None = None 
    image_url: str | None = None
    url_qrcode: str | None = None
    activo: bool | None = None
    status: str  # Obrigatório para o front-end Next.js saber o que fazer com o botão
    municipio: str | None = None
    provincia: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator('provincia', mode='before')
    @classmethod
    def extrair_nome_provincia(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_provincia'):
            return getattr(v, 'nome_provincia')
        if isinstance(v, str) or v is None:
            return v
        raise ValueError('Província inválida')

    @field_validator('municipio', mode='before')
    @classmethod
    def extrair_nome_municipio(cls, v: Any) -> Optional[str]:
        if v and hasattr(v, 'nome_municipio'):
            return getattr(v, 'nome_municipio')
        if isinstance(v, str) or v is None:
            return v
        raise ValueError('Município inválido')


class UsuarioNotificacaoSchema(BaseModel):
    nome_completo: str
    email: str

    model_config = ConfigDict(from_attributes=True)

# 2. Define a estrutura da Notificação enviada para o Frontend
class NotificationResponse(BaseModel):
    id: uuid.UUID
    titulo: str
    mensagem: str
    motivo: str | None
    destinatario: str | None
    criado_as: datetime
    lido_as: datetime | None
    
    # Aqui acontece a magia: injetamos o schema do utilizador dentro da resposta
    solicitante: UsuarioNotificacaoSchema | None 

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    total: int
    results: list[NotificationResponse]



class DoacaoResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    quantia: Decimal
    moeda: str
    metodo_pagamento: MetodoPagamentoEnum
    id_transacao: str | None
    meses_pagar: int
    status: DonationStatusEnum
    observacao: str | None
    data_doacao: datetime
    descricao: str | None
    aprovado_em: datetime | None

    model_config = ConfigDict(from_attributes=True)



class DoacaoList(BaseModel):
    total: int
    results: list[DoacaoResponse]




class ReativarUserResponse(BaseModel):
    msg: str
    user_id: uuid.UUID
    email: str
    ativo: bool



class TipoContribuicao(str, Enum):
    QUOTA = 'QUOTA'
    DOACAO = 'DOACAO'


class ContribuicaoItem(BaseModel):
    id: uuid.UUID
    tipo: TipoContribuicao
    data: datetime
    referencia: str | None
    valor: Decimal
    estado: str
    status: str
    periodo: str | None = None
    metodo_pagamento: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ContribuicoesIndividuoResponse(BaseModel):
    user_id: uuid.UUID
    nome: str
    total_pago: Decimal
    ano: int | None
    total: int
    limit: int
    offset: int
    results: list[ContribuicaoItem]



class UltimoPagamentoQuotaResponse(BaseModel):
    ultimo_pagamento: Optional[date] = None
    proximo_pagamento: Optional[date] = None
    dias_restantes: int = 0



