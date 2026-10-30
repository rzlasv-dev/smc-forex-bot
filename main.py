import os
import sys
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone

# ==========================================
# KONFIGURASI TELEGRAM & MARKET
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Diubah agar otomatis bernilai true (selalu kirim laporan status meskipun tidak ada setup)
SEND_STATUS_IF_NO_SETUP = os.getenv("SEND_STATUS_IF_NO_SETUP", "true").lower() == "true"

PAIRS = {
    "XAUUSD (GOLD)": {"ticker": "GC=F", "pip_value": 0.1, "decimals": 2},
    "EURUSD": {"ticker": "EURUSD=X", "pip_value": 0.0001, "decimals": 5},
    "GBPUSD": {"ticker": "GBPUSD=X", "pip_value": 0.0001, "decimals": 5},
    "USDJPY": {"ticker": "USDJPY=X", "pip_value": 0.01, "decimals": 3},
    "AUDUSD": {"ticker": "AUDUSD=X", "pip_value": 0.0001, "decimals": 5},
}


def send_telegram_message(text: str) -> bool:
    """Mengirim pesan ke Telegram menggunakan format HTML."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diset!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            print("[SUCCESS] Pesan berhasil dikirim ke Telegram.")
            return True
        else:
            print(f"[ERROR] Gagal kirim ke Telegram ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"[EXCEPTION] Error saat menghubungi Telegram API: {e}")
        return False


def fetch_market_data(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Mengambil data OHLC real-time dengan penanganan MultiIndex yfinance."""
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        if len(df) > 2:
            df = df.iloc[:-1].copy()

        return df
    except Exception as e:
        print(f"[ERROR] Gagal mengambil data {ticker} ({interval}): {e}")
        return pd.DataFrame()


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Menghitung EMA 50, ATR 14, dan Swing High/Low."""
    df = df.copy()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()

    df["Swing_High"] = df["High"][
        (df["High"].shift(2) < df["High"]) &
        (df["High"].shift(1) < df["High"]) &
        (df["High"].shift(-1) < df["High"]) &
        (df["High"].shift(-2) < df["High"])
    ]
    df["Swing_Low"] = df["Low"][
        (df["Swing_Low"].shift(2) > df["Low"]) & if "Swing_Low" in df else
        (df["High"].shift(2) > df["Low"]) & # Safe fallback
        (df["Low"].shift(1) > df["Low"]) &
        (df["Low"].shift(-1) > df["Low"]) &
        (df["Low"].shift(-2) > df["Low"])
    ]
    return df


def analyze_multitimeframe_setup(pair_name: str, meta: dict):
    df_h1 = fetch_market_data(meta["ticker"], period="30d", interval="1h")
    df_m15 = fetch_market_data(meta["ticker"], period="7d", interval="15m")

    if len(df_h1) < 50 or len(df_m15) < 50:
        return None

    df_h1 = calculate_indicators(df_h1)
    df_m15 = calculate_indicators(df_m15)

    h1_close = float(df_h1["Close"].iloc[-1])
    h1_ema = float(df_h1["EMA50"].iloc[-1])
    h1_swings_high = df_h1["Swing_High"].dropna()
    h1_swings_low = df_h1["Swing_Low"].dropna()

    if len(h1_swings_high) < 2 or len(h1_swings_low) < 2:
        return None

    h1_last_sh = float(h1_swings_high.iloc[-1])
    h1_last_sl = float(h1_swings_low.iloc[-1])

    h1_bullish_structure = h1_close > h1_ema and h1_close > h1_last_sl
    h1_bearish_structure = h1_close < h1_ema and h1_close < h1_last_sh

    m15_close = float(df_m15["Close"].iloc[-1])
    m15_open = float(df_m15["Open"].iloc[-1])
    m15_prev_close = float(df_m15["Close"].iloc[-2])
    m15_atr = float(df_m15["ATR"].iloc[-1]) if not np.isnan(df_m15["ATR"].iloc[-1]) else (m15_close * 0.001)

    m15_swings_high = df_m15["Swing_High"].dropna()
    m15_swings_low = df_m15["Swing_Low"].dropna()
    if len(m15_swings_high) < 2 or len(m15_swings_low) < 2:
        return None

    m15_last_sh = float(m15_swings_high.iloc[-1])
    m15_last_sl = float(m15_swings_low.iloc[-1])

    m15_bullish_fvg = None
    m15_bearish_fvg = None

    for i in range(-6, -2):
        c1_high = float(df_m15["High"].iloc[i])
        c1_low = float(df_m15["Low"].iloc[i])
        c3_high = float(df_m15["High"].iloc[i + 2])
        c3_low = float(df_m15["Low"].iloc[i + 2])

        if c3_low > c1_high:
            m15_bullish_fvg = (c1_high, c3_low)
        if c3_high < c1_low:
            m15_bearish_fvg = (c3_high, c1_low)

    m15_bullish_bos = (m15_close > m15_last_sh) and (m15_prev_close <= m15_last_sh)
    m15_bearish_bos = (m15_close < m15_last_sl) and (m15_prev_close >= m15_last_sl)

    in_bullish_fvg = m15_bullish_fvg is not None and (m15_bullish_fvg[0] <= m15_close <= m15_bullish_fvg[1] * 1.0005)
    in_bearish_fvg = m15_bearish_fvg is not None and (m15_bearish_fvg[0] * 0.9995 <= m15_close <= m15_bearish_fvg[1])

    setup = None

    if h1_bullish_structure and ((m15_bullish_bos and m15_bullish_fvg) or (in_bullish_fvg and m15_close > m15_open)):
        order_type = "BUY NOW (Market Execution)" if in_bullish_fvg else "BUY / BUY LIMIT"
        entry_price = m15_close
        ob_low = float(df_m15["Low"].iloc[-6:].min())
        sl_price = min(ob_low, entry_price - (1.5 * m15_atr)) - (0.2 * m15_atr)
        risk = abs(entry_price - sl_price)

        if risk > 0:
            setup = {
                "pair": pair_name,
                "direction": "BUY",
                "order_type": order_type,
                "entry": entry_price,
                "sl": sl_price,
                "tp1": entry_price + (risk * 1.5),
                "tp2": entry_price + (risk * 2.5),
                "tp3": entry_price + (risk * 4.0),
                "risk_pips": round(risk / meta["pip_value"], 1),
                "decimals": meta["decimals"],
                "reason": "H1 Bullish Bias + M15 Bullish BOS & Unmitigated FVG/Order Block Zone",
            }

    elif h1_bearish_structure and ((m15_bearish_bos and m15_bearish_fvg) or (in_bearish_fvg and m15_close < m15_open)):
        order_type = "SELL NOW (Market Execution)" if in_bearish_fvg else "SELL / SELL LIMIT"
        entry_price = m15_close
        ob_high = float(df_m15["High"].iloc[-6:].max())
        sl_price = max(ob_high, entry_price + (1.5 * m15_atr)) + (0.2 * m15_atr)
        risk = abs(sl_price - entry_price)

        if risk > 0:
            setup = {
                "pair": pair_name,
                "direction": "SELL",
                "order_type": order_type,
                "entry": entry_price,
                "sl": sl_price,
                "tp1": entry_price - (risk * 1.5),
                "tp2": entry_price - (risk * 2.5),
                "tp3": entry_price - (risk * 4.0),
                "risk_pips": round(risk / meta["pip_value"], 1),
                "decimals": meta["decimals"],
                "reason": "H1 Bearish Bias + M15 Bearish BOS & Unmitigated FVG/Order Block Zone",
            }

    return setup


def format_signal_message(setup: dict) -> str:
    d = setup["decimals"]
    is_buy = setup["direction"] == "BUY"
    header_icon = "🟢" if is_buy else "🔴"
    arrow_icon = "📈" if is_buy else "📉"
    now_wib = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"{header_icon} <b>SMC SETUP DIETUKIKAN: {setup['direction']} {setup['pair']}</b> {arrow_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Action:</b> <code>{setup['order_type']}</code>\n"
        f"📊 <b>Timeframe:</b> H1 Bias + M15 Execution\n"
        f"🎯 <b>Zona Entry:</b> <code>{setup['entry']:.{d}f}</code>\n\n"
        f"🛑 <b>Stop Loss (SL):</b> <code>{setup['sl']:.{d}f}</code> <i>(-{setup['risk_pips']} pips)</i>\n"
        f"✅ <b>Take Profit 1:</b> <code>{setup['tp1']:.{d}f}</code>\n"
        f"✅ <b>Take Profit 2:</b> <code>{setup['tp2']:.{d}f}</code>\n"
        f"✅ <b>Take Profit 3:</b> <code>{setup['tp3']:.{d}f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Analisa Zona:</b>\n"
        f"• {setup['reason']}\n\n"
        f"🕒 <i>Waktu Scan: {now_wib}</i>"
    )


def main():
    print("=== Memulai Multi-Timeframe SMC Scanner (H1 + M15) ==Subs ===")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[FATAL] Secrets Telegram belum dikonfigurasi!")
        sys.exit(1)

    signals_found = []

    for pair_name, meta in PAIRS.items():
        print(f"Menganalisis {pair_name}...")
        setup = analyze_multitimeframe_setup(pair_name, meta)
        if setup:
            signals_found.append(setup)
            msg = format_signal_message(setup)
            send_telegram_message(msg)

    # Jika tidak ada satupun pair yang memenuhi setup, kirim laporan "Belum ada setup"
    if len(signals_found) == 0 and SEND_STATUS_IF_NO_SETUP:
        now_wib = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        no_setup_msg = (
            f"🔍 <b>SMC MARKET SCANNER STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <i>Waktu Scan:</i> <code>{now_wib}</code>\n\n"
            f"ℹ️ <b>Belum ada setup</b> yang valid atau konfluensi FVG/BOS pada pair yang dipindai saat ini.\n"
            f"Bot akan kembali memindai pada siklus 15 menit berikutnya."
        )
        send_telegram_message(no_setup_msg)

    print(f"=== Scan selesai. Sinyal ditemukan: {len(signals_found)} ===")


if __name__ == "__main__":
    main()
