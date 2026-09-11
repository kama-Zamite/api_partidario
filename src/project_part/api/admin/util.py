from .schemas import DoacaoResponse, QuotaResponse, SolicitacaoFundoResponse
from project_part.model.models import Doacao, PagamentoQuota, SolicitacaoFundo

def to_doacao_response(doacao: Doacao) -> DoacaoResponse:
    return DoacaoResponse(
        id=doacao.id,
        user_id=doacao.user_id,
        quantia=doacao.quantia,
        moeda=doacao.moeda,
        metodo_pagamento=doacao.metodo_pagamento,
        referencia=doacao.referencia,
        id_transacao=doacao.id_transacao,
        status=doacao.status,
        observacao=doacao.observacao,
        data_doacao=doacao.data_doacao,
        aprovado_por=doacao.aprovado_por,
        aprovado_em=doacao.aprovado_em,
        recibo_url=doacao.recibo_url,
        recibo_gerado_em=doacao.recibo_gerado_em,
        atualizado_em=doacao.atualizado_em,
        nome_doador=doacao.doador.nome_completo if doacao.doador else None,
    )


def to_quota_response(pag: PagamentoQuota) -> QuotaResponse:
    return QuotaResponse(
        id=pag.id,
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
        aprovado_por=pag.aprovado_por,
        aprovado_em=pag.aprovado_em,
        atualizado_em=pag.atualizado_em,
        nome_militante=pag.militante.nome_completo if pag.militante else None,
    )



def to_quota_response(pag: PagamentoQuota) -> QuotaResponse:
    return QuotaResponse(
        id=pag.id,
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
        aprovado_por=pag.aprovado_por,
        aprovado_em=pag.aprovado_em,
        atualizado_em=pag.atualizado_em,
        nome_militante=pag.militante.nome_completo if pag.militante else None,
    )
    
def to_solicitacao_response(s: SolicitacaoFundo) -> SolicitacaoFundoResponse:
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
        solicitado_por=s.solicitado_por,
        aprovado_por=s.aprovado_por,
        data_solicitacao=s.data_solicitacao,
        aprovado_em=s.aprovado_em,
        nome_provincia=s.provincia.nome_provincia if s.provincia else None,
        nome_solicitante=None,  # preenche se fizeres load do user
    )





