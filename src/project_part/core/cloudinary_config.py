import asyncio
import io
import logging

import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps, UnidentifiedImageError

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)

UPLOAD_TIMEOUT_SECONDS = 30.0
DELETE_TIMEOUT_SECONDS = 15.0

MAX_IMAGE_WIDTH = 4000
MAX_IMAGE_HEIGHT = 4000
MAX_IMAGE_PIXELS = 16_000_000

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def preparar_imagem_segura(file_bytes: bytes) -> bytes:
    """
    Sanitiza completamente um JPEG.

    - verifica estrutura
    - remove EXIF
    - corrige rotação
    - converte para RGB
    - regrava completamente o JPEG
    """

    try:
        #
        # Primeiro verifica a estrutura do JPEG
        #
        with Image.open(io.BytesIO(file_bytes)) as teste:
            teste.verify()

        #
        # Reabre para processamento
        #
        with Image.open(io.BytesIO(file_bytes)) as imagem:
            if imagem.format not in ('JPEG', 'JPG', 'MPO'):
                raise ValueError('Apenas imagens JPEG são aceitas.')

            largura, altura = imagem.size

            if largura > MAX_IMAGE_WIDTH:
                raise ValueError('Largura da imagem excede o limite permitido.')

            if altura > MAX_IMAGE_HEIGHT:
                raise ValueError('Altura da imagem excede o limite permitido.')

            if largura * altura > MAX_IMAGE_PIXELS:
                raise ValueError('Quantidade de pixels excede o limite permitido.')

            #
            # Corrige rotação de celulares
            #
            imagem = ImageOps.exif_transpose(imagem)

            #
            # JPEG deve ser RGB
            #
            if imagem.mode != 'RGB':
                imagem = imagem.convert('RGB')

            saida = io.BytesIO()

            imagem.save(saida, format='JPEG', quality=85, optimize=True, progressive=True)

            return saida.getvalue()

    except Image.DecompressionBombError:
        logger.warning('Imagem rejeitada por decompression bomb.')
        raise ValueError('Imagem muito grande.')

    except UnidentifiedImageError:
        logger.warning('Arquivo não é uma imagem JPEG válida.')
        raise ValueError('Imagem inválida.')

    except Exception as e:
        logger.warning('Imagem rejeitada: %s', e)
        raise ValueError(str(e))


def _sincrono_upload(arquivo, folder, public_id):
    return cloudinary.uploader.upload(
        arquivo,
        folder=folder,
        public_id=public_id,
        overwrite=True,
        unique_filename=False,
        invalidate=True,
        resource_type='image',
        transformation=[{'quality': 'auto', 'fetch_format': 'auto'}],
    )


async def upload_imagem_geral(file_bytes: bytes, identificador: str, pasta_alvo: str, prefixo_arquivo: str) -> str:

    imagem_segura = preparar_imagem_segura(file_bytes)

    public_id = f'{prefixo_arquivo}_{identificador}'

    loop = asyncio.get_running_loop()

    try:
        with io.BytesIO(imagem_segura) as arquivo:
            response = await asyncio.wait_for(
                loop.run_in_executor(None, _sincrono_upload, arquivo, pasta_alvo, public_id),
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )

    except asyncio.TimeoutError:
        logger.error('Timeout ao subir imagem %s.', public_id)
        raise RuntimeError('Timeout durante upload da imagem.')

    except Exception as e:
        logger.error('Erro ao subir imagem %s: %s', public_id, e)
        raise

    secure_url = response.get('secure_url')

    if not secure_url:
        logger.error('Cloudinary não retornou secure_url. Resposta=%s', response)
        raise RuntimeError('Cloudinary não retornou uma URL válida.')

    return secure_url


async def _apagar_do_cloudinary(public_id: str) -> bool:

    try:
        loop = asyncio.get_running_loop()

        resultado = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: cloudinary.uploader.destroy(public_id, invalidate=True)),
            timeout=DELETE_TIMEOUT_SECONDS,
        )

        ok = resultado.get('result') == 'ok'

        if ok:
            logger.info('Imagem %s removida.', public_id)
        else:
            logger.warning('Cloudinary retornou %s para %s', resultado, public_id)

        return ok

    except asyncio.TimeoutError:
        logger.error('Timeout removendo %s', public_id)

        return False

    except Exception as e:
        logger.error('Erro removendo %s: %s', public_id, e)

        return False


async def apagar_foto_perfil_cloudinary(user_id: str) -> bool:
    return await _apagar_do_cloudinary(f'perfis_usuarios/avatar_{user_id}')


async def apagar_imagem_noticia_cloudinary(noticia_id: str) -> bool:
    return await _apagar_do_cloudinary(f'noticias_portal/news_{noticia_id}')


async def apagar_imagem_evento_cloudinary(evento_id: str) -> bool:
    return await _apagar_do_cloudinary(f'atividades_partido/event_{evento_id}')


async def compensar_upload_orfao(public_id: str) -> None:
    """
    Remove uma imagem órfã do Cloudinary após falha de persistência no banco.

    Cenário:
    - Upload Cloudinary OK
    - Commit SQL falhou
    - Arquivo existe na nuvem sem referência no banco

    Se a remoção falhar, registra CRITICAL para posterior
    reconciliação manual ou job de limpeza.
    """

    try:
        removido = await _apagar_do_cloudinary(public_id)

        if removido:
            logger.info('Upload órfão removido com sucesso: %s', public_id)
            return

        logger.critical('Não foi possível remover imagem órfã do Cloudinary: %s. Necessária reconciliação.', public_id)

    except Exception as e:
        logger.critical(
            'Falha crítica ao compensar upload órfão (%s): %s. Necessária intervenção ou job de limpeza.',
            public_id,
            e,
            exc_info=True,
        )
