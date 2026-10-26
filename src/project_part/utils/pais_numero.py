import phonenumbers


def obter_pais_do_numero(numero_e164: str) -> str:
    """Retorna a sigla do país (ex: 'AO') a partir de um número já validado"""
    parsed = phonenumbers.parse(numero_e164, None)
    return phonenumbers.region_code_for_number(parsed)

# pais = obter_pais_do_numero(usuario.telefone)  # Retorna "AO" ou "PT"