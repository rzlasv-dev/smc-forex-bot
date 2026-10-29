import logging
from typing import Optional
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
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_WA,
    TWILIO_TO_WA,
)
from smc_engine import SMCSetupSignal

logger = logging.getLogger("SMC_Bot.WhatsApp")


class WhatsAppMultiNotifier:
    """
    Sistem Notifikasi WhatsApp Kombinasi (Multi-Gateway):
    1. CallMeBot API (100% Gratis untuk nomor pribadi)
    2. Fonnte API (Gateway WhatsApp Indonesia)
    3. Twilio WhatsApp API (Cloud Enterprise)
    4. Custom Webhook (WAHA / Baileys / Go-WhatsApp Self-Hosted)

    Otomatis mengirim ke semua provider yang kredensialnya terisi di .env.
    """

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
            f"⚡ *Execution Plan:*\n"
            f"• *Entry Area:* `{signal.entry_price}`\n"
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

    def send_message(self, text: str) -> bool:
        """
        Mengirim pesan ke seluruh channel WhatsApp yang terkonfigurasi.
        Jika belum ada satupun yang dikonfigurasi, tetap mencetak pesan lengkap di terminal log.
        """
        sent_any = False

        # 1. CallMeBot (Gratis)
        if CALLMEBOT_PHONE and CALLMEBOT_APIKEY:
            if self._send_callmebot(text):
                sent_any = True

        # 2. Fonnte (Gateway WA Indonesia)
        if FONNTE_TOKEN and FONNTE_TARGET:
            if self._send_fonnte(text):
                sent_any = True

        # 3. Twilio WhatsApp
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_TO_WA:
            if self._send_twilio(text):
                sent_any = True

        # 4. Custom Webhook (WAHA / Self-hosted)
        if CUSTOM_WA_WEBHOOK_URL:
            if self._send_custom_webhook(text):
                sent_any = True

        if not sent_any:
            logger.warning(
                "Belum ada kredensial WhatsApp yang diisi di .env. "
                "Menampilkan pratinjau pesan WhatsApp di konsol:\n" + "=" * 50 + f"\n{text}\n" + "=" * 50
            )
        return sent_any

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
