# models/bot.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class Robot:
    name: str
    transport: str

    ip: Optional[str] = None
    mac: Optional[str] = None


    connected: bool = False

    battery: Optional[int] = None
    rssi: Optional[int] = None
