from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import select

from .config import settings
from .database import AsyncSessionLocal
from . import models
from .utils import create_admin_ui_token, now_utc


def webapp_keyboard() -> InlineKeyboardMarkup:
    base_url = (settings.webapp_url or "").strip()
    if base_url:
        base_url = base_url.rstrip("/")
    else:
        base_url = "https://the1priority.ru"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть 1VPN", web_app=WebAppInfo(url=base_url))],
            [InlineKeyboardButton(text="Поддержка", url=f"https://t.me/{settings.support_username}")],
        ]
    )


bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


async def is_subscribed(user_id: int) -> bool:
    """Проверка подписки на канал, если указан REQUIRED_CHANNEL."""
    if not settings.required_channel:
        return True
    try:
        member = await bot.get_chat_member(settings.required_channel, user_id)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False


def subscribe_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Подписаться",
                url=f"https://t.me/{settings.required_channel.lstrip('@')}" if settings.required_channel else "",
            )
        ],
        [InlineKeyboardButton(text="Проверить", callback_data="check_sub")],
    ]
    if settings.policy_url:
        buttons.append([InlineKeyboardButton(text="Политика конфиденциальности", url=settings.policy_url)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def policy_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if settings.policy_url:
        rows.append([InlineKeyboardButton(text="Политика конфиденциальности", url=settings.policy_url)])
    rows.append([InlineKeyboardButton(text="Согласен", callback_data="accept_policy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Открыть мини-приложение 1VPN:", reply_markup=webapp_keyboard())


@dp.message(F.text.lower().contains("поддержка"))
async def support(message: Message):
    await message.answer("Нажмите кнопку ниже, чтобы связаться с поддержкой.", reply_markup=webapp_keyboard())


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(query: CallbackQuery):
    if not await is_subscribed(query.from_user.id):
        await query.answer("Нет подписки на канал", show_alert=True)
        return
    await query.message.edit_text(
        "Подписка подтверждена. Согласитесь с политикой, чтобы открыть 1VPN.",
        reply_markup=policy_keyboard(),
    )
    await query.answer()


@dp.callback_query(F.data == "accept_policy")
async def cb_accept_policy(query: CallbackQuery):
    if not await is_subscribed(query.from_user.id):
        await query.message.edit_text("Сначала подпишитесь на канал.", reply_markup=subscribe_keyboard())
        await query.answer("Нет подписки на канал", show_alert=True)
        return
    await query.message.edit_text("Готово! Открывайте мини-приложение 1VPN.", reply_markup=webapp_keyboard())
    await query.answer()

@dp.callback_query(F.data.startswith("admin_login:"))
async def cb_admin_login(query: CallbackQuery):
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        await query.answer("Invalid request", show_alert=True)
        return
    action, req_id = parts[1], parts[2]
    async with AsyncSessionLocal() as session:
        req = await session.get(models.AdminLoginRequest, req_id)
        if not req:
            await query.answer("Request expired", show_alert=True)
            return
        if req.status != "pending":
            await query.answer("Already handled", show_alert=True)
            return
        if req.expires_at and req.expires_at < now_utc():
            req.status = "expired"
            req.decided_at = now_utc()
            await session.commit()
            await query.answer("Request expired", show_alert=True)
            return
        if action == "approve":
            req.status = "approved"
            req.token = create_admin_ui_token(req.username)
            req.decided_at = now_utc()
            await session.commit()
            await query.message.edit_text("������ ����������� ?")
            await query.answer("��������")
            return
        if action == "deny":
            req.status = "denied"
            req.decided_at = now_utc()
            await session.commit()
            await query.message.edit_text("������ �������� ?")
            await query.answer("���������")
            return
    await query.answer("������", show_alert=True)
