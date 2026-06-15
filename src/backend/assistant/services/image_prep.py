"""Pré-processamento de foto de recibo antes de enviar ao modelo de visão.

Recibos térmicos chegam girados (EXIF), grandes e com baixo contraste/marca
d'água. Normalizar orientação, tamanho e contraste melhora muito o OCR do
modelo. Qualquer falha é silenciosa: devolve a imagem original, nunca quebra o
fluxo de chat.
"""

import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAX_DIMENSION = 2000  # lado maior, em px


def prepare_receipt_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Normaliza a foto do recibo. Retorna ``(bytes, media_type)``.

    Em caso de qualquer erro, retorna ``(data, media_type)`` inalterados.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img)  # corrige orientação da câmera
        img = ImageOps.grayscale(img)  # tinta vs. marca d'água colorida
        img = ImageOps.autocontrast(img)  # realça papel térmico desbotado
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))  # downscale preservando proporção
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.warning("Falha ao pré-processar imagem de recibo; usando original.")
        return data, media_type
