import asyncio
import math
from datetime import timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .bot import bot, dp, webapp_keyboard
from .config import settings
from .database import Base, engine, get_session, AsyncSessionLocal
from .schemas import (
    AdminBalance,
    AdminBan,
    AdminBroadcast,
    AdminServer,
    AdminTariff,
    AdminCredUpdate,
    AdminLogin,
    DeviceRequest,
    PaymentRequest,
    SubscriptionRequest,
    TariffOut,
    UserState,
)
from .utils import create_admin_ui_token, make_wireguard_link, new_slug, now_utc, validate_telegram_webapp_data, verify_admin_ui_token

app = FastAPI(title="1VPN")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


async def get_or_create_user(init_data: str, session: AsyncSession) -> models.User:
    tg_user = validate_telegram_webapp_data(init_data, settings.bot_token)
    tg_id = str(tg_user["id"])
    user = await session.scalar(select(models.User).where(models.User.telegram_id == tg_id))
    if user:
        return user

    server = await pick_available_server(session)
    if not server:
        raise HTTPException(status_code=503, detail="Нет свободных серверов. Напишите в поддержку.")

    user = models.User(
        telegram_id=tg_id,
        username=tg_user.get("username"),
        server_id=server.id,
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
    return {"ok": True, "link": make_wireguard_link(user.link_slug)}


@app.get("/api/state", response_model=UserState)
async def state(user: models.User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    tariffs = (await session.scalars(select(models.Tariff))).all()
    devices = (await session.scalars(select(models.Device).where(models.Device.user_id == user.id))).all()
    server = await session.get(models.Server, user.server_id) if user.server_id else None
    return UserState(
        balance=user.balance,
        subscription_end=user.subscription_end,
        allowed_devices=user.allowed_devices,
        link=make_wireguard_link(user.link_slug),
        server=server,
        devices=devices,
        tariffs=tariffs,
        banned=user.banned,
        link_suspended=user.link_suspended,
        ios_help_url=settings.ios_help_url,
        android_help_url=settings.android_help_url,
        support_url=f"https://t.me/{settings.support_username}",
        is_admin=settings.admin_tg_id == str(user.telegram_id),
    )


@app.post("/api/topup")
async def create_topup(
    payload: PaymentRequest,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.amount < 50:
        raise HTTPException(status_code=400, detail="Минимальная сумма 50₽")

    payment = models.Payment(user_id=user.id, amount=payload.amount, status="pending")
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    # YooKassa payment creation (SBP)
    try:
        from yookassa import Configuration, Payment

        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key

        payment_response = Payment.create(
            {
                "amount": {"value": f"{payload.amount}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"{settings.webapp_url}?paid={payment.id}"},
                "payment_method_data": {"type": "sbp"},
                "description": f"1VPN пополнение #{payment.id}",
                "metadata": {"payment_id": payment.id},
            }
        )
        payment.provider_payment_id = payment_response.id
        await session.commit()
        return {"confirmation_url": payment_response.confirmation.confirmation_url, "payment_id": payment.id}
    except Exception:
        # Fallback for demo without valid credentials
        return {
            "confirmation_url": f"https://yoomoney.ru/quickpay/confirm.xml?label={payment.id}",
            "payment_id": payment.id,
        }


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
        await session.commit()
    count = await session.scalar(select(func.count(models.Device.id)).where(models.Device.user_id == user.id))
    if count and count > user.allowed_devices:
        user.link_suspended = True
        await session.commit()
        await bot.send_message(
            int(user.telegram_id),
            "Обнаружено новое устройство. Оплатите дополнительный слот, чтобы продолжить пользоваться VPN.",
            reply_markup=webapp_keyboard(),
        )
        raise HTTPException(status_code=403, detail="Слишком много устройств. Купите еще слот.")
    return {"ok": True, "devices": count}


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
            await bot.send_message(int(user.telegram_id), f"Баланс пополнен на {payment.amount}₽", reply_markup=webapp_keyboard())
    else:
        payment.status = status_value
    await session.commit()
    return {"ok": True}


def find_user_query(telegram_id: Optional[str], username: Optional[str]):
    if telegram_id:
        return select(models.User).where(models.User.telegram_id == telegram_id)
    if username:
        return select(models.User).where(models.User.username == username)
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
    await session.commit()
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
    await session.commit()
    return {"ok": True, "balance": target.balance}


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
    await session.commit()
    return {"ok": True, "balance": target.balance}


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
    await session.commit()
    return {"ok": True, "banned": target.banned}


@app.get("/{slug}")
async def wireguard_profile(slug: str, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(models.User).where(models.User.link_slug == slug))
    if not user:
        raise HTTPException(status_code=404, detail="Не найдено")
    if user.banned or user.link_suspended:
        raise HTTPException(status_code=403, detail="Ссылка заблокирована")
    if not user.subscription_end or user.subscription_end < now_utc():
        raise HTTPException(status_code=403, detail="Подписка неактивна")
    server = await session.get(models.Server, user.server_id) if user.server_id else None
    return {
        "link": make_wireguard_link(user.link_slug),
        "server_endpoint": server.endpoint if server else None,
        "expires_at": user.subscription_end,
        "devices_allowed": user.allowed_devices,
        "notice": "Импортируйте ссылку в VPN-клиенте с поддержкой WireGuard.",
    }
