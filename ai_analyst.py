import logging
from typing import Optional
from config import GEMINI_API_KEY
from smc_engine import SMCSetupSignal

logger = logging.getLogger("SMC_Bot.AIAnalyst")


class InstitutionalAIAnalyst:
    """
    Modul AI Opsional (Hybrid).
    - Jika GEMINI_API_KEY kosong: Bot berjalan 100% gratis dengan mesin matematika SMC murni.
    - Jika GEMINI_API_KEY diisi: Menggunakan Gemini (`gemini-3.8-flash`) via Interactions API
      untuk memberikan catatan eksekusi & validasi konteks institusional singkat di WhatsApp.
    """

    def __init__(self):
        self.enabled = bool(GEMINI_API_KEY)
        self.client = None
        if self.enabled:
            try:
                from google import genai
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                logger.info("AI Analyst Layer: AKTIF (Gemini 3.8 Flash Institutional Commentary)")
            except Exception as e:
                logger.warning(f"Gagal menginisialisasi google-genai SDK ({e}). Berjalan tanpa AI layer.")
                self.enabled = False
        else:
            logger.info("AI Analyst Layer: NONAKTIF (100% Pure Mathematical SMC Mode - Tanpa API Key)")

    def generate_commentary(self, signal: SMCSetupSignal) -> Optional[str]:
        if not self.enabled or self.client is None:
            return None

        prompt = (
            f"Pair: {signal.pair}\n"
            f"Direction: {signal.direction} ({signal.setup_grade})\n"
            f"H1 Bias & Structure: {signal.h1_structure} | Zone: {signal.h1_zone}\n"
            f"M15 POI: {signal.m15_poi_type} di area {signal.m15_poi_zone[0]} - {signal.m15_poi_zone[1]}\n"
            f"M5 Trigger: {signal.m5_trigger}\n"
            f"Entry: {signal.entry_price} | SL: {signal.stop_loss} ({signal.sl_pips} pips) | TP1: {signal.tp1} | TP2: {signal.tp2}\n"
        )

        try:
            interaction = self.client.interactions.create(
                model="gemini-3.8-flash",
                system_instruction=(
                    "Kamu adalah Institutional Prop-Firm Forex & Gold Trader profesional. "
                    "Berikan ulasan eksekusi super singkat (maksimal 2-3 kalimat padat dalam Bahasa Indonesia) "
                    "mengenai kualitas confluence SMC (H1+M15+M5) di atas dan tips manajemen posisi "
                    "(misal: kapan geser SL ke Breakeven/BEP). Jangan mengulang angka yang sudah tertulis."
                ),
                input=prompt,
            )
            return interaction.output_text.strip() if interaction.output_text else None
        except Exception as e:
            logger.warning(f"AI Analyst skip komentar karena error API: {e}")
            return None
