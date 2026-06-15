import io

from PIL import Image

from assistant.services.image_prep import prepare_receipt_image


def _jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_downscales_large_image_to_max_2000px():
    big = Image.new("RGB", (3000, 4000), color=(200, 200, 200))
    out_bytes, media_type = prepare_receipt_image(_jpeg_bytes(big), "image/jpeg")
    out = Image.open(io.BytesIO(out_bytes))
    assert max(out.size) <= 2000
    assert media_type == "image/jpeg"


def test_keeps_small_image_within_bounds():
    small = Image.new("RGB", (800, 600), color=(180, 180, 180))
    out_bytes, _ = prepare_receipt_image(_jpeg_bytes(small), "image/jpeg")
    out = Image.open(io.BytesIO(out_bytes))
    assert max(out.size) <= 2000
    assert out.size[0] <= 800 and out.size[1] <= 600


def test_converts_to_grayscale_mode():
    color = Image.new("RGB", (400, 400), color=(120, 30, 200))
    out_bytes, _ = prepare_receipt_image(_jpeg_bytes(color), "image/jpeg")
    out = Image.open(io.BytesIO(out_bytes))
    assert out.mode in ("L", "LA")


def test_applies_exif_orientation():
    # imagem 100x200 marcada como girada (orientation=6 -> rotacionar 90 graus)
    img = Image.new("RGB", (100, 200), color=(150, 150, 150))
    exif = img.getexif()
    exif[274] = 6  # tag Orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    out_bytes, _ = prepare_receipt_image(buf.getvalue(), "image/jpeg")
    out = Image.open(io.BytesIO(out_bytes))
    # apos transpose, a largura passa a ser a antiga altura
    assert out.size[0] == 200 and out.size[1] == 100


def test_returns_original_on_corrupt_input():
    data = b"not an image"
    out_bytes, media_type = prepare_receipt_image(data, "image/png")
    assert out_bytes == data
    assert media_type == "image/png"
