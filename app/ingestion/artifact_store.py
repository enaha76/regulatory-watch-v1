"""
T2.9 — S3 Artifact Store

Stores raw HTML and extracted text in S3 under:
  artifacts/{source_type}/{YYYY-MM-DD}/{content_hash[:8]}_raw.html
  artifacts/{source_type}/{YYYY-MM-DD}/{content_hash[:8]}_text.txt

If AWS credentials are not configured, uploads are silently skipped.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _get_s3_client():
    """Return a boto3 S3 client, or None if boto3/credentials are unavailable."""
    try:
        import boto3  # type: ignore
        from app.config import get_settings
        settings = get_settings()
        if not settings.AWS_S3_BUCKET:
            return None, None
        client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
        return client, settings.AWS_S3_BUCKET
    except ImportError:
        return None, None
    except Exception as exc:
        logger.debug("S3 client unavailable: %s", exc)
        return None, None


def upload_artifacts(
    source_type: str,
    content_hash: str,
    raw_html: Optional[str] = None,
    extracted_text: Optional[str] = None,
) -> dict:
    """
    Upload raw HTML and/or extracted text to S3.

    Returns dict with S3 URIs:
      { "raw_html_uri": "s3://bucket/...", "extracted_text_uri": "s3://bucket/..." }
    or empty dict if S3 is not configured.
    """
    client, bucket = _get_s3_client()
    if not client:
        return {}

    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_key = f"artifacts/{source_type}/{date_prefix}/{content_hash[:8]}"
    uris = {}

    if raw_html:
        key = f"{base_key}_raw.html"
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=raw_html.encode("utf-8"),
                ContentType="text/html",
            )
            uris["raw_html_uri"] = f"s3://{bucket}/{key}"
            logger.debug("Uploaded raw HTML to %s", uris["raw_html_uri"])
        except Exception as exc:
            logger.warning("S3 upload failed for raw HTML: %s", exc)

    if extracted_text:
        key = f"{base_key}_text.txt"
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=extracted_text.encode("utf-8"),
                ContentType="text/plain",
            )
            uris["extracted_text_uri"] = f"s3://{bucket}/{key}"
            logger.debug("Uploaded extracted text to %s", uris["extracted_text_uri"])
        except Exception as exc:
            logger.warning("S3 upload failed for extracted text: %s", exc)

    return uris
