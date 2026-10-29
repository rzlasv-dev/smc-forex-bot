# 🚀 24/7 Cloud SMC Forex & Metals Scanner Bot (H1 + M15 + M5)

Bot pemantau market otomatis berbasis **Smart Money Concepts (SMC) Multi-Timeframe** yang dirancang untuk memantau **XAUUSD (Gold)**, **XAGUSD (Silver)**, dan **EURUSD** selama 24 jam penuh (Senin–Jumat) dan mengirimkan *Trading Plan* lengkap ke **WhatsApp**.

---

## 🧠 Arsitektur & Logika Algoritma SMC

Bot berjalan setiap **5 menit (tepat setelah Candle M5 Close)** agar **100% Anti-Repaint**:

1. **H1 Market Structure & Dealing Range (`analyze_h1_bias`)**:
   - Mendeteksi *Fractal Swing High* & *Swing Low* untuk mengidentifikasi **BOS (Break of Structure)** atau **CHoCH**.
   - Memetakan apakah harga saat ini berada di area **Discount (<50%)** atau **Premium (>50%)**.
2. **M15 Point of Interest & Liquidity (`analyze_m15_poi`)**:
   - Mendeteksi **Unmitigated Fair Value Gap (FVG / Imbalance)** dan **Order Block (OB)** yang searah dengan struktur H1.
   - Mendeteksi **Liquidity Sweep (BSL / SSL Stop Hunt)** di M15.
3. **M5 Execution Trigger (`analyze_m5_trigger`)**:
   - Saat harga berada di dalam zona M15 POI, bot menunggu konfirmasi M5 berupa **Micro CHoCH**, **M5 Displacement + FVG**, atau **Engulfing / Rejection Pinbar**.
4. **Auto Risk & Lot Calculator**:
   - Menghitung jarak *Stop Loss* struktural + *ATR Buffer*, target **TP1 (1:2 RR)**, **TP2 (1:3.5 RR / H1 High-Low)**, serta **Ukuran Lot** presisi sesuai nilai kontrak masing-masing pair (`XAUUSD` 100 oz, `XAGUSD` 5,000 oz, `EURUSD` 100,000 unit).

---

## 🔑 Apakah Perlu API Key untuk AI-nya?

**TIDAK WAJIB (Bisa 100% Gratis Tanpa API Key!).**
- **Mesin Utama SMC (`smc_engine.py`)** dihitung menggunakan **algoritma matematika murni (`pandas` & `numpy`)**, sehingga **tidak membutuhkan API Key AI** untuk mendeteksi BOS, CHoCH, Order Block, FVG, maupun Liquidity Sweep.
- Namun, saya juga menyediakan **Layer AI Analyst Opsional (`ai_analyst.py`)** menggunakan **Gemini (`gemini-3.8-flash`)**. Jika kamu mengisi `GEMINI_API_KEY` di `.env`, setiap ada sinyal SMC yang valid, AI akan menambahkan *ulasan singkat ala Institutional Trader* di bagian bawah pesan WhatsApp. Jika dikosongkan, bot tetap berjalan 100% normal!

---

## 🛠️ Cara Menjalankan (Lokal / VPS Cloud)

### 1. Persiapan Environment
```bash
cp .env.example .env
pip install -r requirements.txt
```
Edit file `.env` dan isi salah satu (atau kombinasi) kredensial WhatsApp:
- **CallMeBot (Gratis):** Simpan nomor `+34 644 52 74 88` di kontak WA, kirim pesan `I allow callmebot to send me messages`, lalu masukkan nomor HP dan API Key yang didapat ke `CALLMEBOT_PHONE` & `CALLMEBOT_APIKEY`.
- **Fonnte:** Masukkan `FONNTE_TOKEN` dari dashboard Fonnte dan nomor tujuan di `FONNTE_TARGET`.
- **Twilio / Custom Webhook:** Isi variabel yang sesuai di `.env`.

### 2. Perintah Pengujian & Eksekusi
- **Uji Kirim Pesan Sinyal ke WhatsApp Sekarang:**
  ```bash
  python main.py --test-notif
  ```
- **Jalankan 1 Kali Scan Market Live Sekarang:**
  ```bash
  python main.py --once
  ```
- **Jalankan Mode 24/7 Non-Stop:**
  ```bash
  python main.py
  ```

### 3. Menjalankan 24 Jam di Cloud VPS dengan Docker
```bash
docker compose up -d --build
docker compose logs -f
```
