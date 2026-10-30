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
    setup_grade: str              # "A+ (Strict Institutional SMC)"
    h1_structure: str             # Detail bias & struktur H1
    h1_zone: str                  # "DISCOUNT" / "PREMIUM" / "EQUILIBRIUM"
    m15_poi_type: str             # Contoh: "Fresh M15 Order Block + Displacement FVG"
    m15_poi_zone: Tuple[float, float]
    m5_trigger: str               # Contoh: "M5 Bullish CHoCH + Displacement FVG (RSI Ideal)"
    entry_price: float            # Harga Market Execution (Candle Close M5)
    stop_loss: float
    tp1: float
    tp2: float
    sl_pips: float
    recommended_lot: float
    risk_usd: float
    timestamp: str
    limit_entry_price: float = 0.0  # Harga Optimal Limit Entry (50% FVG / OTE Retracement)


class SMCEngine:
    """
    Mesin Analisa Smart Money Concepts (SMC) Multi-Timeframe Presisi Tinggi (H1 -> M15 -> M5).
    Filter Ketat Prop-Firm:
    1. H1 Bias wajib selaras antara Swing Structure (BOS/HH-HL) & Institutional EMA 50.
    2. Anti-Pucuk / Anti-Dasar: Dilarang BUY di Extreme Premium (>65%) & dilarang SELL di Extreme Discount (<35%).
    3. M15 POI hanya mengambil Fresh Unmitigated FVG/OB yang lahir dari Displacement Kuat (Body >= 1.0x ATR).
    4. M5 Trigger wajib terkonfirmasi Structure Shift (CHoCH) / Displacement + Filter RSI (Anti-Exhaustion).
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
    def compute_rsi(df: pd.DataFrame, period: int = 14) -> float:
        delta = df["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        return float(val) if not pd.isna(val) else 50.0

    @staticmethod
    def find_swing_points(df: pd.DataFrame, left_right: int = 4) -> Tuple[List[Dict], List[Dict]]:
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
        Step 1: Analisa Struktur Market H1 Ketat (Swing Structure + EMA 50 Orderflow + Dealing Range).
        """
        swing_highs, swing_lows = self.find_swing_points(df_h1, left_right=SWING_LENGTH_H1)
        current_close = float(df_h1["close"].iloc[-1])
        ema50 = float(df_h1["close"].ewm(span=50, adjust=False).mean().iloc[-1])

        recent_high = float(df_h1["high"].tail(36).max())
        recent_low = float(df_h1["low"].tail(36).min())

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh = swing_highs[-1]["price"]
            prev_sh = swing_highs[-2]["price"]
            last_sl = swing_lows[-1]["price"]
            prev_sl = swing_lows[-2]["price"]
            range_high = max(last_sh, recent_high)
            range_low = min(last_sl, recent_low)

            if current_close > last_sh:
                bias = "BULLISH"
                structure_note = f"Bullish BOS (Break H1 Swing High {last_sh:.2f})"
            elif current_close < last_sl:
                bias = "BEARISH"
                structure_note = f"Bearish BOS (Break H1 Swing Low {last_sl:.2f})"
            elif last_sh > prev_sh and last_sl >= prev_sl and current_close >= ema50:
                bias = "BULLISH"
                structure_note = "Bullish Orderflow (H1 HH/HL + Above EMA 50)"
            elif last_sh <= prev_sh and last_sl < prev_sl and current_close <= ema50:
                bias = "BEARISH"
                structure_note = "Bearish Orderflow (H1 LH/LL + Below EMA 50)"
            else:
                bias = "NEUTRAL"
                structure_note = "Sideways / Choppy H1 (Menunggu Break Struktur Jelas)"
        else:
            range_high = recent_high
            range_low = recent_low
            bias = "NEUTRAL"
            structure_note = "Data Swing H1 Belum Cukup"

        dealing_span = max(range_high - range_low, 1e-6)
        pct_in_range = ((current_close - range_low) / dealing_span) * 100.0

        if pct_in_range <= 45.0:
            zone = f"DISCOUNT ({pct_in_range:.0f}% Range)"
        elif pct_in_range >= 55.0:
            zone = f"PREMIUM ({pct_in_range:.0f}% Range)"
        else:
            zone = f"EQUILIBRIUM ({pct_in_range:.0f}% Range)"

        # Filter Anti-Pucuk / Anti-Dasar:
        # Jangan BUY jika harga sudah di atas 65% Dealing Range H1, jangan SELL jika di bawah 35% Dealing Range H1
        zone_valid_for_bias = True
        if bias == "BULLISH" and pct_in_range > 65.0:
            zone_valid_for_bias = False
        elif bias == "BEARISH" and pct_in_range < 35.0:
            zone_valid_for_bias = False

        return {
            "bias": bias,
            "zone_valid": zone_valid_for_bias,
            "structure_note": structure_note,
            "swing_high": range_high,
            "swing_low": range_low,
            "equilibrium": (range_high + range_low) / 2.0,
            "zone": zone,
            "pct_in_range": pct_in_range,
        }

    def detect_fresh_fvg_and_ob(
        self, df: pd.DataFrame, direction: str, atr_val: float, lookback: int = 32
    ) -> List[Dict]:
        """
        Hanya mendeteksi Fresh Fair Value Gap (FVG) & Order Block (OB) berkualitas tinggi:
        - Berusia maksimal `lookback` candle (8 jam di M15, bukan zona basi berhari-hari lalu).
        - Wajib lahir dari Institutional Displacement (Body candle tengah >= 0.9x ATR & Lebar FVG >= 0.2x ATR).
        - Belum ditembus (Unmitigated).
        """
        zones = []
        sub = df.tail(lookback).reset_index(drop=True)
        n = len(sub)
        if n < 10:
            return zones

        min_disp_body = atr_val * 0.90
        min_fvg_gap = atr_val * 0.20

        for i in range(2, n - 1):
            c0_high = float(sub["high"].iloc[i - 2])
            c0_low = float(sub["low"].iloc[i - 2])
            c0_open = float(sub["open"].iloc[i - 2])
            c0_close = float(sub["close"].iloc[i - 2])

            c1_open = float(sub["open"].iloc[i - 1])
            c1_close = float(sub["close"].iloc[i - 1])
            c1_body = abs(c1_close - c1_open)

            c2_high = float(sub["high"].iloc[i])
            c2_low = float(sub["low"].iloc[i])

            if direction == "BULLISH":
                fvg_size = c2_low - c0_high
                if fvg_size >= min_fvg_gap and c1_close > c1_open and c1_body >= min_disp_body:
                    ob_bottom = min(c0_low, float(sub["low"].iloc[i - 1]))
                    fvg_bottom = c0_high
                    fvg_top = c2_low
                    subsequent_closes = sub["close"].iloc[i + 1 :]
                    # Belum ditembus ke bawah oleh body candle berikutnya
                    if len(subsequent_closes) == 0 or subsequent_closes.min() >= ob_bottom:
                        zones.append(
                            {
                                "type": "Fresh M15 Bullish Order Block + Displacement FVG",
                                "bottom": ob_bottom,
                                "top": fvg_top,
                                "fvg_mid": (fvg_bottom + fvg_top) / 2.0,
                                "index": i,
                            }
                        )

            elif direction == "BEARISH":
                fvg_size = c0_low - c2_high
                if fvg_size >= min_fvg_gap and c1_close < c1_open and c1_body >= min_disp_body:
                    ob_top = max(c0_high, float(sub["high"].iloc[i - 1]))
                    fvg_top = c0_low
                    fvg_bottom = c2_high
                    subsequent_closes = sub["close"].iloc[i + 1 :]
                    # Belum ditembus ke atas oleh body candle berikutnya
                    if len(subsequent_closes) == 0 or subsequent_closes.max() <= ob_top:
                        zones.append(
                            {
                                "type": "Fresh M15 Bearish Order Block + Displacement FVG",
                                "bottom": fvg_bottom,
                                "top": ob_top,
                                "fvg_mid": (fvg_bottom + fvg_top) / 2.0,
                                "index": i,
                            }
                        )

        return zones

    def analyze_m15_poi(self, df_m15: pd.DataFrame, h1_bias: str) -> Dict:
        """
        Step 2: Cek apakah harga di M15 baru saja menyentuh Fresh POI (Order Block / Displacement FVG)
        ATAU baru saja melakukan Fresh Liquidity Sweep (Stop Hunt) searah bias H1.
        """
        if h1_bias not in ("BULLISH", "BEARISH"):
            return {
                "active": False,
                "poi_type": "Bias H1 masih Neutral/Sideways",
                "zone": (0.0, 0.0),
                "ote_price": 0.0,
                "invalidation_level": 0.0,
            }

        atr_m15 = self.compute_atr(df_m15, 14)
        recent_bars = df_m15.tail(2)  # Hanya 2 candle M15 terakhir (30 menit terakhir) agar benar-benar Fresh!
        recent_low = float(recent_bars["low"].min())
        recent_high = float(recent_bars["high"].max())
        current_close = float(df_m15["close"].iloc[-1])

        # 1. Cek Fresh Liquidity Sweep (Stop Hunt) di M15
        swing_highs, swing_lows = self.find_swing_points(df_m15.iloc[:-2], left_right=SWING_LENGTH_M15)

        if h1_bias == "BULLISH" and swing_lows:
            last_ssl = swing_lows[-1]["price"]
            sweep_depth = last_ssl - recent_low
            # Ekor menyapu di bawah Swing Low (minimal 0.1x ATR, maksimal 1.5x ATR) lalu close kembali di atasnya
            if (atr_m15 * 0.10) <= sweep_depth <= (atr_m15 * 1.50) and current_close > last_ssl:
                return {
                    "active": True,
                    "poi_type": "M15 Sell-Side Liquidity (SSL) Sweep / Stop Hunt",
                    "zone": (recent_low, last_ssl),
                    "ote_price": last_ssl,
                    "invalidation_level": recent_low,
                }

        if h1_bias == "BEARISH" and swing_highs:
            last_bsl = swing_highs[-1]["price"]
            sweep_depth = recent_high - last_bsl
            if (atr_m15 * 0.10) <= sweep_depth <= (atr_m15 * 1.50) and current_close < last_bsl:
                return {
                    "active": True,
                    "poi_type": "M15 Buy-Side Liquidity (BSL) Sweep / Stop Hunt",
                    "zone": (last_bsl, recent_high),
                    "ote_price": last_bsl,
                    "invalidation_level": recent_high,
                }

        # 2. Cek Mitigasi ke Fresh Unmitigated Order Block / Displacement FVG di M15
        zones = self.detect_fresh_fvg_and_ob(df_m15.iloc[:-1], direction=h1_bias, atr_val=atr_m15, lookback=32)
        buffer = atr_m15 * 0.15

        for z in reversed(zones):
            z_bottom = z["bottom"]
            z_top = z["top"]
            if h1_bias == "BULLISH":
                if recent_low <= (z_top + buffer) and current_close >= z_bottom:
                    return {
                        "active": True,
                        "poi_type": z["type"],
                        "zone": (z_bottom, z_top),
                        "ote_price": z["fvg_mid"],
                        "invalidation_level": min(z_bottom, recent_low),
                    }
            else:
                if recent_high >= (z_bottom - buffer) and current_close <= z_top:
                    return {
                        "active": True,
                        "poi_type": z["type"],
                        "zone": (z_bottom, z_top),
                        "ote_price": z["fvg_mid"],
                        "invalidation_level": max(z_top, recent_high),
                    }

        return {
            "active": False,
            "poi_type": "Menunggu harga masuk ke Fresh M15 FVG/OB atau Sweep Liquidity",
            "zone": (0.0, 0.0),
            "ote_price": 0.0,
            "invalidation_level": 0.0,
        }

    def analyze_m5_trigger(self, df_m5: pd.DataFrame, h1_bias: str) -> Dict:
        """
        Step 3: Konfirmasi Eksekusi Ketat di M5:
        - Wajib ada Structure Shift (CHoCH/BOS) ATAU Displacement FVG + Engulfing/Pinbar Kuat.
        - Wajib lolos filter Momentum RSI (Tidak BUY di pucuk RSI > 70, Tidak SELL di dasar RSI < 30).
        """
        atr_m5 = self.compute_atr(df_m5, 14)
        rsi_m5 = self.compute_rsi(df_m5, 14)
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
            if rsi_m5 > 70.0:
                return {
                    "triggered": False,
                    "trigger_note": f"M5 Overbought (RSI {rsi_m5:.1f} > 70, rawan koreksi)",
                    "swing_extreme": 0.0,
                    "atr_m5": atr_m5,
                }

            triggers = []
            # A. Micro CHoCH / BOS M5 dengan body tegas
            if (
                swing_highs
                and close_last > swing_highs[-1]["price"]
                and float(c_prev["close"]) <= swing_highs[-1]["price"]
                and body_last >= atr_m5 * 0.55
            ):
                triggers.append("M5 Bullish CHoCH (Structure Shift)")

            # B. Bullish Displacement + FVG M5
            if (
                 (low_last - float(c_prev2["high"])) >= atr_m5 * 0.15
                and float(c_prev["close"]) > float(c_prev["open"])
                and close_last > open_last
            ):
                triggers.append("M5 Bullish Displacement + FVG")

            # C. Strong Institutional Bullish Engulfing
            is_bull_engulfing = (
                close_last > open_last
                and float(c_prev["close"]) < float(c_prev["open"])
                and close_last > float(c_prev["high"])
                and body_last >= atr_m5 * 0.70
            )
            if is_bull_engulfing:
                triggers.append("M5 Strong Bullish Engulfing")

            if triggers:
                recent_m5_low = float(df_m5["low"].tail(8).min())
                return {
                    "triggered": True,
                    "trigger_note": f"{' + '.join(triggers)} (RSI M5: {rsi_m5:.0f})",
                    "swing_extreme": recent_m5_low,
                    "atr_m5": atr_m5,
                }

        elif h1_bias == "BEARISH":
            if rsi_m5 < 30.0:
                return {
                    "triggered": False,
                    "trigger_note": f"M5 Oversold (RSI {rsi_m5:.1f} < 30, rawan pantulan)",
                    "swing_extreme": 0.0,
                    "atr_m5": atr_m5,
                }

            triggers = []
            # A. Micro CHoCH / BOS M5 dengan body tegas
            if (
                swing_lows
                and close_last < swing_lows[-1]["price"]
                and float(c_prev["close"]) >= swing_lows[-1]["price"]
                and body_last >= atr_m5 * 0.55
            ):
                triggers.append("M5 Bearish CHoCH (Structure Shift)")

            # B. Bearish Displacement + FVG M5
            if (
                (float(c_prev2["low"]) - high_last) >= atr_m5 * 0.15
                and float(c_prev["close"]) < float(c_prev["open"])
                and close_last < open_last
            ):
                triggers.append("M5 Bearish Displacement + FVG")

            # C. Strong Institutional Bearish Engulfing
            is_bear_engulfing = (
                close_last < open_last
                and float(c_prev["close"]) > float(c_prev["open"])
                and close_last < float(c_prev["low"])
                and body_last >= atr_m5 * 0.70
            )
            if is_bear_engulfing:
                triggers.append("M5 Strong Bearish Engulfing")

            if triggers:
                recent_m5_high = float(df_m5["high"].tail(8).max())
                return {
                    "triggered": True,
                    "trigger_note": f"{' + '.join(triggers)} (RSI M5: {rsi_m5:.0f})",
                    "swing_extreme": recent_m5_high,
                    "atr_m5": atr_m5,
                }

        return {
            "triggered": False,
            "trigger_note": "Belum ada konfirmasi CHoCH / Displacement kuat di M5",
            "swing_extreme": 0.0,
            "atr_m5": atr_m5,
        }

    def scan_pair(self, pair: str, mtf_data: Dict[str, pd.DataFrame]) -> Tuple[Optional[SMCSetupSignal], Dict]:
        """
        Menjalankan alur lengkap Strict Top-Down Analysis (H1 -> M15 -> M5) pada 1 Pair.
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
            "h1_zone_valid": h1_info["zone_valid"],
            "m15_active": m15_info["active"],
            "m15_poi": m15_info["poi_type"],
            "m5_triggered": m5_info["triggered"],
            "m5_trigger": m5_info["trigger_note"],
        }

        if not (h1_info["zone_valid"] and m15_info["active"] and m5_info["triggered"]):
            return None, diagnostics

        # 4. Kalkulasi Entry, Optimal Limit (OTE), Stop Loss, Take Profit, dan Ukuran Lot
        atr_buffer = m5_info["atr_m5"] * cfg["atr_sl_WaitMs_multiplier"]
        direction = "BUY" if bias == "BULLISH" else "SELL"

        if direction == "BUY":
            raw_sl = min(m5_info["swing_extreme"], m15_info["invalidation_level"]) - atr_buffer
            sl_distance = max(current_price - raw_sl, m5_info["atr_m5"] * 1.3)
            sl_price = current_price - sl_distance
            tp1_price = current_price + (sl_distance * RR_TP1)
            tp2_price = max(current_price + (sl_distance * RR_TP2), h1_info["swing_high"])
            limit_entry = max(sl_price + (sl_distance * 0.4), min(current_price, m15_info["ote_price"]))
        else:
            raw_sl = max(m5_info["swing_extreme"], m15_info["invalidation_level"]) + atr_buffer
            sl_distance = max(raw_sl - current_price, m5_info["atr_m5"] * 1.3)
            sl_price = current_price + sl_distance
            tp1_price = current_price - (sl_distance * RR_TP1)
            tp2_price = min(current_price - (sl_distance * RR_TP2), h1_info["swing_low"])
            limit_entry = min(sl_price - (sl_distance * 0.4), max(current_price, m15_info["ote_price"]))

        sl_pips = sl_distance / cfg["pip_size"]
        risk_usd = ACCOUNT_BALANCE * (RISK_PERCENT / 100.0)
        raw_lot = risk_usd / (sl_pips * cfg["pip_value_per_lot"]) if sl_pips > 0 else 0.01
        recommended_lot = max(0.01, round(raw_lot, 2))

        signal = SMCSetupSignal(
            pair=pair,
            direction=direction,
            setup_grade="A+ (Strict Institutional SMC)",
            h1_structure=h1_info["structure_note"],
            h1_zone=h1_info["zone"],
            m15_poi_type=m15_info["poi_type"],
            m15_poi_zone=(round(m15_info["zone"][0], decimals), round(m15_info["zone"][1], decimals)),
            m5_trigger=m5_info["trigger_note"],
            entry_price=round(current_price, decimals),
            limit_entry_price=round(limit_entry, decimals),
            stop_loss=round(sl_price, decimals),
            tp1=round(tp1_price, decimals),
            tp2=round(tp2_price, decimals),
            sl_pips=round(sl_pips, 1),
            recommended_lot=recommended_lot,
            risk_usd=round(risk_usd, 2),
            timestamp=last_ts,
        )

        return signal, diagnostics
