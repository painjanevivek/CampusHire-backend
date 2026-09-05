import base64
from io import BytesIO
from pathlib import PurePath

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from app.models.profile import ProfilePhoto

MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_PIXELS = 8_000_000


class InvalidPhoto(ValueError):
    pass


class ProfilePhotoResponse(BaseModel):
    data_url: str | None = None


def photo_response(photo: ProfilePhoto | None) -> ProfilePhotoResponse:
    return ProfilePhotoResponse(
        data_url="data:image/jpeg;base64," + base64.b64encode(photo.image).decode("ascii")
        if photo
        else None
    )


def normalize_photo(data: bytes, content_type: str, filename: str) -> bytes:
    """Discard original bytes/metadata; only a bounded decoded JPEG is persisted."""
    formats = {"image/jpeg": ("JPEG", {".jpg", ".jpeg"}), "image/png": ("PNG", {".png"})}
    expected = formats.get(content_type)
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise InvalidPhoto("Choose a photo smaller than 2 MB.")
    if expected is None or PurePath(filename).suffix.lower() not in expected[1]:
        raise InvalidPhoto("Choose a JPEG or PNG photo.")
    try:
        with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as source:
            if source.format != expected[0] or source.width * source.height > MAX_PHOTO_PIXELS:
                raise InvalidPhoto("Choose a JPEG or PNG photo with at most 8 megapixels.")
            if getattr(source, "n_frames", 1) != 1:
                raise InvalidPhoto("Choose a still photo, not an animation.")
            source.verify()
        with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail((512, 512))
            # A fresh image drops EXIF/GPS, comments, profiles, and trailing payloads.
            rgba = oriented.convert("RGBA")
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            output = BytesIO()
            clean.save(output, format="JPEG", quality=85)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise InvalidPhoto("This photo could not be read. Choose another JPEG or PNG.") from error
