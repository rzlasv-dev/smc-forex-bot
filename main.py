import os
import sys
import html
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone

# ==========================================
# KONFIGURASI
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Kabar "bot masih hidup" tiap siklus (workflow dijadwalkan tiap 15 menit)
SEND_HEARTBEAT = os.getenv("SEND_HEARTBEAT", "true").lower() == "true"

# Filter sesi (jam UTC). London + New York = sekitar 07:00 - 20:00 UTC
USE_SESSION_FILTER = os.getenv("USE_SESSION_FILTER", "true").lower() == "true"
SESSION_START_UTC = int(os.getenv("SESSION_START_UTC", "7"))
SESSION_END_UTC = int(os.getenv("SESSION_END_UTC", "20"))

# Parameter strategi (bisa disetel)
