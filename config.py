from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

VK_GROUP_TOKEN = (os.environ.get("VK_GROUP_TOKEN") or "").strip()
BNOVO_ACCOUNT_ID = (os.environ.get("BNOVO_ACCOUNT_ID") or "").strip()
BNOVO_API_KEY = (os.environ.get("BNOVO_API_KEY") or "").strip()
# Опционально: токен сообщества с правом wall для дублирования задания на стену (как в Android).
VK_WALL_TOKEN = (os.environ.get("VK_WALL_TOKEN") or "").strip()
VK_GROUP_ID_FOR_WALL = (os.environ.get("VK_GROUP_ID_FOR_WALL") or "").strip()

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "housekeeping.db"
