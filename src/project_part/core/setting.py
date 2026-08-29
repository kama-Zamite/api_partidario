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
    DATABASE_REDIS_URL: str
    DUMMY_HASH: str
    EXPIRE_TOKEN: int
    REFRESH_TOKEN: int
    ALGORITHM: str
    SECRET_KEY: str
    TIME_REFRESH_TOKEN: int
    TIME_TOKEN_EXPIRE: int
    SECRET_KEY_RECUPERAR_SENHA: str
    EXPIRE_TOKEN_RECUPERAR_SENHA: int
    CLOUDFLARE_TURNSTILE_SECRET: str
    CLOUDFLARE_VALIDATE_URL :  str
    ENV: str

    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_FROM: str

    EMAIL_FROM: str
    RESEND_API_KEY: str


    ALLOWED_ORIGINS: list[str]
    ALLOWED_HOSTS: list[str]


    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024

    @computed_field
    def SECURE_COOKIES(self) -> bool:
        """Retorna True apenas se o ambiente for produção."""
        return self.ENV == "production"

    @computed_field
    def SAMESITE_COOKIE(self) -> str:
        """Retorna 'none' para produção (exige HTTPS) ou 'lax' para local."""
        return "none" if self.SECURE_COOKIES else "lax"
    
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
