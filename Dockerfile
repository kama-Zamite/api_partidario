ARG PYTHON_IMAGE=python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ARG POETRY_VERSION=2.4.1

# ---------- builder ----------
FROM ${PYTHON_IMAGE} AS builder
ARG POETRY_VERSION

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --without dev --no-root --no-cache

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

USER app
EXPOSE 10000

ENTRYPOINT ["uvicorn"]

# # Dev local (sem proxy reverso): sobrepõe o CMD no compose, ver abaixo
# # Render / produção:
# CMD ["src.project_part.main:app", "--host", "0.0.0.0", "--port", "10000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
# Maquina de desenvolvimento local (sem proxy reverso)
# CMD ["src.project_part.main:app", "--host", "0.0.0.0", "--port", "10000", "--no-proxy-headers"]

# para a render

CMD ["src.project_part.main:app", "--host", "0.0.0.0", "--port", "10000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]












# producao



# FROM python:3.13

# ENV POETRY_VIRTUALENVS_CREATE=false

# WORKDIR /app

# ENV PYTHONPATH=/app

# COPY pyproject.toml ./

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     gcc \
#     && rm -rf /var/lib/apt/lists/*

# RUN pip install poetry

# RUN poetry install --no-interaction --no-ansi --without dev --no-root --no-cache

# COPY . .

# EXPOSE 10000

# ENTRYPOINT ["gunicorn"]

# CMD ["src.project_part.main:app", "--workers", "3", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000", "--forwarded-allow-ips=*"]










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

