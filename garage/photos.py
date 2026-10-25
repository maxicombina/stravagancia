"""Bounded, in-memory photo processing. No filesystem, database or storage writes.

JPEG/PNG/WebP only, static images; output always metadata-free WebP quality 85.
Callers own authorization and persistence (garage-010). Stream input is consumed
from its current position, never closed, and filenames/MIME hints are ignored.
"""
from dataclasses import dataclass
from io import BytesIO
import uuid
import warnings

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError, features


MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_DECODED_PIXELS = 25_000_000
MAX_LONG_EDGE = 2000
WEBP_QUALITY = 85
SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP")


@dataclass(frozen=True)
class ProcessedPhoto:
    data: bytes
    width: int
    height: int
    content_type: str
    filename: str


def _error(code, message):
    return ValidationError(message, code=code)


def _read_bounded(source):
    if isinstance(source, bytes):
        data = source
    else:
        if not callable(getattr(source, "read", None)):
            raise _error("photo_invalid_input", "La foto debe ser contenido binario o un archivo binario.")
        chunks, count = [], 0
        try:
            while True:
                chunk = source.read(min(64 * 1024, MAX_UPLOAD_BYTES + 1 - count))
                if not isinstance(chunk, bytes):
                    raise _error("photo_invalid_input", "La foto debe ser un archivo binario.")
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_UPLOAD_BYTES:
                    raise _error("photo_too_large", "La foto supera el límite de 15 MiB.")
                chunks.append(chunk)
        except (OSError, ValueError) as error:
            raise _error("photo_read_failed", "No se pudo leer la foto.") from error
        data = b"".join(chunks)
    if len(data) > MAX_UPLOAD_BYTES:
        raise _error("photo_too_large", "La foto supera el límite de 15 MiB.")
    if not data:
        raise _error("photo_empty", "El archivo de foto está vacío.")
    return data


def _validate_size(image):
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_DECODED_PIXELS:
        raise _error("photo_pixel_limit", "La foto supera el límite de 25 megapíxeles.")


def _unsupported_signature(data):
    return (data.startswith((b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
            or (len(data) >= 12 and data[4:8] == b"ftyp"))


def process_photo(source):
    """Validate a bounded upload, orient, fit within 2000 px, encode WebP.

    Raises ValidationError with a stable photo_* code; no client filename or
    decoder exception text is exposed. Reopens after verify() to force decoding.
    """
    data = _read_bounded(source)
    if _unsupported_signature(data):
        raise _error("photo_unsupported_format", "Solo se admiten fotos JPEG, PNG o WebP estáticas.")
    if not features.check("webp"):
        raise _error("photo_webp_unavailable", "El servidor no dispone del codificador WebP.")
    clean = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=SUPPORTED_FORMATS) as probe:
                if probe.format not in SUPPORTED_FORMATS:
                    raise _error("photo_unsupported_format", "Solo se admiten fotos JPEG, PNG o WebP estáticas.")
                _validate_size(probe)
                if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) != 1:
                    raise _error("photo_animated", "No se admiten fotos animadas ni archivos con varias imágenes.")
                probe.verify()
            with Image.open(BytesIO(data), formats=SUPPORTED_FORMATS) as image:
                _validate_size(image)
                image.load()
                with ImageOps.exif_transpose(image) as oriented:
                    mode = "RGBA" if oriented.has_transparency_data else "RGB"
                    # A fresh pixel-only image avoids forwarding EXIF, GPS, ICC,
                    # XMP, comments or other source metadata to the encoder.
                    with oriented.convert(mode) as converted:
                        # Palette images force NEAREST when resized directly;
                        # convert first so LANCZOS also smooths their alpha.
                        if max(converted.size) > MAX_LONG_EDGE:
                            converted.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
                        clean = Image.new(mode, converted.size)
                        clean.paste(converted)
    except ValidationError:
        if clean is not None:
            clean.close()
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        if clean is not None:
            clean.close()
        raise _error("photo_pixel_limit", "La foto supera el límite de píxeles seguro.") from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, TypeError, OverflowError) as error:
        if clean is not None:
            clean.close()
        raise _error("photo_invalid_image", "La foto está dañada o no es una imagen admitida.") from error
    try:
        output = BytesIO()
        clean.save(output, format="WEBP", quality=WEBP_QUALITY, method=4, exact=True)
        result = ProcessedPhoto(data=output.getvalue(), width=clean.width, height=clean.height,
                                content_type="image/webp", filename=f"{uuid.uuid4().hex}.webp")
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        raise _error("photo_encode_failed", "No se pudo comprimir la foto.") from error
    finally:
        clean.close()
    return result
