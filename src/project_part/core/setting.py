from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='allow',
        case_sensitive=True,
    )
    BASE_URL: str
    DUMMY_HASH: str
    EXPIRE_TOKEN: int
    REFRESH_TOKEN: int

    # Configurações de autenticação e segurança
    ALGORITHM: str
    SECRET_KEY: str
    TIME_REFRESH_TOKEN: int
    REFRESH_REUSE_GRACE_SECONDS: int
    TIME_TOKEN_EXPIRE: int

    #   Configurações de recuperação de senha
    SECRET_KEY_RECUPERAR_SENHA: str
    EXPIRE_TOKEN_RECUPERAR_SENHA: int
    MARGEM_TOKEN_MIN: int

    # Configurações de Cloudflare Turnstile
    CLOUDFLARE_TURNSTILE_SECRET: str
    CLOUDFLARE_VALIDATE_URL :  str
    ENV: str



    # Configurações de banco de dados
    DATABASE_REDIS_URL: str
    REDIS_QUEUE_URL: str = 'redis://localhost:6379/0'
    TASKIQ_ENABLED: bool = False

    # Regras de bloqueio de conta no processo de login
    MAX_TENTATIVAS : int = 1440          # erros de senha antes de cada bloqueio
    BLOQUEIO_BASE_MIN : int     # 1.º bloqueio: 5 min, depois 10, 15, 20, 25 30, 35, 40...
    BLOQUEIO_MAX_MIN : int  # teto: 24 horas
    MSG_CREDENCIAIS: str
    DETAIL_CHALLENGE_INVALIDA: str

    # armazena o tamanho das fotos
    FILE_SIZE_LIMIT: int
   
   
   
    # Configurações de roles
    ADMIN_ROLE_ID: int
    ROLE_MILITANTE_ID: int
    ROLE_SIMPATIZANTE_ID: int

    # Configurações de Cloudinary para upload de imagens
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    URL_LOGO_UNCLOCK: str
    URL_LOGO_WELLCOME: str
    CLAUDINARY_URL_QUOTA_PAGAMENTO: str
    URL_ADMINISTRATIVO: str
    CLAUDINARY_URL_CONFIRMACAO: str
    URL_LOGIN: str

    # SMTP_HOST: str
    # SMTP_PORT: int
    # SMTP_USER: str
    # SMTP_PASSWORD: str
    # SMTP_FROM: str

    EMAIL_FROM: str
    RESEND_API_KEY: str



    # Configurações de CORS e segurança
    ALLOWED_ORIGINS: list[str]
    ALLOWED_HOSTS: list[str]

    # Chave de encriptação para os segredos TOTP
    TOTP_ENCRYPTION_KEY: str

    # Limite máximo de tamanho de conteúdo (10 MB)
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024

    # Exemplo: ".meusite.com" (o ponto no início permite o domínio e todos os subdomínios)
    # Em desenvolvimento local (localhost), deixe como None ou "localhost"
    # COOKIE_DOMAIN: str = ".meusite.com" if ENV == "production" else None


    # Versão da política de proteção de dados
    VERSAO_POLITICA_APD: str

    @computed_field
    def SECURE_COOKIES(self) -> bool:
        """Retorna True apenas se o ambiente for produção."""
        return self.ENV == "production"

    @computed_field
    def SAMESITE_COOKIE(self) -> str:
        """Sempre 'lax': front e back agora compartilham o mesmo site."""
        return "lax"
    
    @computed_field
    def COOKIE_DOMAIN(self) -> str | None:
        """Domínio raiz em produção (com ponto), None em local."""
        return ".militantes.dev" if self.ENV == "production" else None



    @field_validator('ALLOWED_ORIGINS', 'ALLOWED_HOSTS', mode='before')
    @classmethod
    def assemble_cors_origins(cls, valor: str | list[str]) -> list[str]:
        if isinstance(valor, str) and not valor.startswith('['):
            return [i.strip() for i in valor.split(',')]
        elif isinstance(valor, (list, str)):
            return valor
        raise ValueError(valor)

    @property
    def LOG_LEVEL(self) -> str:
        return 'DEBUG' if self.ENV == 'dev' else 'INFO'


settings = Settings()


# 'Retorna 'lax' para produção e desenvolvimento.
# 'lax' protege contra CSRF mesmo entre subdomínios (front.meusite.com -> back.meusite.com).'