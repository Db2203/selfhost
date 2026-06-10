"""HMAC-signed, expiring URLs for image bytes.

Browsers can't send an Authorization header from an <img> tag, so the asset
list (which does require auth) embeds presigned URLs instead. A signature
covers asset id + variant + expiry; tampering with any of them kills it.
"""

import hashlib
import hmac
import time
import uuid

from app.config import get_settings


def _signature(asset_id: str, variant: str, expires: int) -> str:
    payload = f"{asset_id}:{variant}:{expires}".encode()
    return hmac.new(get_settings().secret_key.encode(), payload, hashlib.sha256).hexdigest()


def sign_asset_url(asset_id: uuid.UUID, variant: str) -> str:
    expires = int(time.time()) + get_settings().signed_url_ttl_minutes * 60
    sig = _signature(str(asset_id), variant, expires)
    return f"/assets/{asset_id}/file/{variant}?exp={expires}&sig={sig}"


def verify_asset_signature(asset_id: uuid.UUID, variant: str, expires: int, sig: str) -> bool:
    if expires < time.time():
        return False
    expected = _signature(str(asset_id), variant, expires)
    return hmac.compare_digest(expected, sig)
