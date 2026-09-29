# ---------------------------------------------------------------------------
# ATUALIZAR
# ---------------------------------------------------------------------------
@event.put('/upgrade/{id_event}', status_code=HTTPStatus.OK)
@limiter.limit('2/minute')
async def atualizar_evento(
    id_event: uuid.UUID,
    request: Request,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
    titulo: str = Form(..., max_length=200),
    descricao: str = Form(...),
    localizacao: str = Form(..., max_length=255),
    data_inicio: datetime = Form(...),
    nome_categoria: EventoCategoriaEnum = Form(...),
    nome_provincia: str = Form(...),
    nome_municipio: str = Form(...),
    max_participantes: int | None = Form(None, gt=0),
    image_event: UploadFile | None = File(None, description='Imagem do evento (jpg, jpeg)'),
):
    try:
        dados_valido = CreateEvent(
            titulo=titulo,
            descricao=descricao,
            localizacao=localizacao,
            data_inicio=data_inicio,
            categoria=nome_categoria,
            nome_provincia=nome_provincia,
            nome_municipio=nome_municipio,
            max_participantes=max_participantes,
        )
    except ValidationError as e:
        logger.error('Erro de validação ao atualizar evento: %s', str(e))
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=e.errors(include_url=False, include_context=False),
        )
 
    evento_banco = await session.scalar(select(Event).where(Event.id == id_event))
    if not evento_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Evento não encontrado')
 
    # Validação de território do evento existente
    if scope.provincia_id and scope.provincia_id != evento_banco.provincia_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você não gerencia o território deste evento.',
        )
 
    if scope.municipio_id and scope.municipio_id != evento_banco.municipio_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você não gerencia o município deste evento.',
        )
 
    # Validação da nova província / município
    provincia_banco = await session.scalar(
        select(Provincia).where(Provincia.nome_provincia == dados_valido.nome_provincia)
    )
    if not provincia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')
 
    if scope.provincia_id and provincia_banco.id != scope.provincia_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você só pode atualizar eventos na sua província.',
        )
 
    municipio_banco = await session.scalar(
        select(Municipio).where(
            Municipio.nome_municipio == dados_valido.nome_municipio,
            Municipio.id_provincia == provincia_banco.id,
        )
    )
    if not municipio_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'O município "{dados_valido.nome_municipio}" não pertence à província "{dados_valido.nome_provincia}"',
        )
 
    if scope.municipio_id and municipio_banco.id != scope.municipio_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você só pode atualizar eventos no seu município.',
        )
 
    # Imagem (opcional): validada e lida ANTES de alterar qualquer campo do evento,
    # e só depois de o utilizador ter passado todas as verificações de permissão.
    conteudo_byte = None
    if image_event and image_event.filename:
        conteudo_byte = await _ler_imagem_evento(image_event)
 
    # Atualiza campos
    evento_banco.titulo = dados_valido.titulo
    evento_banco.descricao = dados_valido.descricao
    evento_banco.localizacao = dados_valido.localizacao
    evento_banco.data_inicio = dados_valido.data_inicio
    evento_banco.categoria = dados_valido.categoria
    evento_banco.provincia_id = provincia_banco.id
    evento_banco.municipio_id = municipio_banco.id
    evento_banco.max_participantes = dados_valido.max_participantes
 
    nova_url = None
    public_id_novo = f'atividades_partido/event_{evento_banco.id}'
 
    if conteudo_byte:
        try:
            nova_url = await upload_imagem_geral(
                file_bytes=conteudo_byte,
                identificador=str(evento_banco.id),
                pasta_alvo='atividades_partido',
                prefixo_arquivo='event',
            )
            evento_banco.image_url = nova_url
        except ValueError as e:
            # Erros de sanitização da imagem
            await session.rollback()
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
        except Exception as e:
            await session.rollback()
            logger.error('Falha ao subir imagem do evento %s: %s', id_event, e)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail='Falha ao salvar a imagem no serviço de nuvem.',
            )
 
    try:
        await session.commit()
        await caches.delete(CACHE_KEY_LISTA)
        logger.info('Evento [%s] atualizado com sucesso por %s.', evento_banco.titulo, current_user.email)
        return {'msg': 'Evento atualizado com sucesso!'}
 
    except IntegrityError as e:
        await session.rollback()
 
        # Se o upload foi feito mas o commit falhou → remove a imagem órfã
        if nova_url:
            await compensar_upload_orfao(public_id_novo)
 
        logger.error('Erro de integridade ao atualizar evento: [%s]', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Dados conflitantes ao atualizar o evento.',
        )
    except Exception:
        await session.rollback()
        if nova_url:
            await compensar_upload_orfao(public_id_novo)
        raise