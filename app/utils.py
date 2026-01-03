import datetime as dt
import datetime as dt
import hmac
import json
import secrets
from hashlib import sha256
from typing import Optional

from fastapi import HTTPException, status
from itsdangerous import BadSignature, TimestampSigner

from .config import settings


def validate_telegram_webapp_data(init_data: str, bot_token: str) -> dict:
    """Validate Telegram WebApp initData hash."""
    from urllib.parse import parse_qsl

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_value = data.pop("hash", None)
    if not hash_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid initData")

    payload = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), sha256).digest()
    calculated = hmac.new(secret_key, payload.encode(), sha256).hexdigest()

    if not hmac.compare_digest(calculated, hash_value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad initData hash")

    try:
        user = json.loads(data["user"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user") from exc

    return user


def now_utc() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)


def make_wireguard_link(slug: str) -> str:
    if slug.startswith("http://") or slug.startswith("https://"):
        return slug
    return f"https://{settings.domain}/{slug}#1VPN"


def new_slug() -> str:
    return secrets.token_urlsafe(6)


def ensure_admin(secret: str):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


def make_admin_ui_signer() -> TimestampSigner:
    return TimestampSigner(settings.admin_secret or "admin-ui")


def create_admin_ui_token(username: str) -> str:
    return make_admin_ui_signer().sign(username).decode()


def verify_admin_ui_token(token: str) -> str:
    try:
        return make_admin_ui_signer().unsign(token, max_age=60 * 60 * 12).decode()
    except BadSignature as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token") from exc
