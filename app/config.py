from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    webapp_url: str
    yookassa_shop_id: str
    yookassa_secret_key: str
    admin_secret: str
    admin_tg_id: str | None = None
    database_url: str = "sqlite+aiosqlite:///./data.db"
    support_username: str = "support"
    ios_help_url: str = "https://telegra.ph/ios-vpn-install"
    android_help_url: str = "https://telegra.ph/android-vpn-install"
    domain: str = "the1priority.ru"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
