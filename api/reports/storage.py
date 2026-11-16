"""Where approved report PDFs live.

Deployed environments set REPORTS_BUCKET and the files go to a private,
encrypted S3 bucket. Without it (local development, tests) they go to
REPORTS_LOCAL_DIR on disk. Customers never get a storage URL: downloads
are streamed through the portal API, which re-checks the caller's
organization on every request.
"""

from __future__ import annotations

from pathlib import Path

import boto3
from django.conf import settings


def _local_path(key: str) -> Path:
    root = Path(settings.REPORTS_LOCAL_DIR).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("storage key escapes the reports directory")
    return path


def _s3():
    # Same region as the rest of the stack; None lets boto3 use its default.
    return boto3.client("s3", region_name=settings.COGNITO_REGION or None)


def put(key: str, data: bytes, content_type: str = "application/pdf") -> None:
    if settings.REPORTS_BUCKET:
        _s3().put_object(
            Bucket=settings.REPORTS_BUCKET, Key=key, Body=data, ContentType=content_type
        )
        return
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get(key: str) -> bytes:
    if settings.REPORTS_BUCKET:
        return _s3().get_object(Bucket=settings.REPORTS_BUCKET, Key=key)["Body"].read()
    return _local_path(key).read_bytes()
