from io import BytesIO

import pytest
from PIL import Image

from app.modules.profiles.photo import InvalidPhoto, normalize_photo


def png_bytes(size: tuple[int, int] = (600, 400)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return output.getvalue()


def test_photo_is_resized_and_reencoded_without_original_payload() -> None:
    photo = normalize_photo(png_bytes() + b"untrusted trailing data", "image/png", "photo.png")
    with Image.open(BytesIO(photo)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 512
        assert not image.getexif()
    assert b"untrusted trailing data" not in photo


@pytest.mark.parametrize(
    "data,mime,name",
    [
        (b"<svg onload='alert(1)'/>", "image/svg+xml", "photo.svg"),
        (b"broken", "image/png", "photo.png"),
        (png_bytes(), "image/jpeg", "photo.jpg"),
        (png_bytes(), "image/png", "photo.svg"),
        (b"x" * (2 * 1024 * 1024 + 1), "image/png", "photo.png"),
        (png_bytes((3000, 3000)), "image/png", "photo.png"),
    ],
    ids=["svg", "corrupt", "mime-mismatch", "extension-mismatch", "byte-limit", "pixel-limit"],
)
def test_invalid_photo_is_rejected(data: bytes, mime: str, name: str) -> None:
    with pytest.raises(InvalidPhoto):
        normalize_photo(data, mime, name)
