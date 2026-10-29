import logging
from typing import Dict, Optional
import pandas as pd
import requests
import yfinance as yf
from config import PAIRS_CONFIG, TWELVEDATA_API_KEY

logger = logging.getLogger("SMC_Bot.DataFeed")


class MarketDataFeed:
    """
    Cloud Data Feed Mandiri untuk mengambil data Multi-Timeframe (H1, M15, M5).
    Mendukung:
    1. TwelveData API (Jika TWELVEDATA_API_KEY diisi di .env)
    2. Yahoo Finance / yfinance (Default 100% Gratis tanpa API Key)
    """

    def __init__(self):
        self.use_twelvedata = bool(TWELVEDATA_API_KEY)
        if self.use_twelvedata:
            logger.info("Data Feed Mode: TwelveData Cloud API (Presisi Spot)")
        else:
            logger.info("Data Feed Mode: Yahoo Finance Cloud (100% Gratis / Tanpa API Key)")

    def fetch_mtf_data(self, pair: str) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Mengambil data H1, M15, dan M5 untuk pair tertentu.
        Selalu membuang 1 candle terakhir yang masih berjalan (floating candle)
        agar sinyal SMC 100% berbasis Candle Close (Anti-Repaint).
        """
        if pair not in PAIRS_CONFIG:
            logger.error(f"Pair {pair} tidak ditemukan di PAIRS_CONFIG.")
            return None

        cfg = PAIRS_CONFIG[pair]

        try:
            if self.use_twelvedata:
                df_h1 = self._fetch_twelvedata(cfg["td_symbol"], "1h", outputsize=200)
                df_m15 = self._fetch_twelvedata(cfg["td_symbol"], "15min", outputsize=200)
                df_m5 = self._fetch_twelvedata(cfg["td_symbol"], "5min", outputsize=200)
                if df_h1 is not None and df_m15 is not None and df_m5 is not None:
                    return {"H1": df_h1, "M15": df_m15, "M5": df_m5}
                logger.warning(f"[{pair}] Fallback ke Yahoo Finance karena TwelveData gagal/limit.")

            # Default atau Fallback: Yahoo Finance
            yf_sym = cfg["yf_symbol"]
            df_h1 = self._fetch_yfinance(yf_sym, interval="1h", period="1mo")
            df_m15 = self._fetch_yfinance(yf_sym, interval="15m", period="5d")
            df_m5 = self._fetch_yfinance(yf_sym, interval="5m", period="5d")

            if df_h1 is None or df_m15 is None or df_m5 is None:
                logger.warning(f"[{pair}] Data tidak lengkap dari Yahoo Finance.")
                return None

            return {"H1": df_h1, "M15": df_m15, "M5": df_m5}

        except Exception as e:
            logger.error(f"[{pair}] Error saat mengambil data MTF: {e}")
            return None

    def _fetch_yfinance(self, symbol: str, interval: str, period: str) -> Optional[pd.DataFrame]:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df is None or df.empty or len(df) < 30:
            return None

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.dropna(subset=["open", "high", "low", "close"], inplace=True)

        # Buang bar terakhir yang sedang terbentuk (floating bar) agar strictly Candle Close
        if len(df) > 20:
            df = df.iloc[:-1].copy()

        df.reset_index(inplace=True)
        df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
        return df

    def _fetch_twelvedata(self, symbol: str, interval: str, outputsize: int = 200) -> Optional[pd.DataFrame]:
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVEDATA_API_KEY,
            "format": "JSON",
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if "values" not in data:
            logger.warning(f"TwelveData response error ({symbol} {interval}): {data.get('message')}")
            return None

        df = pd.DataFrame(data["values"])
        df["timestamp"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df.get("volume", 0).astype(float) if "volume" in df else 0.0

        # Urutkan dari terlama ke terbaru
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Buang candle paling ujung yang masih berjalan (floating)
        if len(df) > 20:
            df = df.iloc[:-1].copy()

        return df[["timestamp", "open", "high", "low", "close", "volume"]]
