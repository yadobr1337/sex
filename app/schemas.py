import datetime as dt
from typing import List, Optional

from pydantic import BaseModel


class DeviceOut(BaseModel):
    id: int
    fingerprint: str
    label: str
    last_seen: dt.datetime
    model_config = {"from_attributes": True}


class ServerOut(BaseModel):
    id: int
    name: str
    endpoint: str
    capacity: int
    model_config = {"from_attributes": True}


class TariffOut(BaseModel):
    id: int
    name: str
    days: int
    price: int
    base_devices: int
    model_config = {"from_attributes": True}


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
    channel_url: Optional[str] = None
    price_per_day: float
    estimated_days: int
    is_admin: bool


class PaymentRequest(BaseModel):
    amount: int
    provider: str | None = "sbp"


class PaymentOut(BaseModel):
    id: int
    amount: int
    status: str
    provider: str
    created_at: dt.datetime
    class Config:
        from_attributes = True


class SubscriptionRequest(BaseModel):
    tariff_id: int
    devices: int


class DeviceRequest(BaseModel):
    fingerprint: str
    label: str = "device"


class AdminBroadcast(BaseModel):
    message: str


class AdminBroadcastPhoto(BaseModel):
    message: str
    photo_url: str


class AdminBan(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    banned: bool = True


class AdminBalance(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    amount: int


class AdminBalanceAdjust(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    amount: int


class AdminUserLookup(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None


class AdminTariff(BaseModel):
    name: str
    days: int
    price: int
    base_devices: int = 1


class AdminServer(BaseModel):
    name: str
    endpoint: str
    capacity: int = 10


class AdminServerDelete(BaseModel):
    server_id: int


class AdminServerUpdate(BaseModel):
    server_id: int
    capacity: int


class AdminPrice(BaseModel):
    price: int


class AdminMaintenance(BaseModel):
    enabled: bool


class AdminMaintenanceAllow(BaseModel):
    telegram_ids: list[str]


class AdminUserLookup(BaseModel):
    telegram_id: Optional[str] = None
    username: Optional[str] = None


class AdminRemSquad(BaseModel):
    name: str
    uuid: str
    capacity: int = 50


class AdminRemSquadUpdate(BaseModel):
    squad_id: int
    capacity: int = 50


class AdminRemSquadDelete(BaseModel):
    squad_id: int


class MarzbanServerOut(BaseModel):
    id: int
    name: str
    api_url: str
    capacity: int
    model_config = {"from_attributes": True}


class AdminMarzbanServer(BaseModel):
    name: str
    api_url: str
    api_token: str
    capacity: int = 10


class AdminMarzbanServerDelete(BaseModel):
    server_id: int


class AdminLogin(BaseModel):
    username: str
    password: str


class AdminCredUpdate(BaseModel):
    username: str
    password: str


class AdminLoginStatus(BaseModel):
    request_id: str
