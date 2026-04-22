"""
Shared HTTP/TLS settings for ingestion connectors.

Some government sites send an incomplete TLS certificate chain; OpenSSL then
reports "unable to get local issuer certificate" even with certifi or Debian
CA bundles. Mitigations (in order):

  1. Optional INGEST_TLS_SKIP_VERIFY_HOST_SUFFIXES — comma-separated host
     suffixes (e.g. dof.gob.mx) for verify=False on those hosts only. Use only
     when the remote chain is broken and you accept the risk.

  2. truststore — uses the platform trust store (helps on macOS/Windows; on
     Linux it still uses OpenSSL + system roots).

  3. Explicit CA file: SSL_CERT_FILE env, then /etc/ssl/certs/ca-certificates.crt,
     then certifi.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _host_tls_skip_verify(host: str) -> bool:
    host = host.lower().strip(".")
    if not host:
        return False
    from app.config import get_settings

    raw = (get_settings().INGEST_TLS_SKIP_VERIFY_HOST_SUFFIXES or "").strip()
    if not raw:
        return False
    for part in raw.split(","):
        suffix = part.strip().lower().strip(".")
        if not suffix:
            continue
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def httpx_verify(url: Optional[str] = None) -> Union[bool, str, ssl.SSLContext]:
    """
    Return the ``verify`` argument for ``httpx.AsyncClient``.

    If *url* is given and its host matches INGEST_TLS_SKIP_VERIFY_HOST_SUFFIXES,
    returns False (no certificate verification) and logs a warning.
    """
    if url:
        try:
            hostname = urlparse(url).hostname
            if hostname and _host_tls_skip_verify(hostname):
                logger.warning(
                    "TLS verify disabled for host %s (INGEST_TLS_SKIP_VERIFY_HOST_SUFFIXES)",
                    hostname,
                )
                return False
        except Exception:
            pass

    try:
        import truststore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return ctx
    except ImportError:
        pass

    cafile = os.environ.get("SSL_CERT_FILE", "").strip()
    if cafile and os.path.isfile(cafile):
        try:
            return ssl.create_default_context(cafile=cafile)
        except ssl.SSLError:
            pass

    debian_ca = "/etc/ssl/certs/ca-certificates.crt"
    if os.path.isfile(debian_ca):
        try:
            return ssl.create_default_context(cafile=debian_ca)
        except ssl.SSLError:
            pass

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return True
