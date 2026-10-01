"""Downloads and prepares cover frames and slides for the vision model (UGC spec §6.4)."""

import io

import httpx
from PIL import Image, UnidentifiedImageError

from jevtrends.config import RetriesCfg
from jevtrends.http import APIError, send_with_retry
from jevtrends.llm.client import ImagePart

ACCEPTED = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
IMAGE_TIMEOUT = httpx.Timeout(30.0)


class ImageFetcher:
    """Downloads images from TikTok's CDN. Sends no API key; any failure means the image is unavailable."""

    def __init__(self, client: httpx.AsyncClient, retries: RetriesCfg):
        self.client = client
        self.retries = retries

    async def fetch(self, url: str, max_bytes: int) -> bytes | None:
        try:
            response = await send_with_retry(self.client, "tiktok_cdn", "GET", url, retries=self.retries,
                                             timeout=IMAGE_TIMEOUT)
        except APIError:
            return None
        return response.content if len(response.content) <= max_bytes else None


def prepare_image(data: bytes, max_long_edge: int) -> ImagePart | None:
    """Passes small supported images through; scales larger ones down to JPEG; None if Pillow can't read it."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format in ACCEPTED and max(image.size) <= max_long_edge:
                return ImagePart(data=data, media_type=ACCEPTED[image.format])
            rgb = image.convert("RGB")
            rgb.thumbnail((max_long_edge, max_long_edge))
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=85)
            return ImagePart(data=buffer.getvalue(), media_type="image/jpeg")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
