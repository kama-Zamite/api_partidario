
@auth.post('/login', status_code=status.HTTP_200_OK, summary='Autenticação de Usuário')
@limiter.limit('3/minute')
async def login(
    request: Request,
    response: Response,
    session: Session,
    token: Access_token,
    # backgroundTasks: BackgroundTasks,
    _captcha: Claudflare_turnfile,
):
    """Endpoint para autenticação de usuário."""
    logger.info('Tentativa de login para o usuário: %s', token.username)
    try:
        # Isolamento estrito da primeira query
        user = await session.scalar(select(User).where(User.email == token.username))
    except Exception as query_err:
        await session.rollback()
        logger.error('Falha crítica ao consultar utilizador no banco: %s', str(query_err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento na base de dados.',
        )
    if user and not user.ativo:
        logger.warning('Tentativa de login em conta desativada: %s', token.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='E-mail ou senha incorretos')
    if not user:
        logger.warning('Falha de login: usuario %s nao encontrado', token.username)
        # Executa a verificação dummy para mitigar ataques de temporização (Timing Attacks)
        verify_password(token.password, settings.DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='E-mail ou senha incorretos',
        )
    agora = datetime.now(timezone.utc)
    if user.bloqueado_permanente:
        logger.warning('Tentativa de login em conta bloqueada permanentemente: %s', token.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Conta bloqueada por segurança. Verifique seu e-mail para desbloquear.',
        )
    if user.bloqueado_ate and agora < user.bloqueado_ate:
        tempo_restante = int((user.bloqueado_ate - agora).total_seconds() / 60)
        logger.warning('Tentativa de login em conta temporariamente bloqueada: %s', token.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Muitas tentativas. Tente novamente em {tempo_restante} minutos.',
        )
    # --- Fluxo de Senha Incorreta ---
    if not verify_password(token.password, user.password_hash):
        # CORREÇÃO 1: Evita quebra por NoneType caso os valores na BD estejam como NULL
        tentativa_acertos = user.tentativa_acertos or 0
        tentativas_apos_bloqueio = user.tentativas_apos_bloqueio or 0
        if tentativa_acertos >= 5:
            user.tentativas_apos_bloqueio = tentativas_apos_bloqueio + 1
            logger.warning('Erro após desbloqueio temporário. Erro número: %d/2', user.tentativas_apos_bloqueio)
            if user.tentativas_apos_bloqueio >= 2:
                user.bloqueado_permanente = True
                logger.error('Usuário %s atingiu o limite máximo e foi bloqueado PERMANENTEMENTE.', token.username)
        else:
            user.tentativa_acertos = tentativa_acertos + 1
            if user.tentativa_acertos == 5:
                user.bloqueado_ate = agora + timedelta(minutes=15)
                logger.warning('Usuário %s atingiu 5 erros. Bloqueado por 15 minutos.', token.username)
        try:
            session.add(user)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error('Não foi possível atualizar as tentativas de acerto no DB: %s', str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='E-mail ou senha incorretos')
 
    # [FIX-2FA] IP calculado pelo helper partilhado (mesma lógica no /2fa-verify).
    #           Substitui o bloco anterior que usava o x-forwarded-for em bruto.
    ip_address = get_client_ip(request)
    # 3. Capturar o User-Agent (Navegador/Dispositivo)
    user_agent = request.headers.get('user-agent')
 
    # --- Senha correta: reset dos contadores de erro ---
    logger.info('Senha validada. Resetando contadores de tentativas do usuario')
    # [FIX-2FA] `user.ultimo_login = agora` FOI MOVIDO: só é gravado quando o
    #           login estiver realmente completo (após o 2FA, no /2fa-verify,
    #           ou abaixo, no fluxo sem 2FA).
    user.tentativas_apos_bloqueio = 0
    user.tentativa_acertos = 0
    user.bloqueado_ate = None
 
    if user.two_factor_enabled:
        logger.info('Usuário %s requer verificação de 2FA.', token.username)
        # [FIX-2FA] Senha validada -> emite challenge de curta duração, uso único,
        #           ligada ao utilizador + IP + User-Agent. Nenhuma sessão/cookie
        #           é criada aqui. Se falhar a gravar, NÃO devolvemos require_2fa
        #           (antes o erro era só logado e a resposta seguia como sucesso).
        try:
            challenge_token = await criar_challenge_2fa(
                session=session,
                user_id=user.id,
                ip=ip_address,
                user_agent=user_agent,
            )
            session.add(user)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error('Falha ao criar challenge 2FA: %s', str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Erro interno de processamento.',
            )
 
        response.headers['Cache-Control'] = 'no-store'
        # [FIX-2FA] Já NÃO devolvemos `user_id`; devolvemos a challenge opaca.
        return {
            'require_2fa': True,
            'challenge_token': challenge_token,
            'expires_in': int(CHALLENGE_TTL.total_seconds()),
            'message': 'Autenticação de dois fatores necessária. Verifique seu dispositivo.',
        }
 
    logger.info('Usuário %s autenticado com sucesso (Sem 2FA)', token.username)
    # [FIX-2FA] ultimo_login gravado aqui (fluxo sem 2FA = login completo).
    user.ultimo_login = agora
    token_gerado = create_token({'sub': str(user.id)})


    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,
        user_id=user.id,
        ip=ip_address,
        user_agent=user_agent,
    )
    try:
        session.add(user)
        await session.commit()
        # CORREÇÃO 2: Removido o 'await session.refresh(user)' que causava colisão de transação
        # com middlewares assíncronos de resposta após o commit já ter sido efetivado.
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))
 
    # enviar email
    user_agent_parsed = parse(user_agent)
    # try:
    #     backgroundTasks.add_task(
    #         email_sucesso_login_async,
    #         nome_completo=user.nome_completo,
    #         ip_address=ip_address,
    #         email_destino=user.email,
    #         navegador=user_agent_parsed.browser.family,
    #         sistema_operacional=user_agent_parsed.os.family,
    #         )
    #     logger.info("E-mail de login enviado com sucesso para %s", user.email)
    # except Exception as e:
    #     logger.error("Falha ao enviar e-mail de login para %s: %s", user.email, str(e))
    set_auth_cookies(
        response=response,
        access_token=token_gerado,
        refresh_token=refresh_gerado,
    )
    response.headers['Cache-Control'] = 'no-store'
    return {
        'require_2fa': False,
        'status': 'success',
        'message': 'Autenticação realizada com sucesso.',
    }
 

 























@auth.post('/login/2fa-verify', status_code=HTTPStatus.OK, summary='Verificação de 2FA')
@limiter.limit('7/minute')
async def verify_2fa(
    response: Response,
    request: Request,
    body: Login2FARequest,
    session: Session,
    backgroundTasks: BackgroundTasks,
):
    """
    Endpoint para verificação de autenticação de dois fatores (2FA).
    Recebe a challenge emitida pelo /login (após validar a senha) e o código 2FA.
    Se tudo estiver correcto, emite o access token e o refresh token.
 
    Args:
        body (Login2FARequest): challenge_token + codigo (TOTP de 6 ou backup de 8 dígitos).
 
    Raises:
        HTTPException [401]: challenge inválida, expirada, já usada ou de outra origem.
        HTTPException [400]: código 2FA incorreto.
    """
    # [FIX-2FA] O user_id deixou de vir do cliente. O utilizador é derivado da challenge.
    ip_address = get_client_ip(request)
    user_agent = request.headers.get('user-agent')
 
    # [FIX-2FA] 1) A challenge tem de existir, estar válida e ter sido emitida
    #           para este mesmo IP/User-Agent. Sem challenge -> sem 2FA.
    challenge = await obter_challenge_valida(
        session=session,
        token_em_claro=body.challenge_token,
        ip=ip_address,
        user_agent=user_agent,
    )
    if not challenge:
        logger.warning('Challenge 2FA inválida, expirada, usada ou de origem diferente (ip=%s)', ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
 
    # Guardamos os ids antes dos commits seguintes (evita lazy-load em objectos expirados)
    challenge_id = challenge.id
    user_id = challenge.user_id
 
    # [FIX-2FA] 2) Conta a tentativa ANTES de validar o código (atómico).
    #           Após CHALLENGE_MAX_ATTEMPTS erros, a challenge morre e é preciso
    #           refazer o login com a senha.
    if not await registrar_tentativa(session, challenge_id):
        logger.warning('Challenge %s sem tentativas restantes', challenge_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
 
    logger.info('Tentativa de verificação 2FA para o usuário: %s', user_id)
    # [FIX-2FA] 3) Utilizador vem da challenge (user_id validado no login), não do body.
    user = await session.scalar(select(User).where(User.id == user_id))
    # [FIX-2FA] Revalida estado da conta (pode ter sido bloqueada/desativada entre o
    #           login e o 2FA).
    if not user or not user.ativo or user.bloqueado_permanente or not user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
 
    codigo_limpo = body.codigo.strip()
    codigo_encontrado = None  # [FIX-2FA] só preenchido se for código de backup
 
    if len(codigo_limpo) == 6:
        totp = pyotp.TOTP(user.two_factor_secret)
        logger.info('Verificando código 2FA para o usuário: %s', user_id)
        # valid_window=1 permite aceitar códigos válidos dentro de uma janela de tempo de 30 segundos antes ou depois do código atual.
        if not totp.verify(codigo_limpo, valid_window=1):
            logger.warning('Código 2FA inválido para o usuário: %s', user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Código 2FA inválido ou expirado.',
            )
    elif len(codigo_limpo) == 8:
        # Aqui esta a lógica para verificar o código de backup de 8 dígitos.
        backup_result = await session.scalars(
            select(BackupCode).where(
                BackupCode.user_id == user.id,
                BackupCode.used == False,  # noqa: E712
            )
        )
        codigos_disponiveis = backup_result.all()
 
        for codigo in codigos_disponiveis:
            if verify_password(codigo_limpo, codigo.code_hash):
                codigo_encontrado = codigo
                break
        if not codigo_encontrado:
            logger.warning('Código de backup inválido para o usuário: %s', user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Código de resgate inválido ou já utilizado.',
            )
        # [FIX-2FA] O código de backup passou a ser marcado como usado mais abaixo,
        #           na MESMA transacção que consome a challenge (tudo ou nada).
    else:
        logger.warning('Código 2FA ou de backup com tamanho inválido para o usuário: %s', user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='O código deve conter 6 dígitos (aplicativo) ou 8 dígitos (resgate).',
        )
        # [FIX-2FA] Removido o `logger.info(... token.username)` que ficava aqui:
        #           era código morto (após o raise) e `token` não existe neste endpoint.
 
    # [FIX-2FA] 4) Código correcto -> consome a challenge (uso único, atómico),
    #           queima o código de backup (se foi o usado) e regista o ultimo_login,
    #           tudo num único commit.
    nome_completo = user.nome_completo
    email_destino = user.email
    user_id_str = str(user.id)
    try:
        if not await consumir_challenge(session, challenge_id):
            # Outro pedido concorrente já consumiu esta challenge (replay)
            await session.rollback()
            logger.warning('Challenge %s já consumida (possível replay)', challenge_id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
 
        if codigo_encontrado is not None:
            # UPDATE condicional: garante uso único do código de backup mesmo com concorrência
            resultado_backup = await session.execute(
                update(BackupCode)
                .where(BackupCode.id == codigo_encontrado.id, BackupCode.used == False)  # noqa: E712
                .values(used=True)
            )
            if resultado_backup.rowcount != 1:
                await session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Código de resgate inválido ou já utilizado.',
                )
 
        # [FIX-2FA] ultimo_login gravado só agora (login realmente concluído).
        user.ultimo_login = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error('Não foi possível concluir a validação 2FA: %s', str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro ao processar validação de segurança.',
        )
 
    logger.info('Usuário %s autenticado com sucesso (2FA)', user_id_str)
 
    # [FIX-2FA] 5) Só AGORA (senha + segundo factor + challenge consumida) emitimos a sessão.
    token_gerado = create_token({'sub': user_id_str})
 
    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,
        user_id=user_id,
        ip=ip_address,
        user_agent=user_agent,
    )
 
    user_agent_parsed = parse(user_agent)
    try:
        backgroundTasks.add_task(
            email_sucesso_login_async,
            nome_completo=nome_completo,
            ip_address=ip_address,
            email_destino=email_destino,
            navegador=user_agent_parsed.browser.family,
            sistema_operacional=user_agent_parsed.os.family,
        )
        logger.info('E-mail de login enviado com sucesso para %s', email_destino)
    except Exception as e:
        logger.error('Falha ao enviar e-mail de login para %s: %s', email_destino, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Falha ao enviar e-mail de login. Tente novamente mais tarde.',
        )
 
    set_auth_cookies(
        response=response,
        access_token=token_gerado,
        refresh_token=refresh_gerado,
    )
    response.headers['Cache-Control'] = 'no-store'
    return {
        'status': 'success',
        'message': 'Autenticação realizada com sucesso.',
    }
 































import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# 1. Base Declarativa
class Base(DeclarativeBase):
    pass


# ---- ENUMS ----
class GenderEnum(PyEnum):
    MALE = 'M'
    FEMALE = 'F'
    OTHER = 'O'


class MaritalStatusEnum(PyEnum):
    SINGLE = 'solteiro'
    MARRIED = 'casado'
    DIVORCED = 'divorciado'
    WIDOWED = 'viuvo'


class DonationStatusEnum(PyEnum):
    PENDING = 'pendente'
    APPROVED = 'aprovado'
    REJECTED = 'rejeitado'


class EventStatusEnum(PyEnum):
    DRAFT = 'rascunho'
    PUBLISHED = 'publicado'
    CANCELLED = 'cancelado'
    CONCLUDED = 'concluido'


# ---- TABELAS DE ASSOCIAÇÃO (N:N) ----

# Relação N:N entre Roles e Permissions
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column(
        'role_id',
        Integer,
        ForeignKey('roles.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'permission_id',
        Integer,
        ForeignKey('permissions.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)

# Relação N:N entre Eventos e Participantes
event_participants = Table(
    'event_participants',
    Base.metadata,
    Column(
        'event_id',
        UUID(as_uuid=True),
        ForeignKey('events.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'user_id',
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column('attendance_status', String(20), default='registered'),  # registered, attended, absent
)

# ---- MODELOS PRINCIPAIS ----


class Province(Base):
    __tablename__ = 'provinces'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    municipalities: Mapped[List['Municipality']] = relationship(back_populates='province')


class Municipality(Base):
    __tablename__ = 'municipalities'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    province_id: Mapped[int] = mapped_column(ForeignKey('provinces.id', ondelete='RESTRICT'), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    province: Mapped['Province'] = relationship(back_populates='municipalities')


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    permissions: Mapped[List['Permission']] = relationship(secondary=role_permissions)


class Permission(Base):
    __tablename__ = 'permissions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    nif: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    number_militant: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    gender: Mapped[GenderEnum] = mapped_column(nullable=False)

    province_id: Mapped[int] = mapped_column(ForeignKey('provinces.id', ondelete='RESTRICT'), nullable=False)
    municipality_id: Mapped[int] = mapped_column(ForeignKey('municipalities.id', ondelete='RESTRICT'), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    membership_status_id: Mapped[int] = mapped_column(
        ForeignKey('membership_status.id', ondelete='RESTRICT'), default=1
    )

    marital_status: Mapped[Optional[MaritalStatusEnum]] = mapped_column(nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps & Auditoria de Conta
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Soft Delete

    # Relacionamentos
    scope: Mapped[Optional['AdminScope']] = relationship(back_populates='user', uselist=False)
    # cards: Mapped[List['MilitantCard']] = relationship(back_populates='user')


class AdminScope(Base):
    """Garante o controle territorial isolado para os administradores regionais"""

    __tablename__ = 'admin_scopes'

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    province_id: Mapped[Optional[int]] = mapped_column(ForeignKey('provinces.id', ondelete='SET NULL'), nullable=True)
    municipality_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('municipalities.id', ondelete='SET NULL'), nullable=True
    )

    user: Mapped['User'] = relationship(back_populates='scope')


class Event(Base):
    __tablename__ = 'events'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(ForeignKey('provinces.id'), nullable=True)
    municipality_id: Mapped[Optional[int]] = mapped_column(ForeignKey('municipalities.id'), nullable=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_participants: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[EventStatusEnum] = mapped_column(default=EventStatusEnum.DRAFT)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class News(Base):
    __tablename__ = 'news'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lead: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('news_categories.id'), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('provinces.id'), nullable=True
    )  # Notícia Regionalizada
    status: Mapped[str] = mapped_column(String(20), default='draft')  # draft, published, archived
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NewsCategory(Base):
    __tablename__ = 'news_categories'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class AuditLog(Base):
    """Armazena logs estruturados usando JSONB para consultas rápidas e auditorias jurídicas"""

    __tablename__ = 'audit_logs'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE, UPDATE, DELETE, APPROVE
    entity: Mapped[str] = mapped_column(String(50), nullable=False)  # users, donations, news
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Estado anterior do registro
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Novo estado modificado
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MilitantCard(Base):
    __tablename__ = 'militant_cards'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    card_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    qr_code_signature: Mapped[str] = mapped_column(Text, nullable=False)  # Token criptográfico anti-fraude
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    expiration_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    user: Mapped['User'] = relationship(back_populates='cards', foreign_keys=[user_id])


class Notification(Base):
    __tablename__ = 'notifications'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    lido_as: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criado_as: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class Session(Base):
    __tablename__ = 'sessions'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = 'documents'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # estatutos, diretrizes, atas
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = 'settings'

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


# class Donation(Base):
#     __tablename__ = 'donations'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('users.id', ondelete='SET NULL'),
#         nullable=True,
#     )  # Anonimização se deletado
#     amount: Mapped[float] = mapped_column(
#         Numeric(15, 2), nullable=False
#     )  # Proteção Monetária exata
#     payment_method: Mapped[str] = mapped_column(
#         String(50), nullable=False
#     )  # MCX, Transferência, IBAN
#     reference: Mapped[Optional[str]] = mapped_column(
#         String(100), unique=True, nullable=True
#     )
#     transaction_id: Mapped[Optional[str]] = mapped_column(
#         String(100), unique=True, nullable=True
#     )
#     currency: Mapped[str] = mapped_column(String(3), default='AOA')
#     status: Mapped[DonationStatusEnum] = mapped_column(
#         default=DonationStatusEnum.PENDING
#     )
#     donated_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )
#     approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True), ForeignKey('users.id'), nullable=True
#     )

#     receipt: Mapped[Optional['DonationReceipt']] = relationship(
#         back_populates='donation', uselist=False
#     )


# class DonationReceipt(Base):
#     __tablename__ = 'donation_receipts'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     donation_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('donations.id', ondelete='CASCADE'),
#         nullable=False,
#     )
#     file_url: Mapped[str] = mapped_column(Text, nullable=False)
#     generated_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )

#     donation: Mapped['Donation'] = relationship(back_populates='receipt')


# class MembershipStatus(Base):
#     __tablename__ = 'membership_status'

#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     name: Mapped[str] = mapped_column(
#         String(50), unique=True, nullable=False
#     )  # pending, approved, suspended, rejected


# class MembershipRequest(Base):
#     """Guarda o histórico e fluxo operacional de solicitações de entrada"""

#     __tablename__ = 'membership_requests'

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
#     )
#     user_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey('users.id', ondelete='CASCADE'),
#         nullable=False,
#     )
#     request_type: Mapped[str] = mapped_column(
#         String(50), default='militancy'
#     )  # militancy, promotion
#     status: Mapped[str] = mapped_column(
#         String(30), default='pending'
#     )  # pending, approved, rejected
#     approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
#         UUID(as_uuid=True), ForeignKey('users.id'), nullable=True
#     )
#     approved_at: Mapped[Optional[datetime]] = mapped_column(
#         DateTime, nullable=True
#     )
#     notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(
#         DateTime, default=datetime.utcnow
#     )
