"""Bounded, decoded user reference images; IDs never authorize caller paths.

Only normalized PNG pixels are retained. A reference image is a user's visual
input, not a verified CAD dimension or a manufacturing specification.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import threading
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import read_json, write_json

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = 12 * 1024 * 1024
MAX_IMAGES = 6
MAX_PIXELS = 20_000_000
MAX_EDGE = 4096
_MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
_PUBLIC_KEYS = ("id", "name", "mime_type", "width", "height", "size_bytes", "sha256", "url")
_UPLOAD_LOCK = threading.Lock()


def _directory(store: Path, *, create: bool = False) -> Path:
    root = Path(store).resolve()
    directory = (root / "reference-images").resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Reference image store is outside the application store")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _image_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Unknown reference image ID")
    return value


def _name(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("A reference image filename is required")
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    basename = "".join(character for character in basename if ord(character) >= 32 and ord(character) != 127).strip()
    return basename[:120] if basename and basename not in {".", ".."} else "reference.png"


def public_reference(record: dict) -> dict:
    """The browser receives metadata and an ID URL, never a filesystem path."""
    return {key: record[key] for key in _PUBLIC_KEYS}


def _normalize(data_url: str) -> tuple[bytes, int, int]:
    if not isinstance(data_url, str) or len(data_url) > ((MAX_SOURCE_BYTES + 2) // 3) * 4 + 64:
        raise ValueError("Each reference image must be at most 8 MiB")
    header, separator, encoded = data_url.partition(",")
    if not separator or not header.startswith("data:") or not header.endswith(";base64"):
        raise ValueError("A base64 PNG, JPEG or WebP image is required")
    mime_type = header[5:-7]
    if mime_type not in _MIME_FORMATS:
        raise ValueError("Only PNG, JPEG and WebP reference images are supported")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Invalid base64 reference image") from error
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Each reference image must be nonempty and at most 8 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != _MIME_FORMATS[mime_type]:
                    raise ValueError("Reference image content does not match its declared format")
                if getattr(source, "n_frames", 1) != 1 or getattr(source, "is_animated", False):
                    raise ValueError("Animated and multiframe reference images are not supported")
                if source.width <= 0 or source.height <= 0 or source.width * source.height > MAX_PIXELS:
                    raise ValueError("Reference images may contain at most 20 million pixels")
                source.load()  # Decode all pixels; a filename or image header is insufficient.
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
                pixels = oriented.convert(mode)
                if max(pixels.size) > MAX_EDGE:
                    pixels.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)
                output = BytesIO()
                clean.save(output, format="PNG", compress_level=6)
                return output.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Reference image cannot be safely decoded") from error


def _read_reference(store: Path, image_id: str) -> tuple[dict, bytes]:
    image_id = _image_id(image_id)
    directory = _directory(store)
    image_path = (directory / f"{image_id}.png").resolve()
    metadata_path = (directory / f"{image_id}.meta.json").resolve()
    if not image_path.is_relative_to(directory) or not metadata_path.is_relative_to(directory):
        raise ValueError("Reference image path is outside its registered directory")
    try:
        metadata = read_json(metadata_path)
        if (not isinstance(metadata, dict) or set(metadata) != set(_PUBLIC_KEYS)
                or metadata.get("id") != image_id or metadata.get("sha256") != image_id
                or metadata.get("mime_type") != "image/png"
                or metadata.get("url") != f"/api/reference-images/{image_id}"
                or not isinstance(metadata.get("name"), str) or _name(metadata["name"]) != metadata["name"]):
            raise ValueError("Reference image registration is invalid")
        for key in ("width", "height", "size_bytes"):
            if type(metadata.get(key)) is not int or metadata[key] <= 0:
                raise ValueError("Reference image registration has invalid dimensions or size")
        if (max(metadata["width"], metadata["height"]) > MAX_EDGE
                or metadata["width"] * metadata["height"] > MAX_PIXELS):
            raise ValueError("Reference image dimensions exceed the allowed limits")
        raw = image_path.read_bytes()
        if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != image_id:
            raise ValueError("Reference image changed after upload")
        with Image.open(BytesIO(raw)) as image:
            if (image.format != "PNG" or image.mode not in {"RGB", "RGBA"}
                    or image.size != (metadata["width"], metadata["height"])
                    or getattr(image, "n_frames", 1) != 1 or image.info):
                raise ValueError("Registered reference image is not a normalized PNG")
            image.load()
        return {**metadata, "path": str(image_path)}, raw
    except (OSError, KeyError, TypeError, UnidentifiedImageError) as error:
        raise ValueError("Reference image is missing or its registration is invalid") from error


def save_reference_image(store: Path, name: str, data_url: str) -> dict:
    """Decode one user upload, normalize its pixels, and register a durable ID."""
    name = _name(name)
    data, width, height = _normalize(data_url)
    image_id = hashlib.sha256(data).hexdigest()
    with _UPLOAD_LOCK:
        directory = _directory(store, create=True)
        image_path = directory / f"{image_id}.png"
        metadata_path = directory / f"{image_id}.meta.json"
        if metadata_path.exists():
            record, _ = _read_reference(store, image_id)
            return record
        metadata = dict(id=image_id, name=name, mime_type="image/png", width=width, height=height,
                        size_bytes=len(data), sha256=image_id, url=f"/api/reference-images/{image_id}")
        if image_path.exists():
            # A prior image commit can outlive a failed metadata commit. Repair
            # only the exact canonical bytes from this validated retry; never
            # replace a changed file or an existing registration.
            if image_path.is_symlink() or not image_path.is_file() or image_path.read_bytes() != data:
                raise ValueError("Unregistered reference image does not match this upload")
            write_json(metadata_path, metadata)
            return _read_reference(store, image_id)[0]
        descriptor, temporary = tempfile.mkstemp(prefix="reference-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, image_path)
            write_json(metadata_path, metadata)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {**metadata, "path": str(image_path.resolve())}


def get_reference_images(store: Path, ids: list[str]) -> list[dict]:
    """Resolve only registered IDs, rechecking file bytes on every request."""
    if not isinstance(ids, list) or len(ids) > MAX_IMAGES:
        raise ValueError("At most 6 reference images may accompany one request")
    if len(set(_image_id(image_id) for image_id in ids)) != len(ids):
        raise ValueError("Duplicate reference image IDs are not allowed")
    return [_read_reference(store, image_id)[0] for image_id in ids]


def read_reference_image(store: Path, image_id: str) -> tuple[dict, bytes]:
    """Return the exact bytes verified for an HTTP image response."""
    return _read_reference(store, image_id)
