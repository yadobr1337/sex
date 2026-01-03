import datetime as dt
from typing import List, Optional

from pydantic import BaseModel


class DeviceOut(BaseModel):
    id: int
    fingerprint: str
    label: str
    last_seen: dt.datetime

    class Config:
        orm_mode = True


class ServerOut(BaseModel):
    id: int
    name: str
    endpoint: str
    capacity: int

    class Config:
        orm_mode = True


class TariffOut(BaseModel):
    id: int
    name: str
    days: int
    price: int
    base_devices: int

    class Config:
        orm_mode = True


class UserState(BaseModel):
    balance: int
    subscription_end: Optional[dt.datetime]
    allowed_devices: int
    link: str
    server: Optional[ServerOut]
    devices: List[DeviceOut]
    tariffs: List[TariffOut]
    banned: bool
    link_suspended: bool
    ios_help_url: str
    android_help_url: str
    support_url: str
    is_admin: bool


class PaymentRequest(BaseModel):
    amount: int


class SubscriptionRequest(BaseModel):
    tariff_id: int
    devices: int


class DeviceRequest(BaseModel):
    fingerprint: str
    label: str = "device"


class AdminBroadcast(BaseModel):
    message: str


class AdminBan(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    banned: bool = True


class AdminBalance(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    amount: int


class AdminTariff(BaseModel):
    name: str
    days: int
    price: int
    base_devices: int = 1


class AdminServer(BaseModel):
    name: str
    endpoint: str
    capacity: int = 10
