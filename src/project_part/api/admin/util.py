from .schemas import DoacaoResponse, QuotaResponse, SolicitacaoFundoResponse
from project_part.model.models import Doacao, PagamentoQuota, SolicitacaoFundo


def to_doacao_response(doacao: Doacao) -> DoacaoResponse:
    # Acesso seguro: garante que doador E provincia existem antes de buscar o nome
    provincia_nome = None
    municipio_nome = None
    if doacao.doador and doacao.doador.provincia:
        provincia_nome = doacao.doador.provincia.nome_provincia
        municipio_nome = doacao.doador.municipio.nome_municipio

    return DoacaoResponse(
        id=doacao.id,
        provincia=provincia_nome,  # Passa uma string ou None com segurança
        municipio=municipio_nome,
        user_id=doacao.user_id,
        quantia=doacao.quantia,
        moeda=doacao.moeda,
        metodo_pagamento=doacao.metodo_pagamento,
        referencia=doacao.referencia,
        id_transacao=doacao.id_transacao,
        status=doacao.status,
        observacao=doacao.observacao,
        data_doacao=doacao.data_doacao,
        aprovado_em=doacao.aprovado_em,
        recibo_url=doacao.recibo_url,
        recibo_gerado_em=doacao.recibo_gerado_em,
        atualizado_em=doacao.atualizado_em,
        nome_doador=doacao.doador.nome_completo if doacao.doador else None,
        nome_aprovador=doacao.aprovador,
        scope_aprovador=doacao.aprovador.scope if doacao.aprovador else None,
    )


# def to_quota_response(pag: PagamentoQuota) -> QuotaResponse:
#     return QuotaResponse(
#         id=pag.id,
#         user_id=pag.user_id,
#         quantia=pag.quantia,
#         moeda=pag.moeda,
#         periodo=pag.periodo,
#         metodo_pagamento=pag.metodo_pagamento,
#         referencia=pag.referencia,
#         provincia = pag.provincia.nome_provincia if pag.provincia else None,
#         id_transacao=pag.id_transacao,
#         status=pag.status,
#         observacao=pag.observacao,
#         data_pagamento=pag.data_pagamento,
#         aprovado_por=pag.aprovado_por,
#         aprovado_em=pag.aprovado_em,
#         atualizado_em=pag.atualizado_em,
#         nome_militante=pag.militante.nome_completo if pag.militante else None,
#     )



def to_quota_response(pag: PagamentoQuota) -> QuotaResponse:

    provincia_nome = None
    municipio_nome = None
    if pag.militante and pag.militante.provincia:
        provincia_nome = pag.militante.provincia.nome_provincia
        municipio_nome = pag.militante.municipio.nome_municipio

    return QuotaResponse(
        id=pag.id,
        provincia=provincia_nome,  # Passa uma string ou None com segurança
        municipio=municipio_nome,
        militante_numero= pag.militante.militante_numero if pag.militante and pag.militante.militante_numero else None,
        user_id=pag.user_id,
        quantia=pag.quantia,
        moeda=pag.moeda,
        periodo=pag.periodo,
        metodo_pagamento=pag.metodo_pagamento,
        referencia=pag.referencia,
        id_transacao=pag.id_transacao,
        status=pag.status,
        observacao=pag.observacao,
        data_pagamento=pag.data_pagamento,
        aprovado_em=pag.aprovado_em,
        atualizado_em=pag.atualizado_em,
        nome_militante=pag.militante.nome_completo if pag.militante else None,
        nome_aprovador=pag.aprovador,
        scope_aprovador=pag.aprovador.scope if pag.aprovador else None,
    )
    
def to_solicitacao_response(s: SolicitacaoFundo) -> SolicitacaoFundoResponse:
    nome_solicitante = None
    if s.user:
        nome_solicitante = s.user.nome_completo

    return SolicitacaoFundoResponse(
        id=s.id,
        provincia_id=s.provincia_id,
        municipio_id=s.municipio_id,
        finalidade=s.finalidade,
        descricao=s.descricao,
        quantia=s.quantia,
        moeda=s.moeda,
        status=s.status,
        observacao=s.observacao,
        solicitado_por=nome_solicitante,
        # aprovado_por=s.aprovado_por,
        data_solicitacao=s.data_solicitacao,
        aprovado_em=s.aprovado_em,
        nome_provincia=s.provincia.nome_provincia if s.provincia else None,
        nome_solicitante=None,  # preenche se fizeres load do user
    )





