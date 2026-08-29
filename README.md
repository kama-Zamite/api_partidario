_Projeto de Api de um partido politico_


> Politic RESTAPI by Tecsyra 


## Descricao


## Tecnologia / Ferramentas

![Postgres](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/sqlalchemy-%23D71F00.svg?style=for-the-badge&logo=sqlalchemy&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571.svg?style=for-the-badge&logo=fastapi)
![Visual Studio Code](https://img.shields.io/badge/Visual%20Studio%20Code-0078d7.svg?style=for-the-badge&logo=visual-studio-code&logoColor=white)
![Pytest](https://img.shields.io/badge/pytest-%23ffffff.svg?style=for-the-badge&logo=pytest&logoColor=2f9fe3)
![Git](https://img.shields.io/badge/git-%23F05033.svg?style=for-the-badge&logo=git&logoColor=white)
![Miro](https://img.shields.io/badge/Miro-%23F2CA02.svg?style=for-the-badge&logo=miro&logoColor=black)

# git reset --soft HEAD~5 -> esse comando permite remover os commits mas deixa o codigo intacto ao contrario do --hard

### ativar vpn

```
    git config --global http.proxy http://IP_DO_PROXY:PORTA
    git config --global https.proxy http://IP_DO_PROXY:PORTA

```
### desativar o vpn
```
  git config --global --unset http.proxy
  git config --global --unset https.proxy
```


```
  A APISERVER esta hospedada num servidor gratis 'Redis' ->  

  Database: Neon
```

Gerar o arquivo de imagem do QR Code diretamente no backend é ideal, pois você pode guardar o arquivo num servidor de ficheiros (como S3) ou enviá-lo diretamente por e-mail no futuro.

Para fazer isto em Python de forma assíncrona e rápida, usamos a biblioteca qrcode (junto com a pillow para desenhar a imagem). 

Como a criação da imagem consome processamento, vamos usar o asyncio.to_thread para que essa geração não trave a sua API FastAPI.

🛠️ Passo 1: Instalar as dependênciasAntes de rodar o código, certifique-se de instalar as duas bibliotecas necessárias no seu ambiente virtual:
```bash
  pip install qrcode pillow
  Use o código com cuidado.
```