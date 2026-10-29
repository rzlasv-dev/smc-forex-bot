import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import threading
import time
from typing import Dict
from ai_analyst import InstitutionalAIAnalyst
from config import (
    ACTIVE_END_HOUR_UTC,
    ACTIVE_START_HOUR_UTC,
    COOLDOWN_MINUTES,
    ONLY_ACTIVE_SESSIONS,
    PAIRS_CONFIG,
)
from data_feed import MarketDataFeed
from smc_engine import SMCEngine, SMCSetupSignal
from whatsapp_notifier import WhatsAppMultiNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SMC_Bot.Main")

COOLDOWN_FILE = os.path.join(os.path.dirname(__file__), "state_cooldown.json")

# State global untuk dipantau via HTTP Dashboard / Healthcheck di Render.com
BOT_STATUS = {
    "service": "SMC Forex & Metals 24/7 Scanner Bot",
    "started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "last_scan_utc": None,
    "market_open": True,
    "pairs_diagnostics": {},
}


class CooldownManager:
    """Mencegah pengiriman sinyal berulang (spam) pada pair & arah yang sama dalam masa cooldown."""

    def __init__(self, filepath: str = COOLDOWN_FILE):
        self.filepath = filepath
        self.state: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.warning(f"Gagal menyimpan state cooldown: {e}")

    def is_on_cooldown(self, pair: str, direction: str) -> bool:
        key = f"{pair}_{direction}"
        last_sent_str = self.state.get(key)
        if not last_sent_str:
            return False
        try:
            last_sent = datetime.fromisoformat(last_sent_str)
            now_utc = datetime.now(timezone.utc)
            return (now_utc - last_sent) < timedelta(minutes=COOLDOWN_MINUTES)
        except Exception:
            return False

    def mark_sent(self, pair: str, direction: str) -> None:
        key = f"{pair}_{direction}"
        self.state[key] = datetime.now(timezone.utc).isoformat()
        self._save()


def is_market_open_and_active_session() -> bool:
    now_utc = datetime.now(timezone.utc)
    # Forex & Metals tutup saat akhir pekan (Sabtu penuh & Minggu sebelum 21:00 UTC)
    if now_utc.weekday() == 5:  # Sabtu
        return False
    if now_utc.weekday() == 6 and now_utc.hour < 21:  # Minggu siang
        return False

    if ONLY_ACTIVE_SESSIONS:
        return ACTIVE_START_HOUR_UTC <= now_utc.hour < ACTIVE_END_HOUR_UTC
    return True


def run_scan_cycle(
    feed: MarketDataFeed,
    engine: SMCEngine,
    ai_analyst: InstitutionalAIAnalyst,
    notifier: WhatsAppMultiNotifier,
    cooldown: CooldownManager,
) -> None:
    logger.info("Memulai siklus scan MTF SMC (H1 -> M15 -> M5) untuk: " + ", ".join(PAIRS_CONFIG.keys()))
    BOT_STATUS["last_scan_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for pair in PAIRS_CONFIG:
        mtf_data = feed.fetch_mtf_data(pair)
        if not mtf_data:
            logger.warning(f"[{pair}] Data MTF tidak tersedia pada siklus ini, lanjut ke pair berikutnya.")
            continue

        signal, diag = engine.scan_pair(pair, mtf_data)
        BOT_STATUS["pairs_diagnostics"][pair] = diag

        logger.info(
            f"[{pair}] Price: {diag['price']} | H1: {diag['h1_bias']} ({diag['h1_zone']}) | "
            f"M15 POI Active: {diag['m15_active']} ({diag['m15_poi']}) | "
            f"M5 Triggered: {diag['m5_triggered']} ({diag['m5_trigger']})"
        )

        if signal is not None:
            if cooldown.is_on_cooldown(signal.pair, signal.direction):
                logger.info(f"[{pair}] Setup {signal.direction} terdeteksi namun masih dalam masa Cooldown.")
                continue

            ai_comment = ai_analyst.generate_commentary(signal)
            wa_message = notifier.format_smc_signal_message(signal, ai_commentary=ai_comment)
            notifier.send_message(wa_message)
            cooldown.mark_sent(signal.pair, signal.direction)


def send_test_notification(
    ai_analyst: InstitutionalAIAnalyst,
    notifier: WhatsAppMultiNotifier,
) -> None:
    logger.info("Mengirim simulasi sinyal SMC A+ (XAUUSD) untuk menguji format & koneksi WhatsApp...")
    dummy_signal = SMCSetupSignal(
        pair="XAUUSD",
        direction="BUY",
        setup_grade="A+ (Full MTF + Optimal Zone)",
        h1_structure="Bullish BOS (Break di atas H1 Swing High 2748.50)",
        h1_zone="DISCOUNT (<50%)",
        m15_poi_type="M15 Bullish Order Block + FVG",
        m15_poi_zone=(2736.20, 2738.80),
        m5_trigger="M5 Bullish CHoCH (Structure Shift) + M5 Bullish Displacement + FVG",
        entry_price=2739.40,
        stop_loss=2734.90,
        tp1=2748.40,
        tp2=2755.15,
        sl_pips=45.0,
        recommended_lot=0.02,
        risk_usd=10.0,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC (TEST)"),
    )
    ai_comment = ai_analyst.generate_commentary(dummy_signal)
    wa_message = notifier.format_smc_signal_message(dummy_signal, ai_commentary=ai_comment)
    notifier.send_message(wa_message)


def sleep_until_next_m5_close() -> None:
    """Menunggu hingga tepat 5 detik setelah penutupan candle M5 berikutnya (:00, :05, :10, dst)."""
    now = datetime.now(timezone.utc)
    minutes_to_next_m5 = 5 - (now.minute % 5)
    next_run = (now + timedelta(minutes=minutes_to_next_m5)).replace(second=5, microsecond=0)
    sleep_sec = max(5.0, (next_run - now).total_seconds())
    logger.info(
        f"Siklus selesai. Menunggu {int(sleep_sec)} detik hingga M5 Candle Close berikutnya "
        f"({next_run.strftime('%H:%M:%S UTC')})..."
    )
    time.sleep(sleep_sec)


class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    """
    HTTP Server ringan khusus untuk Render.com Web Service (Free Tier):
    - GET / atau /status : Menampilkan JSON status analisa terakhir (XAUUSD, XAGUSD, EURUSD)
    - GET /health        : Endpoint ping untuk UptimeRobot / Cron-job.org agar bot aktif 24 jam penuh
    """

    def do_GET(self):
        if self.path in ("/", "/status", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            response_body = json.dumps(BOT_STATUS, indent=2, ensure_ascii=False)
            self.wfile.write(response_body.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Supresi log HTTP rutin agar log konsol tetap fokus pada analisa SMC
        return


def start_render_http_server() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), RenderHealthCheckHandler)
    logger.info(f"🌐 Render HTTP Health & Status Server aktif di port {port} (Endpoint: /health & /status)")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="24/7 Cloud SMC Forex & Metals Scanner Bot (H1+M15+M5)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Jalankan 1 kali scan MTF sekarang juga lalu keluar (untuk testing/cek status market).",
    )
    parser.add_argument(
        "--test-notif",
        action="store_true",
        help="Kirim contoh sinyal SMC A+ ke WhatsApp untuk menguji integrasi gateway.",
    )
    args = parser.parse_args()

    feed = MarketDataFeed()
    engine = SMCEngine()
    ai_analyst = InstitutionalAIAnalyst()
    notifier = WhatsAppMultiNotifier()
    cooldown = CooldownManager()

    if args.test_notif:
        send_test_notification(ai_analyst, notifier)
        return

    if args.once:
        run_scan_cycle(feed, engine, ai_analyst, notifier, cooldown)
        return

    # Jalankan HTTP Health/Status Server di background thread (wajib untuk Render.com Free Web Service)
    http_thread = threading.Thread(target=start_render_http_server, daemon=True)
    http_thread.start()

    logger.info("==========================================================")
    logger.info("🚀 SMC FOREX & METALS 24/7 SCANNER BOT AKTIF (RENDER READY)")
    logger.info("📌 Pair Prioritas : XAUUSD (Gold), XAGUSD (Silver), EURUSD")
    logger.info("📐 Timeframe SMC  : H1 (Bias) + M15 (POI/Sweep) + M5 (Trigger)")
    logger.info("==========================================================")

    while True:
        try:
            market_active = is_market_open_and_active_session()
            BOT_STATUS["market_open"] = market_active
            if market_active:
                run_scan_cycle(feed, engine, ai_analyst, notifier, cooldown)
            else:
                logger.info("Market sedang tutup akhir pekan atau di luar filter jam sesi aktif.")
            sleep_until_next_m5_close()
        except KeyboardInterrupt:
            logger.info("Bot dihentikan secara manual oleh user.")
            break
        except Exception as e:
            logger.error(f"Error tak terduga pada main loop: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
