import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 1. KONFIGURASI PAIR PRIORITAS & SPESIFIKASI KONTRAK
# ==========================================
# Konfigurasi akurasi nilai pip & kontrak untuk XAUUSD, XAGUSD, dan EURUSD
PAIRS_CONFIG = {
    "XAUUSD": {
        "name": "Gold vs US Dollar",
        "yf_symbol": "GC=F",          # Gold Futures / Spot proxy di Yahoo Finance
        "td_symbol": "XAU/USD",       # Simbol TwelveData
        "pip_size": 0.10,             # 1 pip Gold = $0.10 pergerakan harga
        "pip_value_per_lot": 10.0,    # 1 Standard Lot (100 oz) = $10 per 0.10 gerak harga
        "decimals": 2,
        "atr_sl_WaitMs_multiplier": 0.5,
    },
    "XAGUSD": {
        "name": "Silver vs US Dollar",
        "yf_symbol": "SI=F",          # Silver Futures / Spot proxy di Yahoo Finance
        "td_symbol": "XAG/USD",       # Simbol TwelveData
        "pip_size": 0.01,             # 1 pip Silver = $0.01 pergerakan harga
        "pip_value_per_lot": 50.0,    # 1 Standard Lot (5,000 oz) = $50 per $0.01 gerak harga
        "decimals": 3,
        "atr_sl_WaitMs_multiplier": 0.5,
    },
    "EURUSD": {
        "name": "Euro vs US Dollar",
        "yf_symbol": "EURUSD=X",      # EURUSD Spot di Yahoo Finance
        "td_symbol": "EUR/USD",       # Simbol TwelveData
        "pip_size": 0.0001,           # 1 pip EURUSD = 0.0001
        "pip_value_per_lot": 10.0,    # 1 Standard Lot (100,000 unit) = $10 per pip
        "decimals": 5,
        "atr_sl_WaitMs_multiplier": 0.5,
    },
}

# ==========================================
# 2. MANAJEMEN RISIKO (MONEY MANAGEMENT)
# ==========================================
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000.0"))  # Modal dalam USD
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1.0"))           # Risiko per trade (%)
RR_TP1 = float(os.getenv("RR_TP1", "2.0"))                       # Target Risk:Reward 1 (1:2)
RR_TP2 = float(os.getenv("RR_TP2", "3.5"))                       # Target Risk:Reward 2 (1:3.5)

# ==========================================
# 3. PARAMETER ALGORITMA SMC (H1 + M15 + M5)
# ==========================================
SWING_LENGTH_H1 = int(os.getenv("SWING_LENGTH_H1", "5"))         # Fractal lookback H1
SWING_LENGTH_M15 = int(os.getenv("SWING_LENGTH_M15", "4"))       # Fractal lookback M15
SWING_LENGTH_M5 = int(os.getenv("SWING_LENGTH_M5", "3"))         # Fractal lookback M5
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "60"))      # Jeda anti-spam per pair (menit)

# Filter Jam Trading (Killzone Filter)
# Jika False, bot memantau 24 jam penuh (Senin-Jumat)
ONLY_ACTIVE_SESSIONS = os.getenv("ONLY_ACTIVE_SESSIONS", "false").lower() == "true"
# Jam UTC untuk London + New York Session (07:00 UTC - 21:00 UTC / 14:00 WIB - 04:00 WIB)
ACTIVE_START_HOUR_UTC = int(os.getenv("ACTIVE_START_HOUR_UTC", "7"))
ACTIVE_END_HOUR_UTC = int(os.getenv("ACTIVE_END_HOUR_UTC", "21"))

# ==========================================
# 4. DATA FEED & AI ANALYST (OPSIONAL)
# ==========================================
# Jika TWELVEDATA_API_KEY kosong, otomatis pakai Yahoo Finance (100% Gratis tanpa API Key)
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()

# Jika GEMINI_API_KEY kosong, bot tetap berjalan 100% menggunakan algoritma matematika SMC.
# Jika diisi, Gemini akan menambahkan komentar analisa institusional pada pesan WhatsApp.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ==========================================
# 5. KONFIGURASI MULTI-PROVIDER WHATSAPP
# ==========================================
# Bot mendukung kombinasi provider sekaligus. Provider yang memiliki kredensial di .env akan aktif otomatis.

# A. CallMeBot (100% Gratis untuk nomor WA pribadi)
CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE", "6281233959685").strip()       # Nomor WA aktif
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "").strip()

# B. Fonnte (Gateway WhatsApp Indonesia populer)
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "").strip()
FONNTE_TARGET = os.getenv("FONNTE_TARGET", "081233959685").strip()           # Nomor WA aktif

# C. Twilio WhatsApp API
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_WA = os.getenv("TWILIO_FROM_WA", "whatsapp:+14155238886").strip()
TWILIO_TO_WA = os.getenv("TWILIO_TO_WA", "whatsapp:+6281233959685").strip()   # Nomor WA aktif

# D. Custom Webhook (WAHA / Baileys / Go-WhatsApp Self-Hosted)
CUSTOM_WA_WEBHOOK_URL = os.getenv("CUSTOM_WA_WEBHOOK_URL", "").strip()
CUSTOM_WA_TARGET = os.getenv("CUSTOM_WA_TARGET", "6281233959685").strip()
