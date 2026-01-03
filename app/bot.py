from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.client.default import DefaultBotProperties

from .config import settings


def webapp_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть 1VPN", web_app=WebAppInfo(url=settings.webapp_url))],
            [InlineKeyboardButton(text="Поддержка", url=f"https://t.me/{settings.support_username}")],
        ]
    )


bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Добро пожаловать в 1VPN. Управляйте подпиской и устройствами через мини-приложение.",
        reply_markup=webapp_keyboard(),
    )


@dp.message(F.text.lower().contains("поддержка"))
async def support(message: Message):
    await message.answer("Напишите нам в поддержку", reply_markup=webapp_keyboard())
