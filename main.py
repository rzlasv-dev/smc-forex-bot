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
from smc_engine import SMCEngine
from whatsapp_notifier import WhatsAppMultiNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SMC_Bot.Main")

COOLDOWN_FILE = os.path.join(os.path.dirname(__file__), "state_cooldown.json")

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
    send_live_report: bool = False,
) -> None:
    logger.info("Memulai siklus scan Strict MTF SMC (H1 -> M15 -> M5) untuk: " + ", ".join(PAIRS_CONFIG.keys()))
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    BOT_STATUS["last_scan_utc"] = now_str

    all_diagnostics: Dict[str, Dict] = {}

    for pair in PAIRS_CONFIG:
        mtf_data = feed.fetch_mtf_data(pair)
        if not mtf_data:
            logger.warning(f"[{pair}] Data MTF tidak tersedia pada siklus ini, lanjut ke pair berikutnya.")
            continue

        signal, diag = engine.scan_pair(pair, mtf_data)
        BOT_STATUS["pairs_diagnostics"][pair] = diag
        all_diagnostics[pair] = diag

        logger.info(
            f"[{pair}] Spot Price: {diag['price']} | H1: {diag['h1_bias']} ({diag['h1_zone']}) | "
            f"M15 POI Active: {diag['m15_active']} ({diag['m15_poi']}) | "
            f"M5 Triggered: {diag['m5_triggered']} ({diag['m5_trigger']})"
        )

        if signal is not None:
            if cooldown.is_on_cooldown(signal.pair, signal.direction):
                logger.info(f"[{pair}] Setup {signal.direction} terdeteksi namun masih dalam masa Cooldown.")
                continue

            ai_comment = ai_analyst.generate_commentary(signal)
            msg = notifier.format_smc_signal_message(signal, ai_commentary=ai_comment)
            notifier.send_message(msg)
            cooldown.mark_sent(signal.pair, signal.direction)

    # Jika dipicu manual (--test-notif / tombol Run workflow di GitHub), kirimkan Laporan Market Real-Time (bukan angka dummy!)
    if send_live_report and all_diagnostics:
        report_msg = notifier.format_live_market_report(all_diagnostics, now_str)
        notifier.send_message(report_msg)


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
    def do_GET(self):
        if self.path in ("/", "/status", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            response_body = json.dumps(BOT_STATUS, indent=2, ensure_ascii=False)
            self.wfile.write(response_body.encode("utf-8"))
        elif self.path == "/test-notif":
            run_scan_cycle(
                MarketDataFeed(),
                SMCEngine(),
                InstitutionalAIAnalyst(),
                WhatsAppMultiNotifier(),
                CooldownManager(),
                send_live_report=True,
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "status": "sent",
                        "message": "Laporan analisa market Real-Time Spot telah dikirim ke Telegram.",
                    },
                    indent=2,
                ).encode("utf-8")
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_render_http_server() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), RenderHealthCheckHandler)
    logger.info(f"🌐 HTTP Health & Status Server aktif di port {port}")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="24/7 Cloud SMC Forex & Metals Scanner Bot (H1+M15+M5)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Jalankan 1 kali scan MTF sekarang juga (hanya kirim notif jika ada setup A+).",
    )
    parser.add_argument(
        "--test-notif",
        action="store_true",
        help="Jalankan scan market Real-Time Spot sekarang juga dan kirimkan Laporan Radar SMC Live ke Telegram.",
    )
    args = parser.parse_args()

    feed = MarketDataFeed()
    engine = SMCEngine()
    ai_analyst = InstitutionalAIAnalyst()
    notifier = WhatsAppMultiNotifier()
    cooldown = CooldownManager()

    if args.test_notif:
        run_scan_cycle(feed, engine, ai_analyst, notifier, cooldown, send_live_report=True)
        return

    if args.once:
        run_scan_cycle(feed, engine, ai_analyst, notifier, cooldown, send_live_report=False)
        return

    http_thread = threading.Thread(target=start_render_http_server, daemon=True)
    http_thread.start()

    logger.info("==========================================================")
    logger.info("🚀 STRICT SMC FOREX & METALS 24/7 SCANNER BOT AKTIF")
    logger.info("📌 Pair Prioritas : XAUUSD (Gold Spot), XAGUSD (Silver Spot), EURUSD")
    logger.info("📐 Timeframe SMC  : H1 (Bias & Zone) + M15 (Fresh POI/Sweep) + M5 (Trigger)")
    logger.info("==========================================================")

    while True:
        try:
            market_active = is_market_open_and_active_session()
            BOT_STATUS["market_open"] = market_active
            if market_active:
                run_scan_cycle(feed, engine, ai_analyst, notifier, cooldown, send_live_report=False)
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
