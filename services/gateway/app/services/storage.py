"""S3-compatible object storage for uploaded documents.

Local hostPath volumes were fine for single-node dev; the moment we
go multi-node (Kubernetes with > 1 gateway replica, or a real
production cluster) every uploaded image has to live somewhere all
nodes can read. S3 (or any S3-API-compatible store like MinIO,
Wasabi, Backblaze B2) is the boring correct answer.

This module provides a tiny async wrapper around aioboto3 with the
two operations the rest of the gateway needs:

    storage_key = await put_upload(case_id, doc_id, content, content_type)
    bytes_iter  = stream_upload(storage_key)
    presigned   = await presigned_get_url(storage_key, expires_in=300)
    await delete_upload(storage_key)

`storage_key` is the S3 object key. We persist it on the Document
row alongside file_path; legacy reads fall back to file_path when
the key is empty (transitional period — every new upload writes
both).

Configuration via env (all optional in dev — MinIO defaults work):

  STORAGE_S3_ENDPOINT_URL   http://minio:9000   (compose) /
                            https://s3.<region>.amazonaws.com (prod)
  STORAGE_S3_BUCKET         docflow-uploads
  STORAGE_S3_REGION         us-east-1
  STORAGE_S3_ACCESS_KEY     minioadmin / IAM access key
  STORAGE_S3_SECRET_KEY     minioadmin / IAM secret
  STORAGE_S3_FORCE_PATH_STYLE  true  (required for MinIO; false for AWS)

Production should use IAM instance profiles instead of long-lived
keys; aioboto3 picks those up via the standard AWS credential chain
when STORAGE_S3_ACCESS_KEY is unset.
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import aioboto3
from botocore.client import Config

logger = logging.getLogger(__name__)


def _bucket() -> str:
    return os.environ.get("STORAGE_S3_BUCKET", "docflow-uploads")


def _endpoint_url() -> str | None:
    # AWS S3 ignores this; MinIO + other compatibles need it.
    return os.environ.get("STORAGE_S3_ENDPOINT_URL") or None


def _client_kwargs() -> dict:
    """aioboto3 client kwargs assembled from env."""
    kwargs: dict = {
        "region_name": os.environ.get("STORAGE_S3_REGION", "us-east-1"),
    }
    access = os.environ.get("STORAGE_S3_ACCESS_KEY")
    secret = os.environ.get("STORAGE_S3_SECRET_KEY")
    if access and secret:
        kwargs["aws_access_key_id"] = access
        kwargs["aws_secret_access_key"] = secret
    endpoint = _endpoint_url()
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    # MinIO + most S3-compatible stores require path-style addressing
    # (bucket in the URL path rather than the subdomain). AWS supports
    # both but defaults to virtual-host style; force path-style
    # uniformly so the same code talks to both.
    force_path_style = os.environ.get("STORAGE_S3_FORCE_PATH_STYLE", "true").lower() in (
        "1", "true", "yes",
    )
    kwargs["config"] = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if force_path_style else "auto"},
    )
    return kwargs


_session = aioboto3.Session()


def build_storage_key(case_id: str, doc_id: str, ext: str) -> str:
    """Canonical key shape: case/<case_id>/<doc_id><ext>.

    Grouping by case_id makes lifecycle policies and case-deletion
    cleanups (one-shot delete-by-prefix) trivial; the doc_id keeps
    keys unique inside a case.
    """
    return f"case/{case_id}/{doc_id}{ext}"


async def put_upload(
    *, case_id: str, doc_id: str, ext: str, content: bytes, content_type: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """Upload bytes to S3, return the object key. Idempotent — uploading
    the same key twice overwrites; we never reuse keys (UUIDed doc_id)
    so this is fine."""
    key = build_storage_key(case_id, doc_id, ext)
    extra_args: dict = {
        "ContentType": content_type,
    }
    # AWS S3 supports SSE-S3 (AES256) natively; MinIO requires KMS
    # configured first and rejects the call otherwise. Make SSE
    # opt-in via STORAGE_S3_SSE so dev-with-MinIO works out of the
    # box and prod-with-real-S3 sets STORAGE_S3_SSE=AES256 (or aws:kms).
    sse = os.environ.get("STORAGE_S3_SSE", "").strip()
    if sse:
        extra_args["ServerSideEncryption"] = sse
    if metadata:
        # S3 metadata keys must be ASCII; sanitize defensively.
        extra_args["Metadata"] = {
            k: str(v) for k, v in metadata.items() if k.isascii()
        }
    async with _session.client("s3", **_client_kwargs()) as s3:
        await s3.put_object(
            Bucket=_bucket(),
            Key=key,
            Body=content,
            **extra_args,
        )
    return key


async def stream_upload(storage_key: str) -> AsyncIterator[bytes]:
    """Async iterator over the object's bytes — feed straight into a
    StreamingResponse from FastAPI."""
    async with _session.client("s3", **_client_kwargs()) as s3:
        resp = await s3.get_object(Bucket=_bucket(), Key=storage_key)
        async for chunk in resp["Body"].iter_chunks(chunk_size=64 * 1024):
            yield chunk


async def fetch_upload(storage_key: str) -> bytes:
    """Read the entire object into memory. Used by OCR / face when
    they need a single buffer."""
    async with _session.client("s3", **_client_kwargs()) as s3:
        resp = await s3.get_object(Bucket=_bucket(), Key=storage_key)
        return await resp["Body"].read()


async def presigned_get_url(storage_key: str, *, expires_in: int = 300) -> str:
    """Time-limited download URL — used so OCR / face services can
    fetch directly from S3 without sharing AWS credentials."""
    async with _session.client("s3", **_client_kwargs()) as s3:
        return await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": storage_key},
            ExpiresIn=expires_in,
        )


async def delete_upload(storage_key: str) -> None:
    async with _session.client("s3", **_client_kwargs()) as s3:
        await s3.delete_object(Bucket=_bucket(), Key=storage_key)


async def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist. Safe to call on every
    boot — the head_bucket / create_bucket dance is idempotent. Used
    for dev convenience; production MinIO/S3 buckets are typically
    provisioned via Terraform / CloudFormation, not at app startup."""
    bucket = _bucket()
    async with _session.client("s3", **_client_kwargs()) as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
            return
        except Exception:
            pass
        try:
            await s3.create_bucket(Bucket=bucket)
            logger.info("Created S3 bucket %s on first boot", bucket)
        except Exception as exc:
            logger.warning("ensure_bucket(%s) failed: %s", bucket, exc)
