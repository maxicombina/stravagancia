from io import BytesIO
import re

from django.core.exceptions import ValidationError
from PIL import Image, features
import pytest

from . import photos


def encoded(image, format="PNG", **options):
    output = BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def picture(size=(60, 40), mode="RGB", format="PNG", **options):
    with Image.new(mode, size, (80, 120, 160, 128) if mode == "RGBA" else 100 if mode == "L" else (80, 120, 160)) as image:
        return encoded(image, format, **options)


def assert_error(code, source):
    with pytest.raises(ValidationError) as raised:
        photos.process_photo(source)
    assert raised.value.code == code
    return raised.value


def test_real_webp_encoder_available_and_roundtrip_generated_name():
    assert features.check("webp")
    first = photos.process_photo(picture())
    second = photos.process_photo(picture())
    assert first.content_type == "image/webp" and first.filename != second.filename
    assert re.fullmatch(r"[a-f0-9]{32}\.webp", first.filename)
    with Image.open(BytesIO(first.data)) as image:
        image.load()
        assert image.format == "WEBP" and image.size == (first.width, first.height)


@pytest.mark.parametrize("original,expected", [((4000, 3000), (2000, 1500)), ((3000, 4000), (1500, 2000)),
                                              ((1200, 800), (1200, 800)), ((2000, 1000), (2000, 1000)),
                                              ((6000, 600), (2000, 200)), ((1, 4000), (1, 2000))])
def test_long_edge_limit_aspect_small_and_panorama(original, expected):
    result = photos.process_photo(picture(original))
    assert (result.width, result.height) == expected


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_supported_real_formats_ignore_filename_and_mime(format):
    stream = BytesIO(picture(format=format))
    stream.name = "../../.env.exe"
    stream.content_type = "text/plain"
    result = photos.process_photo(stream)
    assert result.filename.endswith(".webp") and "env" not in result.filename
    assert not stream.closed


@pytest.mark.parametrize("orientation,order,dimensions", [
    (1, [0, 1, 2, 3], (80, 60)), (2, [1, 0, 3, 2], (80, 60)),
    (3, [3, 2, 1, 0], (80, 60)), (4, [2, 3, 0, 1], (80, 60)),
    (5, [0, 2, 1, 3], (60, 80)), (6, [2, 0, 3, 1], (60, 80)),
    (7, [3, 1, 2, 0], (60, 80)), (8, [1, 3, 0, 2], (60, 80)),
])
def test_all_exif_orientations_by_quadrant_pixels(orientation, order, dimensions):
    colors = [(230, 20, 20), (20, 230, 20), (20, 20, 230), (230, 230, 20)]
    with Image.new("RGB", (80, 60)) as image:
        for color, box in zip(colors, [(0, 0, 40, 30), (40, 0, 80, 30), (0, 30, 40, 60), (40, 30, 80, 60)]):
            image.paste(color, box)
        exif = Image.Exif()
        exif[274] = orientation
        result = photos.process_photo(encoded(image, "JPEG", quality=100, subsampling=0, exif=exif))
    assert (result.width, result.height) == dimensions
    with Image.open(BytesIO(result.data)) as output:
        width, height = output.size
        observed = [output.getpixel((x, y)) for x, y in [(width//4, height//4), (3*width//4, height//4),
                                                       (width//4, 3*height//4), (3*width//4, 3*height//4)]]
    for observed_color, index in zip(observed, order):
        assert all(abs(a-b) < 20 for a, b in zip(observed_color, colors[index]))


def test_orientation_before_resizing_and_metadata_not_forwarded():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "PRIVATE description"
    exif[34853] = {1: "N", 2: (1, 2, 3), 3: "E", 4: (4, 5, 6)}
    result = photos.process_photo(picture((4000, 3000), format="JPEG", exif=exif, icc_profile=b"PRIVATE ICC"))
    assert (result.width, result.height) == (1500, 2000)
    assert b"PRIVATE" not in result.data
    with Image.open(BytesIO(result.data)) as image:
        assert not image.getexif()
        assert not ({"exif", "icc_profile", "xmp", "comment"} & image.info.keys())


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_alpha_survives_without_metadata(mode):
    with Image.new("RGBA", (60, 40), (100, 150, 200, 0)) as image:
        image.paste((100, 150, 200, 128), (30, 0, 60, 40))
        if mode == "P":
            source = image.convert("P")
        elif mode == "LA":
            source = image.convert("LA")
        else:
            source = image.copy()
        with source:
            result = photos.process_photo(encoded(source))
    with Image.open(BytesIO(result.data)) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((10, 20))[3] == 0
        assert output.getpixel((50, 20))[3] == 128


def test_large_palette_transparency_uses_smooth_alpha_resampling():
    # A hard opaque/transparent palette boundary must acquire intermediate
    # alpha after downsampling. Resizing P directly would force NEAREST.
    with Image.new("P", (4000, 40), 0) as image:
        image.putpalette([0, 0, 0, 200, 100, 50] + [0] * (768 - 6))
        image.info["transparency"] = 0
        image.paste(1, (2001, 0, 4000, 40))
        result = photos.process_photo(encoded(image))
    assert (result.width, result.height) == (2000, 20)
    with Image.open(BytesIO(result.data)) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((100, 10))[3] == 0
        assert output.getpixel((1900, 10))[3] == 255
        assert any(0 < output.getpixel((x, 10))[3] < 255 for x in range(996, 1006))


@pytest.mark.parametrize("mode,format", [("L", "PNG"), ("CMYK", "JPEG")])
def test_grayscale_and_cmyk_are_normalized(mode, format):
    with Image.new(mode, (40, 30)) as image:
        result = photos.process_photo(encoded(image, format))
    with Image.open(BytesIO(result.data)) as output:
        assert output.mode == "RGB" and output.size == (40, 30)


@pytest.mark.parametrize("format", ["GIF", "BMP", "TIFF"])
def test_unsupported_real_formats_rejected(format):
    assert_error("photo_unsupported_format", picture(format=format))


def test_heic_signature_rejected_without_decoder():
    assert_error("photo_unsupported_format", b"\x00\x00\x00\x18ftypheic" + b"\x00"*20)


@pytest.mark.parametrize("format", ["PNG", "WEBP"])
def test_animated_formats_rejected_instead_of_silent_first_frame(format):
    with Image.new("RGB", (30, 20), "red") as first, Image.new("RGB", (30, 20), "blue") as second:
        source = encoded(first, format, save_all=True, append_images=[second], duration=100, loop=0)
    assert_error("photo_animated", source)


@pytest.mark.parametrize("source,code", [(b"", "photo_empty"), (b"not a photo", "photo_invalid_image"),
                                       ("filename.jpg", "photo_invalid_input"), (BytesIO(b""), "photo_empty")])
def test_invalid_inputs_have_clear_errors(source, code):
    assert_error(code, source)


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_truncated_encoded_images_rejected(format):
    data = picture((200, 100), format=format)
    assert_error("photo_invalid_image", data[:len(data)//2])


def test_input_byte_limit_for_bytes_and_bounded_nonseekable_stream(monkeypatch):
    source = picture()
    monkeypatch.setattr(photos, "MAX_UPLOAD_BYTES", len(source))
    assert photos.process_photo(source)
    assert_error("photo_too_large", source + b"x")
    class NonSeekable:
        def __init__(self, data):
            self.data, self.position, self.requests = data, 0, []
        def read(self, size):
            assert size > 0
            self.requests.append(size)
            value = self.data[self.position:self.position+size]
            self.position += len(value)
            return value
    valid = NonSeekable(source)
    assert photos.process_photo(valid)
    too_large = NonSeekable(source + b"x" * 100)
    assert_error("photo_too_large", too_large)
    assert too_large.position == len(source) + 1 and max(too_large.requests) <= len(source) + 1


def test_pixel_limit_checked_before_decoding_and_boundary_allowed(monkeypatch):
    monkeypatch.setattr(photos, "MAX_DECODED_PIXELS", 2400)
    assert photos.process_photo(picture((60, 40)))
    source = picture((61, 40))
    def forbidden(*args):
        raise AssertionError("Oversized images must not decode")
    monkeypatch.setattr(Image.Image, "load", forbidden)
    assert_error("photo_pixel_limit", source)


@pytest.mark.parametrize("pixels", [150, 250])
def test_pillow_bomb_warning_and_error_map_to_safe_pixel_error(monkeypatch, pixels):
    source = picture((pixels, 1))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    assert_error("photo_pixel_limit", source)


def test_read_failure_is_safe_and_no_private_exception_text():
    class BrokenStream:
        def read(self, size):
            raise OSError("PRIVATE /Users/person/.env")
    error = assert_error("photo_read_failed", BrokenStream())
    assert "PRIVATE" not in str(error) and "/Users" not in str(error)


def test_text_stream_rejected():
    class TextStream:
        def read(self, size):
            return "not binary"
    assert_error("photo_invalid_input", TextStream())


def test_decode_failure_is_safe(monkeypatch):
    source = picture(format="JPEG")
    from PIL import JpegImagePlugin
    def broken(*args):
        raise OSError("PRIVATE decoder error")
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", broken)
    error = assert_error("photo_invalid_image", source)
    assert "PRIVATE" not in str(error)


def test_encoder_failure_returns_no_partial_result(monkeypatch):
    source = picture()
    def broken(*args, **kwargs):
        raise OSError("PRIVATE encoder error")
    monkeypatch.setattr(Image.Image, "save", broken)
    error = assert_error("photo_encode_failed", source)
    assert "PRIVATE" not in str(error)


def test_webp_unavailable_is_explicit(monkeypatch):
    source = picture()
    monkeypatch.setattr(features, "check", lambda name: False)
    assert_error("photo_webp_unavailable", source)
