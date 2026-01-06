import asyncio
import math
import uuid
from datetime import timedelta, datetime, timezone
from typing import Optional

import aiohttp
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, HTMLResponse

from fastapi.staticfiles import StaticFiles

from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession



from . import models

from .bot import bot, dp, webapp_keyboard
from aiogram import types

from .config import settings

from .database import Base, engine, get_session, AsyncSessionLocal

from .schemas import (
    AdminBalance,
    AdminBan,
    AdminBroadcast,
    AdminBroadcastPhoto,
    AdminBalanceAdjust,
    AdminUserLookup,
    AdminServer,
    AdminServerDelete,
    AdminServerUpdate,
    AdminTariff,
    AdminCredUpdate,
    AdminLogin,
    AdminPrice,
    AdminMarzbanServer,
    AdminMarzbanServerDelete,
    AdminRemSquad,
    AdminRemSquadUpdate,
    AdminRemSquadDelete,
    DeviceRequest,
    PaymentRequest,
    SubscriptionRequest,
    TariffOut,
    UserState,
    MarzbanServerOut,
)
from .utils import create_admin_ui_token, make_wireguard_link, new_slug, now_utc, validate_telegram_webapp_data, verify_admin_ui_token


async def get_price(session: AsyncSession) -> float:
    setting = await session.get(models.AppSetting, "price_per_day")
    if setting:
        try:
            return float(setting.value)
        except ValueError:
            return settings.price_per_day
    # если нет записи — вернуть значение из env, но не создавать принудительно
    return settings.price_per_day


async def set_price(session: AsyncSession, value: float) -> float:
    setting = await session.get(models.AppSetting, "price_per_day")
    if setting:
        setting.value = str(value)
    else:
        session.add(models.AppSetting(key="price_per_day", value=str(value)))
    await session.commit()
    return value


def get_rem_config() -> tuple[str, str, str]:
    if not settings.rem_base_url or not settings.rem_api_token:
        raise HTTPException(status_code=503, detail="Remnawave API is not configured")
    base = settings.rem_base_url.rstrip("/")
    # Если передан URL с /api на конце — убираем, чтобы не было /api/api/...
    if base.lower().endswith("/api"):
        base = base[:-4]
    base_api = f"{base}/api"
    return base, base_api, settings.rem_api_token


async def pick_rem_squad(session: AsyncSession) -> Optional[models.RemSquad]:
    squads = list((await session.scalars(select(models.RemSquad))).all())
    if not squads:
        return None
    for squad in squads:
        used = await session.scalar(select(func.count(models.RemUser.id)).where(models.RemUser.squad_id == squad.id))
        if (used or 0) < squad.capacity:
            return squad
    return None


async def check_subscription(user: models.User) -> bool:
    if not settings.required_channel:
        return True
    channel = settings.required_channel.strip()
    # normalize: https://t.me/xxx -> xxx, t.me/xxx -> xxx, add @ if missing for usernames
    if channel.startswith("https://"):
        channel = channel.split("/")[-1]
    if channel.startswith("t.me/"):
        channel = channel.split("/")[-1]
    if channel and channel[0].isalpha() and not channel.startswith("@") and not channel.startswith("-100"):
        channel = f"@{channel}"
    try:
        member = await bot.get_chat_member(channel, int(user.telegram_id))
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False


async def rem_disable_user(panel_uuid: str) -> None:
    if not panel_uuid:
        return
    base_url, base_api, token = get_rem_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base_api}/users/{panel_uuid}/actions/disable", headers=headers) as resp:
            return


async def rem_enable_user(panel_uuid: str) -> None:
    if not panel_uuid:
        return
    base_url, base_api, token = get_rem_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base_api}/users/{panel_uuid}/actions/enable", headers=headers) as resp:
            return


async def recalc_subscription(session: AsyncSession, user: models.User) -> dict:
    devices_count = await session.scalar(
        select(func.count(models.Device.id)).where(models.Device.user_id == user.id)
    ) or 0
    device_count = max(devices_count, 1)
    price_value = await get_price(session)
    cost = price_value * device_count if price_value else 0
    link_value = ""
    estimated_days = 0
    rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
    panel_uuid_current = rem_user.panel_uuid if rem_user else ""
    short_uuid_current = rem_user.short_uuid if rem_user else ""
    prev_suspended = user.link_suspended
    prev_days = None
    if user.subscription_end:
        sub_end = user.subscription_end
        if sub_end.tzinfo is None:
            sub_end = sub_end.replace(tzinfo=timezone.utc)
            user.subscription_end = sub_end
        delta = sub_end - now_utc()
        prev_days = math.ceil(delta.total_seconds() / 86400)

    # Если пользователь забанен — сразу блокируем доступ и выходим
    if user.banned:
        user.subscription_end = None
        user.allowed_devices = device_count
        user.link_suspended = True
        try:
            current_uuid = panel_uuid_current or short_uuid_current
            if current_uuid:
                await rem_disable_user(current_uuid)
        except Exception:
            pass
        await session.commit()
        return {
            "link": "",
            "link_suspended": True,
            "allowed_devices": device_count,
            "estimated_days": 0,
        }

    if cost > 0:
        estimated_days = int(user.balance / cost)

    if estimated_days <= 0:
        user.subscription_end = None
        user.allowed_devices = device_count
        user.link_suspended = True
        expires_at = now_utc()
        try:
            panel_uuid, short_uuid, _ = await rem_upsert_user(session, user, device_count, expires_at)
            rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
            current_uuid = panel_uuid or (rem_user.panel_uuid if rem_user else "") or panel_uuid_current
            if not current_uuid:
                current_uuid = short_uuid or (rem_user.short_uuid if rem_user else "") or short_uuid_current
            await rem_disable_user(current_uuid)
        except Exception:
            pass
        # уведомление о паузе подписки
        if user.telegram_id and not prev_suspended and (user.balance > 0 or prev_days is not None):
            try:
                await bot.send_message(
                    int(user.telegram_id),
                    "Подписка приостановлена — баланс закончился. Пополните баланс, чтобы возобновить.",
                    reply_markup=webapp_keyboard(),
                )
            except Exception:
                pass
    else:
        expires_at = now_utc() + timedelta(days=estimated_days)
        user.subscription_end = expires_at
        user.allowed_devices = device_count
        user.link_suspended = False
        try:
            panel_uuid, short_uuid, sub_url = await rem_upsert_user(session, user, device_count, expires_at)
            rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
            current_uuid = panel_uuid or (rem_user.panel_uuid if rem_user else "") or panel_uuid_current
            if not current_uuid:
                current_uuid = short_uuid or (rem_user.short_uuid if rem_user else "") or short_uuid_current
            await rem_enable_user(current_uuid)
            if sub_url:
                link_value = sub_url
            elif rem_user and rem_user.subscription_url:
                link_value = rem_user.subscription_url
        except Exception:
            user.link_suspended = True
            link_value = ""
        # уведомление о скором окончании
        if user.telegram_id and 0 < estimated_days <= 3 and user.balance > 0 and prev_days is not None:
            send_warn = True
            if prev_days is not None and prev_days <= 3:
                send_warn = False
            if send_warn:
                try:
                    await bot.send_message(
                        int(user.telegram_id),
                        "У вас осталось менее 3 дней подписки. Пополните баланс, чтобы продолжить.",
                        reply_markup=webapp_keyboard(),
                    )
                except Exception:
                    pass

    await session.commit()
    return {
        "link": link_value,
        "link_suspended": user.link_suspended,
        "allowed_devices": device_count,
        "estimated_days": estimated_days,
    }


async def rem_register_hwid(session: AsyncSession, user: models.User, device: models.Device) -> None:
    base_url, base_api, token = get_rem_config()
    rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
    if not rem_user or not rem_user.panel_uuid:
        return
    payload = {
        "hwid": device.fingerprint,
        "userUuid": rem_user.panel_uuid,
        "platform": "1VPN",
        "osVersion": "webapp",
        "deviceModel": device.label or "device",
        "userAgent": "1VPN-webapp",
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base_api}/hwid/devices", json=payload, headers=headers) as resp:
            if resp.status not in (200, 201, 204):
                return


async def rem_delete_hwid(session: AsyncSession, user: models.User, hwid: str) -> None:
    base_url, base_api, token = get_rem_config()
    rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
    if not rem_user or not rem_user.panel_uuid:
        return
    payload = {"userUuid": rem_user.panel_uuid, "hwid": hwid}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base_api}/hwid/devices/delete", json=payload, headers=headers) as resp:
            if resp.status not in (200, 201, 204):
                return


async def rem_upsert_user(
    session: AsyncSession, user: models.User, devices: int, expires_at: datetime
) -> tuple[str, Optional[str], Optional[str]]:
    base_url, base_api, token = get_rem_config()
    rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == user.id))
    squad = None
    if rem_user:
        squad = await session.get(models.RemSquad, rem_user.squad_id)
    if not squad:
        squad = await pick_rem_squad(session)
    if not squad:
        raise HTTPException(status_code=503, detail="Нет свободных Remnawave сквадов")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    expire_str = expires_at.astimezone(__import__("datetime").timezone.utc).isoformat(timespec="milliseconds")
    if expire_str.endswith("+00:00"):
        expire_str = expire_str[:-6] + "Z"
    payload = {
        "username": f"tg{user.telegram_id}",
        "expireAt": expire_str,
        "hwidDeviceLimit": devices,
        "activeInternalSquads": [squad.uuid],
        "telegramId": int(user.telegram_id) if str(user.telegram_id).isdigit() else None,
        "description": f"TG {user.telegram_id}",
    }

    async with aiohttp.ClientSession() as http:
        if rem_user and rem_user.panel_uuid:
            payload["uuid"] = rem_user.panel_uuid
            async with http.patch(f"{base_api}/users", json=payload, headers=headers) as resp:
                if resp.status not in (200, 201, 204):
                    detail = await resp.text()
                    raise HTTPException(status_code=503, detail=f"Remnawave update failed: {detail}")
                data = await resp.json()
        else:
            async with http.post(f"{base_api}/users", json=payload, headers=headers) as resp:
                if resp.status not in (200, 201, 204):
                    detail = await resp.text()
                    raise HTTPException(status_code=503, detail=f"Remnawave create failed: {detail}")
                data = await resp.json()

        response_data = data.get("response") if isinstance(data, dict) else {}
        user_payload = response_data
        if isinstance(response_data, dict) and "users" in response_data:
            users_list = response_data.get("users") or []
            if users_list:
                user_payload = users_list[0]

        panel_uuid = None
        short_uuid = None
        sub_url = None

        if isinstance(user_payload, dict):
            panel_uuid = user_payload.get("uuid") or user_payload.get("id")
            short_uuid = user_payload.get("shortUuid") or user_payload.get("subscriptionUuid")
            sub_url = user_payload.get("subscriptionUrl")
        if panel_uuid is None and rem_user:
            panel_uuid = rem_user.panel_uuid

        if rem_user:
            rem_user.panel_uuid = panel_uuid or rem_user.panel_uuid
            rem_user.short_uuid = short_uuid or rem_user.short_uuid
            rem_user.subscription_url = sub_url or rem_user.subscription_url
            rem_user.squad_id = squad.id
        else:
            rem_user = models.RemUser(
                user_id=user.id,
                squad_id=squad.id,
                panel_uuid=panel_uuid or "",
                short_uuid=short_uuid,
                subscription_url=sub_url,
            )
            session.add(rem_user)

        return panel_uuid or "", short_uuid, sub_url


async def bill_users_once() -> None:
    async with AsyncSessionLocal() as session:
        today = now_utc().date().isoformat()
        last = await session.get(models.AppSetting, "last_billed_date")
        if last and last.value == today:
            return

        price_value = await get_price(session)
        users = (await session.scalars(select(models.User))).all()
        for user in users:
            device_count = await session.scalar(
                select(func.count(models.Device.id)).where(models.Device.user_id == user.id)
            ) or 1
            cost = price_value * max(device_count, 1)
            if cost <= 0:
                continue
            if user.balance >= cost:
                user.balance -= cost
                days_left = int(user.balance / cost) + 1
                expires_at = now_utc() + timedelta(days=days_left)
                user.subscription_end = expires_at
                user.allowed_devices = device_count
                user.link_suspended = False
                try:
                    await rem_upsert_user(session, user, device_count, expires_at)
                except Exception:
                    user.link_suspended = True
            else:
                user.link_suspended = True
                user.subscription_end = None
                try:
                    await rem_upsert_user(session, user, device_count, now_utc())
                except Exception:
                    pass

        if last:
            last.value = today
        else:
            session.add(models.AppSetting(key="last_billed_date", value=today))
        await session.commit()


async def billing_loop():
    while True:
        try:
            await bill_users_once()
        except Exception:
            pass
        await asyncio.sleep(24 * 3600)


app = FastAPI(title="1VPN")

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)


# Hide internal error details
@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": "error"})



app.mount("/static", StaticFiles(directory="app/webapp"), name="static")





async def start_bot_polling():

    await dp.start_polling(bot)





@app.on_event("startup")

async def startup():

    async with engine.begin() as conn:

        await conn.run_sync(Base.metadata.create_all)

    # ensure admin credential exists

    async with AsyncSessionLocal() as session:

        cred = await session.scalar(select(models.AdminCredential).limit(1))

        if not cred:

            session.add(models.AdminCredential(username="admin", password="admin"))

            await session.commit()

    asyncio.create_task(start_bot_polling())
    asyncio.create_task(billing_loop())





@app.on_event("shutdown")

async def shutdown():

    await bot.session.close()





@app.get("/", response_class=HTMLResponse)

async def index():

    return FileResponse("app/webapp/index.html")





@app.get("/admin-ui", response_class=HTMLResponse)

async def admin_ui_page():

    return FileResponse("app/webapp/admin.html")





def payment_total(price: int, base_devices: int, requested_devices: int) -> int:

    per_device = price / max(base_devices, 1)

    return math.ceil(per_device * requested_devices)





async def pick_available_server(session: AsyncSession, current_user_id: Optional[int] = None) -> Optional[models.Server]:

    servers = list((await session.scalars(select(models.Server))).all())

    if not servers:

        return None

    for server in servers:

        if await server_has_capacity(session, server, current_user_id):

            return server

    return None





async def server_has_capacity(session: AsyncSession, server: models.Server, current_user_id: Optional[int] = None) -> bool:
    active_count = await session.scalar(

        select(func.count(models.User.id)).where(

            models.User.server_id == server.id,

            models.User.subscription_end.is_not(None),

            models.User.subscription_end > now_utc(),

        )

    )

    adjusted = (active_count or 0)

    if current_user_id:

        owns_slot = await session.scalar(

            select(func.count(models.User.id)).where(

                models.User.id == current_user_id,

                models.User.server_id == server.id,

                models.User.subscription_end.is_not(None),

                models.User.subscription_end > now_utc(),

            )

        )

        adjusted = max(0, adjusted - (owns_slot or 0))

    return adjusted < server.capacity


async def pick_marzban_server(session: AsyncSession) -> Optional[models.MarzbanServer]:
    try:
        servers = list((await session.scalars(select(models.MarzbanServer))).all())
    except Exception:
        return None
    if not servers:
        return None
    for server in servers:
        used = await session.scalar(
            select(func.count(models.MarzbanUser.id)).where(models.MarzbanUser.server_id == server.id)
        )
        if (used or 0) < server.capacity:
            return server
    return None


async def marzban_upsert_client(
    server: models.MarzbanServer, username: str, expires_at: Optional[datetime], max_devices: int
) -> str:
    """Создаёт или обновляет клиента на Marzban, возвращает subscription URL."""
    base = server.api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {server.api_token}", "Content-Type": "application/json"}
    payload = {
        "username": username,
        "expire": int(expires_at.timestamp()) if expires_at else None,
        "ips": max_devices,
    }
    async with aiohttp.ClientSession() as http:
        # Marzban API: создание/обновление через PUT /api/admin/users/{username}
        update_url = f"{base}/api/admin/users/{username}"
        async with http.put(update_url, json=payload, headers=headers) as resp:
            if resp.status not in (200, 201, 204):
                detail = await resp.text()
                raise HTTPException(status_code=503, detail=f"Marzban update failed: {detail}")
        sub_url = f"{base}/api/user/{username}/subscription"
        async with http.get(sub_url, headers=headers) as resp:
            if resp.status in (200, 201):
                try:
                    data = await resp.json()
                    return data.get("subscription_url") or data.get("url") or sub_url
                except Exception:
                    pass
        return sub_url


async def get_or_create_user(init_data: str, session: AsyncSession) -> models.User:

    tg_user = validate_telegram_webapp_data(init_data, settings.bot_token)

    tg_id = str(tg_user["id"])

    user = await session.scalar(select(models.User).where(models.User.telegram_id == tg_id))

    if user:

        return user
    user = models.User(

        telegram_id=tg_id,

        username=tg_user.get("username"),

        link_slug=new_slug(),

    )

    session.add(user)

    await session.commit()

    await session.refresh(user)

    return user





async def get_current_user(

    x_init_data: str = Header(..., alias="X-Telegram-Init"),

    session: AsyncSession = Depends(get_session),

) -> models.User:

    user = await get_or_create_user(x_init_data, session)

    if user.banned:

        raise HTTPException(status_code=403, detail="Вы заблокированы")

    return user





@app.get("/", response_class=HTMLResponse)

async def index():

    return FileResponse("app/webapp/index.html")





@app.post("/api/init")

async def init_user(

    request: Request,

    x_init: str | None = Header(None, alias="X-Telegram-Init"),

    session: AsyncSession = Depends(get_session),

):

    data = await request.json()

    init_data = data.get("initData") or x_init

    if not init_data:

        raise HTTPException(status_code=400, detail="initData required")

    user = await get_or_create_user(init_data, session)

    return {"ok": True, "link": ""}





@app.get("/api/gate")
async def gate(user: models.User = Depends(get_current_user)):
    subscribed = await check_subscription(user)
    channel = settings.required_channel or ""
    ch = channel.strip()
    if ch.startswith("https://"):
        ch = ch.split("/")[-1]
    if ch.startswith("t.me/"):
        ch = ch.split("/")[-1]
    if ch and ch[0].isalpha() and not ch.startswith("@") and not ch.startswith("-100"):
        ch = f"@{ch}"
    return {
        "subscribed": subscribed,
        "required_channel": ch,
        "policy_url": settings.policy_url,
    }


@app.get("/api/state", response_model=UserState)
async def state(user: models.User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not await check_subscription(user):
        raise HTTPException(status_code=403, detail="subscribe_required")
    tariffs = []
    devices = (
        await session.scalars(
            select(models.Device)
            .where(models.Device.user_id == user.id)
            .order_by(models.Device.id)
        )
    ).all()

    recalculated = await recalc_subscription(session, user)
    price_value = await get_price(session)
    server_data: Optional[dict] = None

    return UserState(
        balance=user.balance,
        subscription_end=user.subscription_end,
        allowed_devices=recalculated["allowed_devices"],
        link=recalculated["link"],
        server=server_data,
        devices=devices,
        tariffs=tariffs,
        banned=user.banned,
        link_suspended=recalculated["link_suspended"],
        ios_help_url=settings.ios_help_url,
        android_help_url=settings.android_help_url,
        support_url=f"https://t.me/{settings.support_username}",
        is_admin=settings.admin_tg_id == str(user.telegram_id),
        price_per_day=price_value,
        estimated_days=recalculated["estimated_days"],
    )

@app.post("/api/topup")

async def create_topup(

    payload: PaymentRequest,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    if payload.amount < 50:

        raise HTTPException(status_code=400, detail="Минимальная сумма 50?")



    provider = (payload.provider or "sbp").lower()
    payment = models.Payment(user_id=user.id, amount=payload.amount, status="pending", provider=provider)

    session.add(payment)

    await session.commit()

    await session.refresh(payment)



    # CryptoBot flow
    if provider == "crypto":
        if not settings.crypto_pay_token:
            raise HTTPException(status_code=400, detail="Crypto provider not configured")
        import aiohttp
        asset_amount = payload.amount
        if settings.crypto_rate and settings.crypto_rate > 0:
            asset_amount = round(payload.amount / settings.crypto_rate, 2)

        body = {
            "amount": f"{asset_amount:.2f}",
            "asset": settings.crypto_pay_asset or "USDT",
            "description": f"1VPN пополнение #{payment.id}",
            "payload": str(payment.id),
        }
        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    "https://pay.crypt.bot/api/createInvoice",
                    json=body,
                    headers={
                        "Crypto-Pay-API-Token": settings.crypto_pay_token,
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        raise HTTPException(status_code=500, detail="crypto_create_failed")
                    result = data.get("result") or {}
                    pay_url = result.get("pay_url")
                    invoice_id = result.get("invoice_id")
                    if not pay_url:
                        raise HTTPException(status_code=500, detail="crypto_create_failed")
                    payment.provider_payment_id = str(invoice_id or "")
                    await session.commit()
                    return {"confirmation_url": pay_url, "payment_id": payment.id}
        except HTTPException:
            await session.delete(payment)
            await session.commit()
            raise
        except Exception:
            await session.delete(payment)
            await session.commit()
            raise HTTPException(status_code=500, detail="crypto_create_failed")

    # YooKassa payment creation (SBP)
    try:
        from yookassa import Configuration, Payment
        from yookassa.domain.exceptions import ApiError

        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key
        amount_value = f"{payload.amount:.2f}"
        idem_key = str(uuid.uuid4())

        payment_response = Payment.create(
            {
                "amount": {"value": amount_value, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"{settings.webapp_url}?paid={payment.id}"},
                "capture": True,
                "payment_method_data": {"type": "sbp"},
                "description": f"1VPN пополнение #{payment.id}",
                "metadata": {"payment_id": payment.id},
            },
            idempotency_key=idem_key,
        )

        payment.provider_payment_id = payment_response.id

        await session.commit()

        return {"confirmation_url": payment_response.confirmation.confirmation_url, "payment_id": payment.id}

    except ApiError as e:
        await session.delete(payment)
        await session.commit()
        detail = (
            f"yookassa_error: {e}"
            f" | type: {getattr(e, 'type', None)}"
            f" | code: {getattr(e, 'code', None)}"
            f" | param: {getattr(e, 'parameter', None)}"
            f" | desc: {getattr(e, 'description', None)}"
            f" | idempotence: {getattr(e, 'idempotence_key', None)}"
        )
        resp_text = getattr(e, "response", None)
        if resp_text and hasattr(resp_text, "text"):
            detail += f" | resp: {resp_text.text}"
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        # вернуть понятную ошибку, чтобы увидеть причину в UI/логах
        await session.delete(payment)
        await session.commit()
        err_text = str(e)
        err_body = getattr(e, "body", None)
        err_resp = None
        try:
            err_resp = getattr(e, "response", None)
            if err_resp and hasattr(err_resp, "text"):
                err_resp = err_resp.text
        except Exception:
            err_resp = None
        err_args = getattr(e, "args", None)
        detail = f"yookassa_error: {err_text}"
        if err_body:
            detail += f" | body: {err_body}"
        if err_resp:
            detail += f" | resp: {err_resp}"
        if err_args:
            detail += f" | args: {err_args}"
        try:
            print(detail)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=detail)





@app.post("/api/subscription")

async def start_subscription(

    payload: SubscriptionRequest,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    tariff = await session.get(models.Tariff, payload.tariff_id)

    if not tariff:

        raise HTTPException(status_code=404, detail="Тариф не найден")



    total = payment_total(tariff.price, tariff.base_devices, payload.devices)

    if user.balance < total:

        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе")



    server = await session.get(models.Server, user.server_id) if user.server_id else None

    if server and not await server_has_capacity(session, server, user.id):

        server = None

    if not server:

        server = await pick_available_server(session, user.id)

    if not server:

        raise HTTPException(status_code=503, detail="Нет свободных серверов. Напишите в поддержку.")



    user.balance -= total

    user.allowed_devices = payload.devices

    user.server_id = server.id

    user.link_suspended = False

    now = now_utc()

    if user.subscription_end and user.subscription_end > now:

        user.subscription_end = user.subscription_end + timedelta(days=tariff.days)

    else:

        user.subscription_end = now + timedelta(days=tariff.days)



    await session.commit()

    await session.refresh(user)

    return {"ok": True, "subscription_end": user.subscription_end, "balance": user.balance}





@app.post("/api/device")

async def register_device(

    payload: DeviceRequest,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    existing = await session.scalar(

        select(models.Device).where(models.Device.user_id == user.id, models.Device.fingerprint == payload.fingerprint)

    )

    if not existing:

        device = models.Device(user_id=user.id, fingerprint=payload.fingerprint, label=payload.label)

        session.add(device)

        await session.commit()

    else:

        existing.last_seen = now_utc()

        device = existing

        await session.commit()

    count = await session.scalar(select(func.count(models.Device.id)).where(models.Device.user_id == user.id))

    device_count = max(count or 0, 1)

    price_value = await get_price(session)

    cost_per_day = price_value * device_count if price_value else 0

    estimated_days = int(user.balance / cost_per_day) if cost_per_day else 0

    user.allowed_devices = device_count

    if estimated_days > 0:

        expires_at = now_utc() + timedelta(days=estimated_days)

        user.subscription_end = expires_at

        user.link_suspended = False

    else:

        expires_at = now_utc()

        user.subscription_end = None

        user.link_suspended = True

    try:

        await rem_upsert_user(session, user, device_count, expires_at)

        await rem_register_hwid(session, user, device)

    except Exception:

        user.link_suspended = True

    await session.commit()

    return {"ok": True, "devices": count}





@app.delete("/api/device/{device_id}")

async def delete_device(

    device_id: int,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    device = await session.get(models.Device, device_id)

    if not device or device.user_id != user.id:

        raise HTTPException(status_code=404, detail="Device not found")

    await session.delete(device)

    await session.commit()

    remaining = await session.scalar(select(func.count(models.Device.id)).where(models.Device.user_id == user.id))

    device_count = max(remaining or 0, 1)

    price_value = await get_price(session)

    cost_per_day = price_value * device_count if price_value else 0

    estimated_days = int(user.balance / cost_per_day) if cost_per_day else 0

    user.allowed_devices = device_count

    if estimated_days > 0:

        expires_at = now_utc() + timedelta(days=estimated_days)

        user.subscription_end = expires_at

        user.link_suspended = False

    else:

        expires_at = now_utc()

        user.subscription_end = None

        user.link_suspended = True

    try:

        await rem_upsert_user(session, user, device_count, expires_at)

        await rem_delete_hwid(session, user, device.fingerprint)

    except Exception:

        user.link_suspended = True

    await session.commit()

    return {"ok": True}





@app.post("/api/webhooks/yookassa")

async def yookassa_hook(request: Request, session: AsyncSession = Depends(get_session)):

    data = await request.json()

    metadata = data.get("object", {}).get("metadata", {})

    payment_id = metadata.get("payment_id")

    status_value = data.get("object", {}).get("status")

    if not payment_id:

        return {"ok": False}

    payment: models.Payment | None = await session.get(models.Payment, int(payment_id))

    if not payment or payment.status == "succeeded":

        return {"ok": True}

    if status_value == "succeeded":

        payment.status = "succeeded"

        user = await session.get(models.User, payment.user_id)

        if user:

            user.balance += payment.amount

            await bot.send_message(int(user.telegram_id), f"Баланс пополнен на {payment.amount}?", reply_markup=webapp_keyboard())

    else:

        payment.status = status_value

    await session.commit()

    return {"ok": True}


@app.post("/api/webhooks/cryptobot")
async def cryptobot_hook(request: Request, session: AsyncSession = Depends(get_session)):
    """
    Webhook для Crypto Bot. Ждем update_type = invoice_paid и payload с id платежа (payment.id),
    который передаем в createInvoice.
    """
    try:
        data = await request.json()
    except Exception:
        return {"ok": False}

    update_type = data.get("update_type")
    status_value = (data.get("status") or data.get("invoice", {}).get("status") or "").lower()
    payload_id = (
        data.get("payload")
        or data.get("invoice_payload")
        or data.get("invoice", {}).get("payload")
        or data.get("data", {}).get("payload")
    )
    invoice_id = data.get("invoice_id") or data.get("invoice", {}).get("invoice_id")

    if update_type != "invoice_paid" or status_value != "paid" or not payload_id:
        return {"ok": True}

    try:
        payment_pk = int(str(payload_id))
    except ValueError:
        payment_pk = None

    payment: models.Payment | None = None
    if payment_pk:
        payment = await session.get(models.Payment, payment_pk)
    if not payment and invoice_id:
        payment = await session.scalar(
            select(models.Payment).where(models.Payment.provider_payment_id == str(invoice_id))
        )
    if not payment or payment.status == "succeeded":
        return {"ok": True}

    payment.status = "succeeded"
    if invoice_id and not payment.provider_payment_id:
        payment.provider_payment_id = str(invoice_id)

    user = await session.get(models.User, payment.user_id)
    if user:
        user.balance += payment.amount
        recalculated = await recalc_subscription(session, user)
        await bot.send_message(
            int(user.telegram_id),
            f"Баланс пополнен на {payment.amount} ₽",
            reply_markup=webapp_keyboard(),
        )
        await session.commit()
        return {"ok": True, "link_suspended": recalculated.get("link_suspended", True)}

    await session.commit()
    return {"ok": True}


def find_user_query(telegram_id: Optional[str], username: Optional[str]):

    if telegram_id:

        return select(models.User).where(models.User.telegram_id == str(telegram_id).lstrip("@"))

    if username:

        return select(models.User).where(models.User.username == str(username).lstrip("@"))

    raise HTTPException(status_code=400, detail="Нужен telegram_id или username")





def ensure_admin_user(user: models.User):

    if settings.admin_tg_id and str(user.telegram_id) == settings.admin_tg_id:

        return

    raise HTTPException(status_code=403, detail="Admin only")





async def ensure_admin_ui(token: str, session: AsyncSession) -> str:

    username = verify_admin_ui_token(token)

    cred = await session.scalar(select(models.AdminCredential).where(models.AdminCredential.username == username))

    if not cred:

        raise HTTPException(status_code=401, detail="Invalid admin token")

    return username





async def admin_ui_guard(x_admin_token: str = Header(..., alias="X-Admin-Token"), session: AsyncSession = Depends(get_session)):

    return await ensure_admin_ui(x_admin_token, session)





@app.post("/admin/broadcast")

async def admin_broadcast(

    payload: AdminBroadcast,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    ensure_admin_user(user)

    users = (await session.scalars(select(models.User))).all()

    for item in users:

        try:

            await bot.send_message(int(item.telegram_id), payload.message, reply_markup=webapp_keyboard())

        except Exception:

            continue

    return {"sent": len(users)}





@app.post("/admin/ban")

async def admin_ban(

    payload: AdminBan,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    ensure_admin_user(user)

    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))

    if not target:

        raise HTTPException(status_code=404, detail="User not found")

    target.banned = payload.banned

    await recalc_subscription(session, target)

    return {"ok": True, "banned": target.banned}





@app.post("/admin/topup")

async def admin_topup(

    payload: AdminBalance,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    ensure_admin_user(user)

    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))

    if not target:

        raise HTTPException(status_code=404, detail="User not found")

    target.balance += payload.amount
    result = await recalc_subscription(session, target)
    return {"ok": True, "balance": target.balance, "link_suspended": result["link_suspended"]}


@app.post("/admin/ui/debit")
async def admin_ui_debit(
    payload: AdminBalanceAdjust,
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    target.balance = max(0, target.balance - payload.amount)
    result = await recalc_subscription(session, target)
    return {"ok": True, "balance": target.balance, "link_suspended": result["link_suspended"]}


@app.post("/admin/ui/userinfo")
async def admin_ui_userinfo(
    payload: AdminUserLookup,
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    device_count = await session.scalar(
        select(func.count(models.Device.id)).where(models.Device.user_id == target.id)
    ) or 0
    rem_user = await session.scalar(select(models.RemUser).where(models.RemUser.user_id == target.id))
    return {
        "balance": target.balance,
        "subscription_end": target.subscription_end,
        "allowed_devices": target.allowed_devices,
        "devices": device_count,
        "banned": target.banned,
        "link": rem_user.subscription_url if rem_user else None,
    }





@app.post("/admin/tariffs", response_model=TariffOut)

async def admin_tariff(

    payload: AdminTariff,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    ensure_admin_user(user)

    tariff = models.Tariff(name=payload.name, days=payload.days, price=payload.price, base_devices=payload.base_devices)

    session.add(tariff)

    await session.commit()

    await session.refresh(tariff)

    return tariff





@app.post("/admin/servers")

async def admin_server(

    payload: AdminServer,

    user: models.User = Depends(get_current_user),

    session: AsyncSession = Depends(get_session),

):

    ensure_admin_user(user)

    server = models.Server(name=payload.name, endpoint=payload.endpoint, capacity=payload.capacity)

    session.add(server)

    await session.commit()

    return {"ok": True, "server_id": server.id}





@app.post("/admin/ui/login")

async def admin_ui_login(payload: AdminLogin, session: AsyncSession = Depends(get_session)):

    cred = await session.scalar(select(models.AdminCredential).where(models.AdminCredential.username == payload.username))

    if not cred or cred.password != payload.password:

        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_admin_ui_token(payload.username)

    return {"token": token}





@app.post("/admin/ui/creds")

async def admin_ui_creds(

    payload: AdminCredUpdate,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    cred = await session.scalar(select(models.AdminCredential).limit(1))

    if not cred:

        cred = models.AdminCredential(username=payload.username, password=payload.password)

        session.add(cred)

    else:

        cred.username = payload.username

        cred.password = payload.password

    await session.commit()

    return {"ok": True}





@app.post("/admin/ui/broadcast")

async def admin_ui_broadcast(

    payload: AdminBroadcast,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    users = (await session.scalars(select(models.User))).all()

    for item in users:

        try:

            await bot.send_message(int(item.telegram_id), payload.message, reply_markup=webapp_keyboard())

        except Exception:

            continue

    return {"sent": len(users)}


@app.post("/admin/ui/broadcast_photo")
async def admin_ui_broadcast_photo(
    payload: AdminBroadcastPhoto,
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    users = (await session.scalars(select(models.User))).all()
    sent = 0
    for item in users:
        try:
            await bot.send_photo(
                int(item.telegram_id),
                payload.photo_url,
                caption=payload.message or None,
                reply_markup=webapp_keyboard(),
            )
            sent += 1
        except Exception:
            continue
    return {"sent": sent}


@app.post("/admin/ui/broadcast_photo_upload")
async def admin_ui_broadcast_photo_upload(
    message: str = Form(""),
    file: UploadFile = File(...),
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    users = (await session.scalars(select(models.User))).all()
    data = await file.read()
    input_file = types.BufferedInputFile(data, filename=file.filename or "photo.jpg")
    sent = 0
    for item in users:
        try:
            await bot.send_photo(int(item.telegram_id), input_file, caption=message or None, reply_markup=webapp_keyboard())
            sent += 1
        except Exception:
            continue
    return {"sent": sent}





@app.post("/admin/ui/servers")

async def admin_ui_servers(

    payload: AdminServer,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    server = models.Server(name=payload.name, endpoint=payload.endpoint, capacity=payload.capacity)

    session.add(server)

    await session.commit()

    return {"ok": True, "server_id": server.id}





@app.get("/admin/ui/servers/list")

async def admin_ui_servers_list(_: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):

    servers = (await session.scalars(select(models.Server))).all()

    return {"servers": [{"id": s.id, "name": s.name, "endpoint": s.endpoint, "capacity": s.capacity} for s in servers]}





@app.post("/admin/ui/servers/delete")

async def admin_ui_servers_delete(

    payload: AdminServerDelete,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    server = await session.get(models.Server, payload.server_id)

    if not server:

        raise HTTPException(status_code=404, detail="Not found")

    await session.delete(server)

    await session.commit()

    return {"ok": True}


@app.get("/admin/ui/rem/status")
async def admin_ui_rem_status(_: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):
    base, base_api, token = get_rem_config()
    url = f"{base_api}/system/health"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(url, headers=headers) as resp:
                ok = resp.status == 200
                try:
                    data = await resp.json()
                    detail = data if isinstance(data, str) else data.get("status") or str(data)
                except Exception:
                    detail = await resp.text()
                return {"ok": ok, "detail": detail, "status": resp.status}
    except Exception as e:
        return {"ok": False, "detail": str(e)}

@app.post("/admin/ui/marzban/servers")
async def admin_ui_marzban_servers(
    payload: AdminMarzbanServer, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)
):
    server = models.MarzbanServer(
        name=payload.name, api_url=payload.api_url, api_token=payload.api_token, capacity=payload.capacity
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return MarzbanServerOut.model_validate(server)


@app.get("/admin/ui/marzban/servers/list", response_model=list[MarzbanServerOut])
async def admin_ui_marzban_servers_list(_: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):
    servers = (await session.scalars(select(models.MarzbanServer))).all()
    return servers


@app.post("/admin/ui/marzban/servers/delete")
async def admin_ui_marzban_servers_delete(
    payload: AdminMarzbanServerDelete, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)
):
    server = await session.get(models.MarzbanServer, payload.server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(server)
    await session.commit()
    return {"ok": True}







@app.post("/admin/ui/rem/squads")
async def admin_ui_rem_squad_create(
    payload: AdminRemSquad, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)
):
    squad = models.RemSquad(name=payload.name, uuid=payload.uuid, capacity=payload.capacity)
    session.add(squad)
    await session.commit()
    await session.refresh(squad)
    return {"id": squad.id, "name": squad.name, "uuid": squad.uuid, "capacity": squad.capacity}


@app.get("/admin/ui/rem/squads/list")
async def admin_ui_rem_squad_list(_: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):
    squads = (await session.scalars(select(models.RemSquad))).all()
    return [{"id": s.id, "name": s.name, "uuid": s.uuid, "capacity": s.capacity} for s in squads]


@app.post("/admin/ui/rem/squads/update")
async def admin_ui_rem_squad_update(
    payload: AdminRemSquadUpdate, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)
):
    squad = await session.get(models.RemSquad, payload.squad_id)
    if not squad:
        raise HTTPException(status_code=404, detail="Not found")
    squad.capacity = payload.capacity
    await session.commit()
    return {"ok": True, "capacity": squad.capacity}


@app.post("/admin/ui/rem/squads/delete")
async def admin_ui_rem_squad_delete(
    payload: AdminRemSquadDelete, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)
):
    squad = await session.get(models.RemSquad, payload.squad_id)
    if not squad:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(squad)
    await session.commit()
    return {"ok": True}
@app.post("/admin/ui/servers/update")

async def admin_ui_servers_update(

    payload: AdminServerUpdate,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    server = await session.get(models.Server, payload.server_id)

    if not server:

        raise HTTPException(status_code=404, detail="Not found")

    server.capacity = payload.capacity

    await session.commit()

    return {"ok": True, "capacity": server.capacity}





@app.get("/admin/ui/price")

async def admin_ui_price(_: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):

    return {"price": await get_price(session)}





@app.post("/admin/ui/price")

async def admin_ui_set_price(payload: AdminPrice, _: str = Depends(admin_ui_guard), session: AsyncSession = Depends(get_session)):

    await set_price(session, payload.price)

    return {"ok": True, "price": await get_price(session)}





@app.post("/admin/ui/tariffs", response_model=TariffOut)

async def admin_ui_tariffs(

    payload: AdminTariff,

    _: str = Depends(admin_ui_guard),

    session: AsyncSession = Depends(get_session),

):

    tariff = models.Tariff(name=payload.name, days=payload.days, price=payload.price, base_devices=payload.base_devices)

    session.add(tariff)

    await session.commit()

    await session.refresh(tariff)

    return tariff





@app.post("/admin/ui/topup")
async def admin_ui_topup(
    payload: AdminBalance,
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.balance += payload.amount
    result = await recalc_subscription(session, target)
    return {"ok": True, "balance": target.balance, "link_suspended": result["link_suspended"]}





@app.post("/admin/ui/ban")
async def admin_ui_ban(
    payload: AdminBan,
    _: str = Depends(admin_ui_guard),
    session: AsyncSession = Depends(get_session),
):
    target = await session.scalar(find_user_query(payload.telegram_id, payload.username))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.banned = payload.banned
    result = await recalc_subscription(session, target)
    return {"ok": True, "banned": target.banned, "link_suspended": result["link_suspended"]}





@app.get("/{slug}")
async def wireguard_profile(slug: str, session: AsyncSession = Depends(get_session)):
    raise HTTPException(status_code=404, detail="?????? ??????????")

