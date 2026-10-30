import logging
from typing import Dict, Optional
import urllib.parse
import requests
from config import (
    ACCOUNT_BALANCE,
    CALLMEBOT_APIKEY,
    CALLMEBOT_PHONE,
    CUSTOM_WA_TARGET,
    CUSTOM_WA_WEBHOOK_URL,
    FONNTE_TARGET,
    FONNTE_TOKEN,
    RISK_PERCENT,
    RR_TP1,
    RR_TP2,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_WA,
    TWILIO_TO_WA,
)
from smc_engine import SMCSetupSignal

logger = logging.getLogger("SMC_Bot.Notifier")


class WhatsAppMultiNotifier:
    """
    Sistem Notifikasi Utama:
    1. TELEGRAM BOT API (Utama - 100% Gratis Selamanya, Instan, Tanpa Limit Kuota)
       Dilengkapi fitur Auto-Detect Chat ID jika user baru mengisi TELEGRAM_BOT_TOKEN
       dan sudah mengirim pesan '/start' ke bot Telegram-nya.
    2. Multi-Gateway WhatsApp (Opsional/Cadangan: Fonnte, CallMeBot, Twilio, Custom Webhook)
    """

    def __init__(self):
        self.cached_tg_chat_id = TELEGRAM_CHAT_ID

    @staticmethod
    def format_smc_signal_message(signal: SMCSetupSignal, ai_commentary: Optional[str] = None) -> str:
        emoji_dir = "🟢 *BUY / LONG*" if signal.direction == "BUY" else "🔴 *SELL / SHORT*"
        msg = (
            f"🚨 *SMC INSTITUTIONAL ALERT: {signal.pair}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Order:* {emoji_dir}\n"
            f"⭐ *Grade:* {signal.setup_grade}\n"
            f"🕒 *Candle Close:* {signal.timestamp}\n\n"
            f"📐 *Multi-Timeframe Confluence:*\n"
            f"• *H1 Bias:* {signal.h1_structure}\n"
            f"• *H1 Dealing Zone:* {signal.h1_zone}\n"
            f"• *M15 POI:* {signal.m15_poi_type} ({signal.m15_poi_zone[0]} - {signal.m15_poi_zone[1]})\n"
            f"• *M5 Trigger:* {signal.m5_trigger}\n\n"
            f"⚡ *Execution Plan (Spot Price):*\n"
            f"• *Instant Entry (Close M5):* `{signal.entry_price}`\n"
            f"• *Optimal Limit (OTE 50%):* `{signal.limit_entry_price}`\n"
            f"• *Stop Loss (SL):* `{signal.stop_loss}` _({signal.sl_pips} pips)_\n"
            f"• *Take Profit 1 (1:{RR_TP1}):* `{signal.tp1}` _(Partial 50% + SL to BEP)_\n"
            f"• *Take Profit 2 (1:{RR_TP2}/HTF):* `{signal.tp2}`\n\n"
            f"⚖️ *Risk & Money Management:*\n"
            f"• *Balance:* ${ACCOUNT_BALANCE:,.0f} (Risk {RISK_PERCENT}% = ${signal.risk_usd})\n"
            f"• *Recommended Lot:* *{signal.recommended_lot} Lot*"
        )

        if ai_commentary:
            msg += f"\n\n🧠 *Catatan AI Institutional Analyst:*\n_{ai_commentary}_"

        return msg

    @staticmethod
    def format_live_market_report(diagnostics_map: Dict[str, Dict], timestamp_str: str) -> str:
        """
        Format laporan analisa market live (Real-Time Spot) untuk XAUUSD, XAGUSD, dan EURUSD
        saat user melakukan tes manual, bukan angka dummy/palsu.
        """
        lines = [
            "📊 *LIVE SMC MARKET RADAR (REAL-TIME SPOT)*",
            f"🕒 *Waktu Scan:* {timestamp_str}",
            "━━━━━━━━━━━━━━━━━━",
        ]
        for pair, d in diagnostics_map.items():
            bias_icon = "🟢 BULLISH" if d["h1_bias"] == "BULLISH" else ("🔴 BEARISH" if d["h1_bias"] == "BEARISH" else "⚪ NEUTRAL")
            poi_status = "✅ *AKTIF di Zona POI*" if d["m15_active"] else "⏳ _Menunggu Harga Masuk Zona POI_"
            m5_status = "🔥 *TERKONFIRMASI*" if d["m5_triggered"] else "⏳ _Menunggu Trigger CHoCH/Displacement_"
            lines.append(
                f"\n🔹 *{pair}* — Spot Price: `{d['price']}`\n"
                f"• *H1 Bias:* {bias_icon} | {d['h1_structure']}\n"
                f"• *H1 Position:* {d['h1_zone']}\n"
                f"• *M15 POI:* {poi_status}\n"
                f"  _({d['m15_poi']})_\n"
                f"• *M5 Trigger:* {m5_status}\n"
                f"  _({d['m5_trigger']})_"
            )

        lines.append(
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🤖 _Bot memantau otomatis 24/5 dan hanya mengirim sinyal ENTRY (BUY/SELL) "
            "saat H1 + M15 + M5 semuanya terkonfirmasi ✅_"
        )
        return "\n".join(lines)

    def send_message(self, text: str) -> bool:
        """
        Mengirim sinyal ke Telegram (Prioritas Utama) serta gateway WhatsApp jika diisi.
        """
        sent_any = False

        # 1. TELEGRAM BOT (UTAMA)
        if TELEGRAM_BOT_TOKEN:
            if self._send_telegram(text):
                sent_any = True

        # 2. CallMeBot WA (Opsional)
        if CALLMEBOT_PHONE and CALLMEBOT_APIKEY:
            if self._send_callmebot(text):
                sent_any = True

        # 3. Fonnte WA (Opsional)
        if FONNTE_TOKEN and FONNTE_TARGET:
            if self._send_fonnte(text):
                sent_any = True

        # 4. Twilio WA (Opsional)
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_TO_WA:
            if self._send_twilio(text):
                sent_any = True

        # 5. Custom Webhook WA (Opsional)
        if CUSTOM_WA_WEBHOOK_URL:
            if self._send_custom_webhook(text):
                sent_any = True

        if not sent_any:
            logger.warning(
                "Belum ada TELEGRAM_BOT_TOKEN yang diisi di .env. "
                "Menampilkan pratinjau pesan sinyal di konsol:\n" + "=" * 50 + f"\n{text}\n" + "=" * 50
            )
        return sent_any

    def _resolve_telegram_chat_id(self) -> Optional[str]:
        """Jika TELEGRAM_CHAT_ID belum diisi, otomatis ambil dari user terakhir yang chat /start ke bot."""
        if self.cached_tg_chat_id:
            return self.cached_tg_chat_id
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("ok") and data.get("result"):
                for update in reversed(data["result"]):
                    msg = update.get("message") or update.get("channel_post")
                    if msg and "chat" in msg and "id" in msg["chat"]:
                        self.cached_tg_chat_id = str(msg["chat"]["id"])
                        logger.info(f"Auto-detected Telegram Chat ID: {self.cached_tg_chat_id}")
                        return self.cached_tg_chat_id
        except Exception as e:
            logger.warning(f"Gagal auto-detect Telegram Chat ID: {e}")
        return None

    def _send_telegram(self, text: str) -> bool:
        chat_id = self._resolve_telegram_chat_id()
        if not chat_id:
            logger.error(
                "TELEGRAM_CHAT_ID belum ditemukan! Silakan buka bot Telegram kamu dan klik Start (/start), "
                "atau isi TELEGRAM_CHAT_ID di Environment Variables."
            )
            return False

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info(f"✅ Notifikasi berhasil dikirim ke Telegram (Chat ID: {chat_id}).")
                return True
            payload.pop("parse_mode", None)
            resp_fallback = requests.post(url, json=payload, timeout=15)
            if resp_fallback.status_code == 200:
                logger.info("✅ Notifikasi berhasil dikirim ke Telegram (Plain mode).")
                return True
            logger.error(f"Telegram gagal ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Telegram exception: {e}")
        return False

    def _send_callmebot(self, text: str) -> bool:
        try:
            encoded_text = urllib.parse.quote(text)
            url = (
                f"https://api.callmebot.com/whatsapp.php?"
                f"phone={CALLMEBOT_PHONE}&text={encoded_text}&apikey={CALLMEBOT_APIKEY}"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                logger.info("Notifikasi WhatsApp terkirim via CallMeBot.")
                return True
            logger.error(f"CallMeBot gagal ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"CallMeBot exception: {e}")
        return False

    def _send_fonnte(self, text: str) -> bool:
        try:
            url = "https://api.fonnte.com/send"
            headers = {"Authorization": FONNTE_TOKEN}
            payload = {
                "target": FONNTE_TARGET,
                "message": text,
                "countryCode": "62",
            }
            resp = requests.post(url, headers=headers, data=payload, timeout=15)
            if resp.status_code == 200 and resp.json().get("status"):
                logger.info("Notifikasi WhatsApp terkirim via Fonnte.")
                return True
            logger.error(f"Fonnte gagal: {resp.text}")
        except Exception as e:
            logger.error(f"Fonnte exception: {e}")
        return False

    def _send_twilio(self, text: str) -> bool:
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
            payload = {
                "From": TWILIO_FROM_WA,
                "To": TWILIO_TO_WA,
                "Body": text,
            }
            resp = requests.post(url, data=payload, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=15)
            if resp.status_code in (200, 201):
                logger.info("Notifikasi WhatsApp terkirim via Twilio.")
                return True
            logger.error(f"Twilio gagal ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Twilio exception: {e}")
        return False

    def _send_custom_webhook(self, text: str) -> bool:
        try:
            payload = {"chatId": CUSTOM_WA_TARGET, "phone": CUSTOM_WA_TARGET, "text": text, "message": text}
            resp = requests.post(CUSTOM_WA_WEBHOOK_URL, json=payload, timeout=15)
            if resp.status_code in (200, 201):
                logger.info("Notifikasi WhatsApp terkirim via Custom Webhook.")
                return True
            logger.error(f"Custom Webhook gagal ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Custom Webhook exception: {e}")
        return False
