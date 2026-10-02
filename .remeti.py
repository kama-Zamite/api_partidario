Para fazer essa verificação de forma robusta e profissional, você precisa de atuar em duas frentes: no esquema de validação de dados (Pydantic) para rejeitar a requisição imediatamente se o utilizador não aceitar, e na base de dados, para registar o consentimento (com data e versão dos termos).
Aqui está o passo a passo de como implementar isto no seu projeto FastAPI:
1. Atualizar o Schema do Pydantic (schemas/user.py)
Utilize um campo booleano (True/False) e adicione uma validação com model_validator ou field_validator. Se o utilizador enviar false, a API devolve um erro automático de validação (Status 422).
python
from pydantic import BaseModel, Field, field_validator

class UserRegisterSchema(BaseModel):
    email: str
    password: str
    # Campo obrigatório no Payload: ex: {"aceitou_termos": true}
    aceitou_termos: bool = Field(..., description="O utilizador deve aceitar as políticas de segurança.")

    @field_validator('aceitou_termos')
    @classmethod
    def validar_aceite_termos(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("Deve aceitar as políticas de segurança e privacidade para se registar.")
        return v
Use o código com cuidado.
2. Atualizar o Modelo da Base de Dados (models/user.py)
Não basta apenas verificar no momento do registo; para fins jurídicos e de auditoria (como conformidade com a LGPD ou RGPD), é crucial guardar quando e qual versão das políticas o utilizador aceitou.
Adicione estes campos ao seu modelo SQLAlchemy (ou equivalente):
python
from sqlalchemy import Column, Boolean, DateTime, String
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    
    # ... outros campos (id, email, password_hash) ...
    
    aceitou_termos = Column(Boolean, default=False, nullable=False)
    termos_aceitos_em = Column(DateTime, nullable=True)
    versao_termos_aceitos = Column(String, nullable=True) # Ex: "v1.0" ou "2026-10"
Use o código com cuidado.
3. Implementar no Router de Registo (auth_router.py)
No seu endpoint de cadastro, basta passar esses dados para o modelo antes de guardar na base de dados. Lembre-se de usar o utilitário de hash seguro que criámos no passo anterior!
python
from datetime import datetime
from project_part.utils.security import safe_get_password_hash

@router.post("/register", status_code=21)
async def register_user(payload: UserRegisterSchema, db: Session = Depends(get_db)):
    # 1. (Opcional) Verificar se o e-mail já existe
    # ...
    
    # 2. Gerar o hash da senha usando o Semaphore global do seu utils
    hash_senha = await safe_get_password_hash(payload.password)
    
    # 3. Criar o utilizador guardando o histórico do consentimento
    novo_usuario = User(
        email=payload.email,
        password_hash=hash_senha,
        aceitou_termos=payload.aceitou_termos,       # Será sempre True devido ao Pydantic
        termos_aceitos_em=datetime.utcnow(),         # Registo da data/hora
        versao_termos_aceitos="v1.0.0"               # Controle da versão atual dos seus termos
    )
    
    db.add(novo_usuario)
    await db.commit()
    
    return {"message": "Utilizador registado com sucesso!"}
Use o código com cuidado.
💡 Dica de Segurança e UX:
Ao estruturar a tabela desta forma, se no futuro a sua plataforma atualizar as políticas de segurança para uma versão "v2.0.0", poderá facilmente identificar na base de dados quais utilizadores têm a versão antiga e forçar um ecrã de "Aceite os novos termos" quando eles fizerem o próximo login.
Deseja também ajuda para estruturar o middleware ou a lógica que bloqueia o acesso à plataforma caso o utilizador tenha aceite uma versão desatualizada dos termos?
