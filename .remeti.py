import re
import phonenumbers
from pydantic import field_validator

# ... dentro da sua classe Pydantic ...

    @field_validator('telefone')
    @classmethod
    def validar_numero_telefone(cls, tel_number: str) -> str:
        if not tel_number or tel_number.strip() == "":
            raise             ValueError("O número de telefone não pode ser vazio")
        
        # 1. Limpa espaços e caracteres especiais
        numero_limpo = re.sub(r'[^\d+]', '', tel_number.strip())
        
        # 2. Mantém a conveniência para Angola (9 dígitos diretos)
        if len(numero_limpo) == 9 and numero_limpo.startswith(('91', '92', '93', '94', '95', '99')):
            numero_limpo = f"+244{numero_limpo}"
        
        if not numero_limpo.startswith('+'):
            numero_limpo = f"+{numero_limpo}"

        try:
            # 3. Parse com a biblioteca do Google
            parsed_number = phonenumbers.parse(numero_limpo, "AO")
            
            if not phonenumbers.is_valid_number(parsed_number):
                raise ValueError("Formato inválido")
                
            # 4. CAPTURA O CÓDIGO DO PAÍS (Ex: "AO", "PT", "BR", "US")
            codigo_pais = phonenumbers.region_code_for_number(parsed_number)
            
            # 5. [OPCIONAL] FILTRO DE RESTRIÇÃO DE PAÍSES
            # Se quiser bloquear algum país, basta adicionar a sigla à lista abaixo
            paises_bloqueados = ["CN", "RU"] # Exemplo: China e Rússia bloqueados
            if codigo_pais in paises_bloqueados:
                raise ValueError(f"Envios para o país {codigo_pais} não são permitidos.")
            
            # Nota: Se quiser APENAS permitir certos países (ex: Angola e Portugal), use:
            # paises_permitidos = ["AO", "PT"]
            # if codigo_pais not in paises_permitidos:
            #     raise ValueError("País não suportado.")

            # 6. Retorna o número formatado no padrão internacional E.164
            numero_final = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
            
            # DICA: Se precisar de salvar a sigla do país na Base de Dados, 
            # pode passá-la temporariamente para um atributo privado ou log do sistema aqui.
            # print(f"Número válido detetado para o país: {codigo_pais}") 
            
            return numero_final
            
        except Exception as e:
            # Mantém a mensagem de erro clara se for um bloqueio explícito feito acima
            erro_msg = str(e) if "permitidos" in str(e) or "suportado" in str(e) else \
                'Número de telefone inválido. Insira um número válido com o prefixo internacional (ex: +244... ou +351...).'
            raise ValueError(erro_msg)
