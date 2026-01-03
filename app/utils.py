import datetime as dt
import hmac
import json
import secrets
from hashlib import sha256
from typing import Optional

from fastapi import HTTPException, status

from .config import settings


def validate_telegram_webapp_data(init_data: str, bot_token: str) -> dict:
    """Validate Telegram WebApp initData hash."""
    from urllib.parse import parse_qsl

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_value = data.pop("hash", None)
    if not hash_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid initData")

    payload = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = sha256(f"WebAppData{bot_token}".encode()).digest()
    calculated = hmac.new(secret, payload.encode(), sha256).hexdigest()

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
    return f"https://{settings.domain}/{slug}#1VPN"


def new_slug() -> str:
    return secrets.token_urlsafe(6)


def ensure_admin(secret: str):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
