from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    webapp_url: str
    yookassa_shop_id: str
    yookassa_secret_key: str
    payment_return_url: str | None = None
    admin_secret: str
    admin_tg_id: str | None = None
    database_url: str = "sqlite+aiosqlite:///./data.db"
    support_username: str = "support"
    required_channel: str | None = None  # формат @channel или username
    policy_url: str | None = None
    ios_help_url: str = "https://telegra.ph/ios-vpn-install"
    android_help_url: str = "https://telegra.ph/android-vpn-install"
    domain: str = "the1priority.ru"
    price_per_day: float = 10.0
    rem_base_url: str = ""
    rem_api_token: str = ""
    crypto_pay_token: str = ""
    crypto_pay_asset: str = "USDT"
    crypto_rate: float = 0.0  # рублей за 1 единицу актива (например, 100 = 100₽ за 1 USDT/TON)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
