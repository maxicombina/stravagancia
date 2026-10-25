"""Real private-bucket check for garage-010. Synthetic image only; prints OK/FALLO, never secrets.

Run from the repo root, after the user authorized and created the test bucket:

    .venv/bin/python -I tools/handoff/garage_bucket_check.py [--env-file ~/.config/garage-s3-test.env]

Loads no Django settings, database or .env. Reads only the five GARAGE_S3_* values from a
user-only file outside the repository. Touches only the keys it creates and deletes them.
"""
import argparse
import hashlib
from io import BytesIO
import os
from pathlib import Path
import stat
import sys
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw  # noqa: E402

from garage.photos import process_photo  # noqa: E402
from garage.storage import (PhotoStorageConfig, PhotoStorageError, PrivatePhotoStorage,  # noqa: E402
                            new_photo_key)

KEYS = ('GARAGE_S3_ENDPOINT_URL', 'GARAGE_S3_REGION', 'GARAGE_S3_BUCKET',
        'GARAGE_S3_ACCESS_KEY_ID', 'GARAGE_S3_SECRET_ACCESS_KEY')
DEFAULT_ENV_FILE = Path.home() / '.config' / 'garage-s3-test.env'
DENIED = {401, 403}


def load_values(path):
    if not path.exists():
        raise SystemExit(f'No existe {path}. Créalo con los cinco valores GARAGE_S3_* (ver docs/garage-photo-bucket-proposal.md).')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise SystemExit(f'{path} debe ser un archivo sólo legible por su dueño (chmod 600).')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        if name in KEYS:
            values[name] = value.strip('"\'')
    missing = [name for name in KEYS if not values.get(name)]
    if missing:
        raise SystemExit('Faltan variables: ' + ', '.join(missing))
    return values


def synthetic_photo(seed):
    image = Image.new('RGB', (2400, 1600), (40 * seed % 256, 120, 200))
    ImageDraw.Draw(image).ellipse((300 * seed, 200, 300 * seed + 900, 1100), fill=(250, 170, 30))
    source = BytesIO()
    image.save(source, format='PNG')
    source.seek(0)
    return process_photo(source)


def http_get(url):
    """Plain unauthenticated HTTPS GET. Returns (status, body); never exposes the URL."""
    try:
        with urlopen(Request(url, method='GET'), timeout=15) as response:
            return response.status, response.read(16 * 1024 * 1024)
    except HTTPError as error:
        return error.code, b''


def tampered(url):
    parts = urlsplit(url)
    query = [(name, (value[:-1] + ('0' if value[-1] != '0' else '1')) if name == 'X-Amz-Signature' else value)
             for name, value in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(query)))


class Report:
    def __init__(self):
        self.failures = 0

    def step(self, name, ok, detail=''):
        self.failures += not ok
        print(f"{'OK   ' if ok else 'FALLO'} {name}{' — ' + detail if detail else ''}", flush=True)


def missing(storage, key):
    try:
        storage.read(key)
    except PhotoStorageError as error:
        return error.code == 'photo_storage_missing'
    return False


def run(values, report):
    config = PhotoStorageConfig.from_environment(values)
    writer, reader = PrivatePhotoStorage(config), PrivatePhotoStorage(config)
    created = []
    try:
        first, second = synthetic_photo(1), synthetic_photo(2)
        report.step('imagen sintética procesada (WebP, lado mayor 2000 px)',
                    first.content_type == 'image/webp' and max(first.width, first.height) == 2000)

        key = new_photo_key()
        created.append(key)
        uploaded = writer.upload(first, key=key)
        report.step('subida con el cliente A', uploaded.size_bytes == len(first.data))

        data = reader.read(key)
        report.step('lectura desde un cliente B independiente (bytes y SHA-256 idénticos)',
                    hashlib.sha256(data).hexdigest() == uploaded.sha256 and reader.size(key) == uploaded.size_bytes)

        anonymous = f"{values['GARAGE_S3_ENDPOINT_URL'].rstrip('/')}/{quote(values['GARAGE_S3_BUCKET'])}/{quote(key)}"
        status, body = http_get(anonymous)
        report.step('lectura anónima denegada', status in DENIED and uploaded.sha256 != hashlib.sha256(body).hexdigest(),
                    f'HTTP {status}' + ('' if status in DENIED else ' (se esperaba 401/403)'))

        status, body = http_get(writer.signed_download_url(key, expires_seconds=60))
        report.step('enlace firmado de 60 s devuelve la misma imagen',
                    status == 200 and hashlib.sha256(body).hexdigest() == uploaded.sha256, f'HTTP {status}')

        status, _ = http_get(tampered(writer.signed_download_url(key, expires_seconds=60)))
        report.step('enlace con firma alterada denegado', status in DENIED, f'HTTP {status}')

        expiring = writer.signed_download_url(key, expires_seconds=1)
        time.sleep(3)
        status, _ = http_get(expiring)
        report.step('enlace firmado caducado denegado', status in DENIED, f'HTTP {status}')

        replacement = new_photo_key()
        created.append(replacement)
        writer.upload(second, key=replacement)
        writer.delete(key)
        report.step('sustitución: la nueva se lee y la anterior ya no existe',
                    hashlib.sha256(reader.read(replacement)).hexdigest() == hashlib.sha256(second.data).hexdigest()
                    and missing(reader, key))

        wrong = PrivatePhotoStorage(PhotoStorageConfig.from_environment(
            dict(values, GARAGE_S3_SECRET_ACCESS_KEY=values['GARAGE_S3_SECRET_ACCESS_KEY'] + 'x')))
        try:
            wrong.read(replacement)
            report.step('credencial incorrecta rechazada', False, 'la lectura no falló')
        except PhotoStorageError as error:
            message = str(error)
            leaked = [name for name in KEYS if values[name] in message]
            report.step('credencial incorrecta rechazada con error saneado', not leaked, f'código {error.code}')
        finally:
            wrong.close()
    finally:
        for key in created:
            try:
                writer.delete(key)
            except PhotoStorageError as error:
                report.step('limpieza de un objeto de la prueba', False, f'código {error.code}')
        report.step('limpieza: los objetos de la prueba ya no existen', all(missing(reader, key) for key in created))
        writer.close()
        reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--env-file', type=Path, default=DEFAULT_ENV_FILE)
    arguments = parser.parse_args()
    values = load_values(arguments.env_file.expanduser())
    report = Report()
    try:
        run(values, report)
    except Exception as error:  # Never print tracebacks: they could carry endpoints or signed URLs.
        code = getattr(error, 'code', '')
        report.step('ejecución interrumpida', False, type(error).__name__ + (f' ({code})' if isinstance(code, str) and code else ''))
    print('RESULTADO:', 'todo OK' if not report.failures else f'{report.failures} fallo(s)')
    return 0 if not report.failures else 1


if __name__ == '__main__':
    sys.exit(main())
