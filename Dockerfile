FROM python:3.13

ENV POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

ENV PYTHONPATH=/app

COPY pyproject.toml ./

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

RUN poetry install --no-interaction --no-ansi --without dev --no-root --no-cache

COPY . .

EXPOSE 10000

ENTRYPOINT ["uvicorn"]

CMD ["src.project_part.main:app", "--host", "0.0.0.0", "--port", "10000", "--proxy-headers", "--forwarded-allow-ips=*"]



# events {
#     worker_connections 1024;
# }

# http {
#     # Configuração exclusiva de Desenvolvimento Local (Apenas Porta 80)
#     server {
#         listen 80;
#         server_name localhost;

#         location / {
#             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#             proxy_set_header X-Forwarded-Proto $scheme;
#             proxy_set_header Host $http_host;
#             proxy_redirect off;
            
#             # Encaminha direto para o container da sua API
#             proxy_pass http://server_api:10000;
#         }
#     }
# }















# events {
#     worker_connections 1024;
# }

# http {
#     # 1. Servidor para Desenvolvimento Local (PORTA 80 DIRETA)
#     server {
#         listen 80;
#         server_name localhost; # 👈 Trata o localhost de forma isolada

#         location / {
#             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#             proxy_set_header X-Forwarded-Proto $scheme;
#             proxy_set_header Host $http_host;
#             proxy_redirect off;
#             proxy_pass http://server_api:8000;
#         }
#     }

#     # 2. Redirecionamento de Produção (Apenas para o domínio real na internet)
#     server {
#         listen 80;
#         server_name seu_dominio.com www.seu_dominio.com;
#         return 301 https://$host$request_uri;
#     }

#     # 3. Servidor HTTPS Seguro de Produção
#     server {
#         listen 443 ssl;
#         server_name seu_dominio.com www.seu_dominio.com;

#         ssl_certificate /etc/nginx/certs/seu_certificado.crt;
#         ssl_certificate_key /etc/nginx/certs/sua_chave.key;

#         ssl_protocols TLSv1.2 TLSv1.3;
#         ssl_ciphers HIGH:!aNULL:!MD5;

#         location / {
#             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#             proxy_set_header X-Forwarded-Proto $scheme;
#             proxy_set_header Host $http_host;
#             proxy_redirect off;
#             proxy_pass http://server_api:8000;
#         }
#     }
# }

