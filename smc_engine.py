from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from config import (
    ACCOUNT_BALANCE,
    PAIRS_CONFIG,
    RISK_PERCENT,
    RR_TP1,
    RR_TP2,
    SWING_LENGTH_H1,
    SWING_LENGTH_M15,
    SWING_LENGTH_M5,
)


@dataclass
class SMCSetupSignal:
    pair: str
    direction: str                # "BUY" atau "SELL"
    setup_grade: str              # "A+ (Full MTF Confluence)" atau "A (SMC Continuation)"
    h1_structure: str             # Detail bias & struktur H1
    h1_zone: str                  # "DISCOUNT (<50%)" / "PREMIUM (>50%)" / "EQUILIBRIUM"
    m15_poi_type: str             # Contoh: "Unmitigated FVG + Order Block" / "Liquidity Sweep (SSL)"
    m15_poi_zone: Tuple[float, float]
    m5_trigger: str               # Contoh: "M5 Bullish CHoCH + Displacement FVG"
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    sl_pips: float
    recommended_lot: float
    risk_usd: float
    timestamp: str


class SMCEngine:
    """
    Mesin Analisa Smart Money Concepts (SMC) Multi-Timeframe (H1 -> M15 -> M5).
    100% berbasis algoritma matematis tanpa repaint (hanya menghitung closed candle).
    """

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return float((high - low).tail(14).mean())
        return float(atr)

    @staticmethod
    def find_swing_points(df: pd.DataFrame, left_right: int = 4) -> Tuple[List[Dict], List[Dict]]:
        """
        Mendeteksi Swing High dan Swing Low menggunakan Fractal Pivot.
        Mengembalikan list dict: [{"index": i, "price": val, "timestamp": ts}]
        """
        highs = df["high"].values
        lows = df["low"].values
        timestamps = df["timestamp"].values
        n = len(df)

        swing_highs = []
        swing_lows = []

        for i in range(left_right, n - left_right):
            window_h = highs[i - left_right : i + left_right + 1]
            if highs[i] == np.max(window_h) and np.sum(window_h == highs[i]) == 1:
                swing_highs.append({"index": i, "price": float(highs[i]), "timestamp": timestamps[i]})

            window_l = lows[i - left_right : i + left_right + 1]
            if lows[i] == np.min(window_l) and np.sum(window_l == lows[i]) == 1:
                swing_lows.append({"index": i, "price": float(lows[i]), "timestamp": timestamps[i]})

        return swing_highs, swing_lows

    def analyze_h1_bias(self, df_h1: pd.DataFrame) -> Dict:
        """
        Step 1: Analisa Struktur Market H1 (BOS / CHoCH & Dealing Range Premium/Discount).
        """
        swing_highs, swing_lows = self.find_swing_points(df_h1, left_right=SWING_LENGTH_H1)
        current_close = float(df_h1["close"].iloc[-1])

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            # Fallback menggunakan EMA 50 jika swing belum cukup
            ema50 = float(df_h1["close"].ewm(span=50, adjust=False).mean().iloc[-1])
            bias = "BULLISH" if current_close >= ema50 else "BEARISH"
            recent_high = float(df_h1["high"].tail(48).max())
            recent_low = float(df_h1["low"].tail(48).min())
            return {
                "bias": bias,
                "structure_note": f"H1 Trend ({bias} via Dynamic Structure)",
                "swing_high": recent_high,
                "swing_low": recent_low,
                "equilibrium": (recent_high + recent_low) / 2.0,
                "zone": "DISCOUNT" if current_close < (recent_high + recent_low) / 2.0 else "PREMIUM",
            }

        last_sh = swing_highs[-1]["price"]
        prev_sh = swing_highs[-2]["price"]
        last_sl = swing_lows[-1]["price"]
        prev_sl = swing_lows[-2]["price"]

        # Cek Break of Structure (BOS) / Change of Character (CHoCH)
        if current_close > last_sh:
            bias = "BULLISH"
            structure_note = f"Bullish BOS (Break di atas H1 Swing High {last_sh})"
        elif current_close < last_sl:
            bias = "BEARISH"
            structure_note = f"Bearish BOS (Break di bawah H1 Swing Low {last_sl})"
        elif last_sh > prev_sh and last_sl >= prev_sl:
            bias = "BULLISH"
            structure_note = "Bullish Structure (Higher High & Higher Low di H1)"
        elif last_sh <= prev_sh and last_sl < prev_sl:
            bias = "BEARISH"
            structure_note = "Bearish Structure (Lower High & Lower Low di H1)"
        else:
            # Gunakan posisi terhadap Equilibrium + EMA 50
            ema50 = float(df_h1["close"].ewm(span=50, adjust=False).mean().iloc[-1])
            bias = "BULLISH" if current_close >= ema50 else "BEARISH"
            structure_note = f"H1 Rotational ({bias} Orderflow)"

        range_high = max(last_sh, float(df_h1["high"].tail(24).max()))
        range_low = min(last_sl, float(df_h1["low"].tail(24).min()))
        eq = (range_high + range_low) / 2.0
        zone = "DISCOUNT (<50%)" if current_close <= eq else "PREMIUM (>50%)"

        return {
            "bias": bias,
            "structure_note": structure_note,
            "swing_high": range_high,
            "swing_low": range_low,
            "equilibrium": eq,
            "zone": zone,
        }

    def detect_unmitigated_fvg_and_ob(
        self, df: pd.DataFrame, direction: str, lookback: int = 60
    ) -> List[Dict]:
        """
        Mendeteksi Fair Value Gap (FVG) dan Order Block (OB) yang belum tertembus penuh (Unmitigated)
        dalam rentang `lookback` candle terakhir.
        """
        zones = []
        sub = df.tail(lookback).reset_index(drop=True)
        n = len(sub)
        if n < 10:
            return zones

        for i in range(2, n - 1):
            c0_high = float(sub["high"].iloc[i - 2])
            c0_low = float(sub["low"].iloc[i - 2])
            c0_open = float(sub["open"].iloc[i - 2])
            c0_close = float(sub["close"].iloc[i - 2])

            c2_high = float(sub["high"].iloc[i])
            c2_low = float(sub["low"].iloc[i])

            if direction == "BULLISH":
                # Bullish FVG: Low candle ke-3 (i) > High candle ke-1 (i-2)
                if c2_low > c0_high:
                    fvg_bottom = c0_high
                    fvg_top = c2_low
                    # Cek apakah sudah ditembus ke bawah oleh close candle setelahnya
                    subsequent_closes = sub["close"].iloc[i + 1 :]
                    if len(subsequent_closes) == 0 or subsequent_closes.min() >= fvg_bottom:
                        zones.append(
                            {
                                "type": "Bullish FVG (Imbalance)",
                                "bottom": fvg_bottom,
                                "top": fvg_top,
                                "index": i,
                            }
                        )
                        # Cek Order Block (Candle i-2 jika bearish atau candle terendah sebelum displacement)
                        ob_bottom = min(c0_low, float(sub["low"].iloc[i - 1]))
                        ob_top = max(c0_open, c0_close) if c0_close < c0_open else c0_high
                        if len(subsequent_closes) == 0 or subsequent_closes.min() >= ob_bottom:
                            zones.append(
                                {
                                    "type": "Bullish Order Block + FVG",
                                    "bottom": ob_bottom,
                                    "top": fvg_top,
                                    "index": i,
                                }
                            )

            elif direction == "BEARISH":
                # Bearish FVG: High candle ke-3 (i) < Low candle ke-1 (i-2)
                if c2_high < c0_low:
                    fvg_top = c0_low
                    fvg_bottom = c2_high
                    subsequent_closes = sub["close"].iloc[i + 1 :]
                    if len(subsequent_closes) == 0 or subsequent_closes.max() <= fvg_top:
                        zones.append(
                            {
                                "type": "Bearish FVG (Imbalance)",
                                "bottom": fvg_bottom,
                                "top": fvg_top,
                                "index": i,
                            }
                        )
                        ob_top = max(c0_high, float(sub["high"].iloc[i - 1]))
                        ob_bottom = min(c0_open, c0_close) if c0_close > c0_open else c0_low
                        if len(subsequent_closes) == 0 or subsequent_closes.max() <= ob_top:
                            zones.append(
                                {
                                    "type": "Bearish Order Block + FVG",
                                    "bottom": fvg_bottom,
                                    "top": ob_top,
                                    "index": i,
                                }
                            )

        return zones

    def analyze_m15_poi(self, df_m15: pd.DataFrame, h1_bias: str) -> Dict:
        """
        Step 2: Cek apakah harga di M15 baru saja menyentuh POI (FVG / Order Block)
        ATAU baru saja melakukan Liquidity Sweep (Stop Hunt) searah bias H1.
        """
        atr_m15 = self.compute_atr(df_m15, 14)
        recent_bars = df_m15.tail(3)  # 3 candle M15 terakhir (45 menit terakhir)
        recent_low = float(recent_bars["low"].min())
        recent_high = float(recent_bars["high"].max())
        current_close = float(df_m15["close"].iloc[-1])

        # 1. Cek Liquidity Sweep di M15
        swing_highs, swing_lows = self.find_swing_points(df_m15.iloc[:-3], left_right=SWING_LENGTH_M15)

        if h1_bias == "BULLISH" and swing_lows:
            last_ssl = swing_lows[-1]["price"]
            # Sell-Side Liquidity (SSL) Sweep: Ekor turun menembus Swing Low tapi close kembali di atasnya
            if recent_low < last_ssl and current_close > last_ssl:
                return {
                    "active": True,
                    "poi_type": "M15 Sell-Side Liquidity (SSL) Sweep / Stop Hunt",
                    "zone": (recent_low, last_ssl),
                    "invalidation_level": recent_low,
                }

        if h1_bias == "BEARISH" and swing_highs:
            last_bsl = swing_highs[-1]["price"]
            # Buy-Side Liquidity (BSL) Sweep: Ekor naik menembus Swing High tapi close kembali di bawahnya
            if recent_high > last_bsl and current_close < last_bsl:
                return {
                    "active": True,
                    "poi_type": "M15 Buy-Side Liquidity (BSL) Sweep / Stop Hunt",
                    "zone": (last_bsl, recent_high),
                    "invalidation_level": recent_high,
                }

        # 2. Cek Mitigasi ke Unmitigated Order Block / FVG di M15
        zones = self.detect_unmitigated_fvg_and_ob(df_m15.iloc[:-1], direction=h1_bias, lookback=65)
        buffer = atr_m15 * 0.25  # Toleransi sentuhan tipis ke FVG/OB

        for z in reversed(zones):
            z_bottom = z["bottom"]
            z_top = z["top"]
            if h1_bias == "BULLISH":
                # Harga turun menyentuh zona FVG/OB lalu bertahan di atas bottom zona
                if recent_low <= (z_top + buffer) and current_close >= z_bottom:
                    return {
                        "active": True,
                        "poi_type": f"M15 {z['type']}",
                        "zone": (z_bottom, z_top),
                        "invalidation_level": min(z_bottom, recent_low),
                    }
            else:
                # Harga naik menyentuh zona Bearish FVG/OB lalu bertahan di bawah top zona
                if recent_high >= (z_bottom - buffer) and current_close <= z_top:
                    return {
                        "active": True,
                        "poi_type": f"M15 {z['type']}",
                        "zone": (z_bottom, z_top),
                        "invalidation_level": max(z_top, recent_high),
                    }

        return {
            "active": False,
            "poi_type": "Menunggu harga masuk ke zona M15 FVG/OB atau Sweep Liquidity",
            "zone": (0.0, 0.0),
            "invalidation_level": 0.0,
        }

    def analyze_m5_trigger(self, df_m5: pd.DataFrame, h1_bias: str) -> Dict:
        """
        Step 3: Konfirmasi Eksekusi di M5 (Micro CHoCH, Displacement FVG, atau Engulfing Rejection).
        """
        atr_m5 = self.compute_atr(df_m5, 14)
        c_last = df_m5.iloc[-1]
        c_prev = df_m5.iloc[-2]
        c_prev2 = df_m5.iloc[-3]

        close_last = float(c_last["close"])
        open_last = float(c_last["open"])
        high_last = float(c_last["high"])
        low_last = float(c_last["low"])
        body_last = abs(close_last - open_last)

        swing_highs, swing_lows = self.find_swing_points(df_m5.iloc[:-1], left_right=SWING_LENGTH_M5)

        if h1_bias == "BULLISH":
            triggers = []
            # A. Cek Micro CHoCH / BOS M5
            if swing_highs and close_last > swing_highs[-1]["price"] and float(c_prev["close"]) <= swing_highs[-1]["price"]:
                triggers.append("M5 Bullish CHoCH (Structure Shift)")

            # B. Cek Bullish FVG / Displacement M5 baru terbentuk
            if low_last > float(c_prev2["high"]) and float(c_prev["close"]) > float(c_prev["open"]):
                triggers.append("M5 Bullish Displacement + FVG")

            # C. Cek Bullish Engulfing / Strong Rejection Pinbar di M5
            is_bull_engulfing = (
                close_last > open_last
                and float(c_prev["close"]) < float(c_prev["open"])
                and close_last > float(c_prev["open"])
                and body_last >= atr_m5 * 0.45
            )
            lower_wick = min(open_last, close_last) - low_last
            is_bull_pinbar = close_last > open_last and lower_wick >= body_last * 1.8 and lower_wick >= atr_m5 * 0.5

            if is_bull_engulfing:
                triggers.append("M5 Bullish Engulfing Candle")
            elif is_bull_pinbar:
                triggers.append("M5 Bullish Liquidity Rejection Pinbar")

            if triggers:
                recent_m5_low = float(df_m5["low"].tail(6).min())
                return {
                    "triggered": True,
                    "trigger_note": " + ".join(triggers),
                    "swing_extreme": recent_m5_low,
                    "atr_m5": atr_m5,
                }

        elif h1_bias == "BEARISH":
            triggers = []
            # A. Cek Micro CHoCH / BOS M5
            if swing_lows and close_last < swing_lows[-1]["price"] and float(c_prev["close"]) >= swing_lows[-1]["price"]:
                triggers.append("M5 Bearish CHoCH (Structure Shift)")

            # B. Cek Bearish FVG / Displacement M5 baru terbentuk
            if high_last < float(c_prev2["low"]) and float(c_prev["close"]) < float(c_prev["open"]):
                triggers.append("M5 Bearish Displacement + FVG")

            # C. Cek Bearish Engulfing / Strong Rejection Pinbar di M5
            is_bear_engulfing = (
                close_last < open_last
                and float(c_prev["close"]) > float(c_prev["open"])
                and close_last < float(c_prev["open"])
                and body_last >= atr_m5 * 0.45
            )
            upper_wick = high_last - max(open_last, close_last)
            is_bear_pinbar = close_last < open_last and upper_wick >= body_last * 1.8 and upper_wick >= atr_m5 * 0.5

            if is_bear_engulfing:
                triggers.append("M5 Bearish Engulfing Candle")
            elif is_bear_pinbar:
                triggers.append("M5 Bearish Liquidity Rejection Pinbar")

            if triggers:
                recent_m5_high = float(df_m5["high"].tail(6).max())
                return {
                    "triggered": True,
                    "trigger_note": " + ".join(triggers),
                    "swing_extreme": recent_m5_high,
                    "atr_m5": atr_m5,
                }

        return {
            "triggered": False,
            "trigger_note": "Belum ada konfirmasi CHoCH / Displacement di M5",
            "swing_extreme": 0.0,
            "atr_m5": atr_m5,
        }

    def scan_pair(self, pair: str, mtf_data: Dict[str, pd.DataFrame]) -> Tuple[Optional[SMCSetupSignal], Dict]:
        """
        Menjalankan alur lengkap Top-Down Analysis (H1 -> M15 -> M5) pada 1 Pair.
        Mengembalikan: (SMCSetupSignal jika ada setup valid, Dict ringkasan status market)
        """
        df_h1 = mtf_data["H1"]
        df_m15 = mtf_data["M15"]
        df_m5 = mtf_data["M5"]
        cfg = PAIRS_CONFIG[pair]
        decimals = cfg["decimals"]

        # 1. Analisa H1
        h1_info = self.analyze_h1_bias(df_h1)
        bias = h1_info["bias"]

        # 2. Analisa M15 POI
        m15_info = self.analyze_m15_poi(df_m15, h1_bias=bias)

        # 3. Analisa M5 Trigger
        m5_info = self.analyze_m5_trigger(df_m5, h1_bias=bias)

        current_price = float(df_m5["close"].iloc[-1])
        last_ts = str(df_m5["timestamp"].iloc[-1])

        diagnostics = {
            "pair": pair,
            "price": round(current_price, decimals),
            "h1_bias": bias,
            "h1_structure": h1_info["structure_note"],
            "h1_zone": h1_info["zone"],
            "m15_active": m15_info["active"],
            "m15_poi": m15_info["poi_type"],
            "m5_triggered": m5_info["triggered"],
            "m5_trigger": m5_info["trigger_note"],
        }

        if not (m15_info["active"] and m5_info["triggered"]):
            return None, diagnostics

        # 4. Kalkulasi Entry, Stop Loss, Take Profit, dan Ukuran Lot Presisi
        atr_buffer = m5_info["atr_m5"] * cfg["atr_sl_WaitMs_multiplier"]
        direction = "BUY" if bias == "BULLISH" else "SELL"

        if direction == "BUY":
            raw_sl = min(m5_info["swing_extreme"], m15_info["invalidation_level"]) - atr_buffer
            sl_distance = max(current_price - raw_sl, m5_info["atr_m5"] * 1.2)
            sl_price = current_price - sl_distance
            tp1_price = current_price + (sl_distance * RR_TP1)
            tp2_price = max(current_price + (sl_distance * RR_TP2), h1_info["swing_high"])
            is_optimal_zone = "DISCOUNT" in h1_info["zone"]
        else:
            raw_sl = max(m5_info["swing_extreme"], m15_info["invalidation_level"]) + atr_buffer
            sl_distance = max(raw_sl - current_price, m5_info["atr_m5"] * 1.2)
            sl_price = current_price + sl_distance
            tp1_price = current_price - (sl_distance * RR_TP1)
            tp2_price = min(current_price - (sl_distance * RR_TP2), h1_info["swing_low"])
            is_optimal_zone = "PREMIUM" in h1_info["zone"]

        sl_pips = sl_distance / cfg["pip_size"]
        risk_usd = ACCOUNT_BALANCE * (RISK_PERCENT / 100.0)
        raw_lot = risk_usd / (sl_pips * cfg["pip_value_per_lot"]) if sl_pips > 0 else 0.01
        recommended_lot = max(0.01, round(raw_lot, 2))

        setup_grade = "A+ (Full MTF + Optimal Zone)" if is_optimal_zone else "A (MTF SMC Alignment)"

        signal = SMCSetupSignal(
            pair=pair,
            direction=direction,
            setup_grade=setup_grade,
            h1_structure=h1_info["structure_note"],
            h1_zone=h1_info["zone"],
            m15_poi_type=m15_info["poi_type"],
            m15_poi_zone=(round(m15_info["zone"][0], decimals), round(m15_info["zone"][1], decimals)),
            m5_trigger=m5_info["trigger_note"],
            entry_price=round(current_price, decimals),
            stop_loss=round(sl_price, decimals),
            tp1=round(tp1_price, decimals),
            tp2=round(tp2_price, decimals),
            sl_pips=round(sl_pips, 1),
            recommended_lot=recommended_lot,
            risk_usd=round(risk_usd, 2),
            timestamp=last_ts,
        )

        return signal, diagnostics
