"""Media storage.

Voice notes and order photos are the demo, and Cloud Run's disk is per-instance
and ephemeral — a file written during ingestion is gone by the time the owner
taps it. So GCS is the real path, and local disk exists only so that
`uvicorn app.main:app --reload` works without cloud credentials.

Which one runs is decided by `GCS_BUCKET` being set, not by an env name: a
developer with a bucket gets GCS, and a demo laptop without one still works.
"""

from __future__ import annotations

import mimetypes
import uuid
from functools import lru_cache
from pathlib import Path

from app.config import settings


@lru_cache
def _bucket():
    """Cached: the client opens a connection pool and reads credentials."""
    from google.cloud import storage

    return storage.Client().bucket(settings().gcs_bucket)


def _content_type(filename: str) -> str:
    guess, _ = mimetypes.guess_type(filename)
    if guess:
        return guess
    # WhatsApp voice notes are .opus, which mimetypes does not know about.
    if filename.lower().endswith(".opus"):
        return "audio/ogg"
    return "application/octet-stream"


def _key(tenant_id: uuid.UUID | str, filename: str) -> str:
    """Tenant-prefixed so a bucket-level listing can never mix two businesses."""
    safe = Path(filename).name or "file"
    return f"{tenant_id}/{uuid.uuid4().hex[:8]}-{safe}"


def store_media(tenant_id: uuid.UUID | str, filename: str, blob: bytes) -> str:
    """Persist a media file and return the URI the rest of the system uses.

    `gs://bucket/tenant/name` when a bucket is configured, a `file://` URI
    otherwise. Nothing downstream should care which.
    """
    key = _key(tenant_id, filename)
    bucket_name = settings().gcs_bucket

    if not bucket_name:
        target = Path(settings().upload_dir) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        return target.resolve().as_uri()

    gcs_blob = _bucket().blob(key)
    gcs_blob.upload_from_string(blob, content_type=_content_type(filename))
    return f"gs://{bucket_name}/{key}"


def read_media(uri: str) -> bytes:
    """Read back what store_media wrote, from either backend.

    Used by the screens that show an attachment. It reads through the service
    account rather than minting a signed or public URL: a photograph of
    somebody's ledger should not be fetchable by anyone who ends up with the
    link, and a URL that works without a token is a link that will eventually
    be forwarded.
    """
    if uri.startswith("gs://"):
        _, _, rest = uri.partition("gs://")
        bucket_name, _, key = rest.partition("/")
        from google.cloud import storage as gcs

        client = gcs.Client()
        return client.bucket(bucket_name).blob(key).download_as_bytes()

    if uri.startswith("file://"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        return Path(url2pathname(urlparse(uri).path)).read_bytes()

    raise ValueError(f"Unsupported media URI: {uri[:32]}")
