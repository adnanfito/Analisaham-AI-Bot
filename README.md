# Market Sentiment Pipeline

Pipeline otomatis untuk **mengumpulkan berita pasar saham Indonesia**, menyaring berita yang relevan, lalu **menganalisis sentimennya (bullish / bearish / neutral)** menggunakan LLM (Groq). Hasilnya disimpan ke Supabase (atau file JSON lokal) dan dikirim ke pengguna lewat **Telegram bot**.

## Kegunaan

- **Kumpulkan berita** dari banyak sumber sekaligus: RSS portal berita, API keterbukaan informasi IDX, API Stockbit, dan sitemap (mis. investor.id).
- **Saring berita penting.** LLM membuang berita yang tidak relevan untuk investor dan memberi kategori awal.
- **Ambil isi artikel lengkap**, termasuk PDF keterbukaan informasi IDX. Untuk situs yang dilindungi Cloudflare dipakai browser Playwright *stealth*.
- **Analisis mendalam per berita**: ringkasan, arah sentimen dan alasannya, kategori, ticker emiten, tag, serta data kunci (angka penting).
- **Hapus duplikat** berdasarkan URL dan kemiripan judul (threshold 0.75).
- **Notifikasi Telegram** otomatis ke semua subscriber saat ada berita baru atau hasil analisis baru.
- **Kelola sumber berita dari Telegram** (tambah, edit, aktif/nonaktif, hapus) tanpa menyentuh kode.

## Alur Pipeline

```
 ┌──────────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
 │ 1. Collect   │ → │ 2. Parse    │ → │ 3. Filter    │ → │ 4. Store    │ → │ 5. Analyze   │
 │ RSS / IDX /  │   │ judul, tgl, │   │ LLM: relevan │   │ Supabase /  │   │ scrape isi + │
 │ Stockbit /   │   │ ringkasan,  │   │ atau tidak + │   │ JSON lokal, │   │ LLM: summary,│
 │ sitemap      │   │ dedup URL   │   │ kategori     │   │ notif Tele  │   │ sentimen,... │
 └──────────────┘   └─────────────┘   └──────────────┘   └─────────────┘   └──────────────┘
        └────────────── python main.py (collect) ──────────────┘        python main.py analyze
```

Langkah 1–4 dijalankan oleh perintah `collect`. Langkah 5 dijalankan terpisah lewat perintah `analyze` (CLI atau Telegram), karena butuh scraping dan pemanggilan LLM yang lebih berat.

## Struktur Folder

```
market-sentiment/
├── main.py                     # Entry point CLI
├── requirements.txt
├── .env.example                # Template variabel environment
├── data/                       # Data runtime (dibuat otomatis, tidak di-commit)
│   ├── news/                   #   berita (mode JSON lokal), 1 file per berita
│   ├── state.json              #   state collect (mode JSON lokal)
│   ├── sources.json            #   daftar sumber (fallback bot tanpa Supabase)
│   └── subscribers.json        #   subscriber Telegram (fallback tanpa Supabase)
└── market_sentiment/
    ├── core/
    │   ├── config.py           # Konstanta, path, logging, load .env
    │   ├── helpers.py          # Utilitas: ID, parsing tanggal, similarity, strip HTML
    │   └── browser.py          # BrowserManager (Playwright) + helper thread
    ├── collectors/
    │   ├── sources.py          # Load sumber + fetch RSS, IDX API, Stockbit, sitemap
    │   └── scraper.py          # Scrape isi artikel HTML & PDF (requests → browser stealth)
    ├── llm/
    │   ├── client.py           # GroqClient
    │   ├── filter.py           # Phase 3: filter relevansi berita (batch)
    │   └── analyzer.py         # Phase 5: analisis sentimen satu berita
    ├── storage/
    │   ├── supabase_db.py      # Backend Supabase (news, sources, subscribers, state)
    │   ├── json_store.py       # Backend JSON lokal (data/news)
    │   ├── factory.py          # get_store(): pilih Supabase atau JSON otomatis
    │   └── state.py            # load/save state pipeline
    ├── pipeline/
    │   ├── collect.py          # cmd_collect (Phase 1–4, dengan retry)
    │   ├── news.py             # cmd_list, cmd_analyze, cmd_stats
    │   └── scheduler.py        # Jadwal auto-collect (APScheduler)
    └── bot/
        ├── app.py              # run_bot: registrasi handler + menu command
        ├── constants.py        # State percakapan, tipe & kategori sumber, emoji
        ├── repositories.py     # CRUD subscriber & sumber (Supabase / JSON)
        ├── formatters.py       # Format pesan HTML Telegram
        ├── notifier.py         # Kirim notifikasi ke semua subscriber
        ├── utils.py            # Paginasi list, admin_only, helper analyze
        └── handlers/
            ├── general.py      # /start, /help, /subscribe, /unsubscribe
            ├── news.py         # /list, /search, /category, /source, /analyze, /stats, /collect, /cleanup
            ├── sources.py      # /sources, /toggle_source, /add_source
            ├── callbacks.py    # Tombol inline (paging, filter, edit/hapus sumber)
            └── messages.py     # Input teks saat edit sumber
```

## Instalasi

Butuh **Python 3.12** (lihat `.python-version`).

```bash
# 1. Buat & aktifkan virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

# 2. Install dependency
pip install -r requirements.txt

# 3. Install browser untuk Playwright (dipakai saat scraping)
playwright install chromium

# 4. Siapkan konfigurasi
copy .env.example .env         # Windows   (Linux/macOS: cp .env.example .env)
```

Lalu isi `.env`.

## Konfigurasi (`.env`)

| Variabel | Wajib? | Kegunaan |
|---|---|---|
| `GROQ_API_KEY` | Ya | API key Groq untuk filter dan analisis LLM (model `openai/gpt-oss-120b`) |
| `SUPABASE_URL` | Untuk `collect` | URL project Supabase |
| `SUPABASE_SERVICE_KEY` | Untuk `collect` | Service key Supabase |
| `TELEGRAM_BOT_TOKEN` | Untuk bot | Token dari @BotFather |
| `TELEGRAM_ADMIN_ID` | Untuk bot | User ID Telegram admin. Hanya admin yang bisa memakai command 🔒 |
| `TELEGRAM_CHAT_ID` | Opsional | Chat ID yang selalu ikut menerima notifikasi |

Konstanta lain (model LLM, batas token, delay browser, threshold kemiripan judul, kategori valid) ada di [market_sentiment/core/config.py](market_sentiment/core/config.py).

## Penyimpanan Data

Backend dipilih otomatis oleh `get_store()`:

- **Supabase**: dipakai jika `SUPABASE_URL` dan `SUPABASE_SERVICE_KEY` terisi. Tabel yang digunakan: `news`, `sources`, `subscribers`, `pipeline_state`, `news_stats`.
- **JSON lokal**: fallback jika Supabase tidak dikonfigurasi atau gagal. Data disimpan di folder `data/`.

> ⚠️ Perintah **`collect` wajib memakai Supabase**, karena daftar sumber berita aktif dibaca dari tabel `sources`. Perintah `list`, `analyze`, dan `stats` tetap bisa berjalan dengan JSON lokal.
> Fitur `/cleanup` di bot juga hanya tersedia di mode Supabase.

## Penggunaan CLI

Jalankan semua perintah dari root project:

```bash
python main.py                   # Collect berita baru (Phase 1-4)
python main.py list              # Lihat semua berita + ID
python main.py list raw          # Lihat berita yang belum dianalisis
python main.py list analyzed     # Lihat berita yang sudah dianalisis
python main.py analyze <id>      # Analisis satu berita (by ID)
python main.py analyze all       # Analisis semua berita pending
python main.py analyze all 5     # Analisis 5 berita pending terbaru
python main.py stats             # Statistik ringkas (total, kategori, sentimen)
python main.py bot               # Jalankan Telegram bot + scheduler
python main.py help              # Tampilkan bantuan
```

Contoh alur manual:

```bash
python main.py                   # kumpulkan berita
python main.py list raw          # cari ID berita yang menarik, mis. 9f7f6549
python main.py analyze 9f7f6549  # analisis berita tersebut
```

## Telegram Bot

```bash
python main.py bot
```

Perintah ini menjalankan bot (*long polling*) **dan** scheduler auto-collect. Saat start, collect langsung dijalankan sekali, lalu terjadwal (zona waktu WIB):

| Jam | Interval |
|---|---|
| 06:00 – 16:59 | tiap 10 menit |
| 17:00 – 23:59 | tiap 30 menit |
| 00:00 – 05:59 | tiap jam |

Berita baru otomatis dikirim ke semua subscriber.

**Command publik**

| Command | Fungsi |
|---|---|
| `/start` | Mulai bot & otomatis berlangganan notifikasi |
| `/help` | Bantuan |
| `/list` | Baca berita terbaru (dengan paginasi) |
| `/search` | Cari berita berdasarkan kata kunci |
| `/source` | Filter berita per sumber |
| `/category` | Filter berita per kategori |
| `/analyze <id>` | Analisis / tampilkan analisis berita |
| `/subscribe` / `/unsubscribe` | Nyalakan / matikan notifikasi |

**Command admin 🔒** (hanya untuk `TELEGRAM_ADMIN_ID`)

| Command | Fungsi |
|---|---|
| `/stats` | Statistik server |
| `/collect` | Jalankan scraping manual |
| `/cleanup` | Hapus berita lebih dari 3 hari (Supabase) |
| `/sources` | Lihat & kelola sumber (edit, aktif/nonaktif, hapus via tombol) |
| `/add_source` | Wizard tambah sumber baru (nama → URL → tipe → kategori) |
| `/toggle_source <id>` | Aktif/nonaktifkan sumber |

## Sumber Berita

Setiap sumber punya `name`, `feed_url`, `type`, `category`, dan `is_active`. Tipe yang didukung:

| `type` | Keterangan |
|---|---|
| `rss` | Feed RSS/Atom biasa |
| `idx_api` | API keterbukaan informasi Bursa Efek Indonesia (otomatis fallback ke browser jika diblokir) |
| `stockbit_api` | API berita Stockbit |
| `sitemap.xml` | Google News sitemap (mis. investor.id) |

**Kategori:** `Market`, `Macro`, `Commodity`, `Sectoral`, `Corporate Action`, `Disclosure`
**Sentimen:** `bullish` 🟢, `bearish` 🔴, `neutral` ⚪

## Menambah Fitur

- **Jenis sumber baru**: tambahkan fungsi fetch di `collectors/sources.py`, lalu daftarkan cabangnya di `pipeline/collect.py` dan di `SOURCE_TYPES` (`bot/constants.py`).
- **Command bot baru**: buat handler di `bot/handlers/`, lalu daftarkan di `run_bot()` (`bot/app.py`) dan, jika perlu, di menu `post_init()`.
- **Ubah prompt LLM**: `llm/filter.py` (filter) dan `llm/analyzer.py` (analisis).

## Troubleshooting

| Masalah | Solusi |
|---|---|
| `Missing GROQ_API_KEY in .env` | Isi `GROQ_API_KEY` di `.env` (di root project) |
| `Kredensial Supabase tidak ditemukan` saat collect | `collect` butuh `SUPABASE_URL` & `SUPABASE_SERVICE_KEY` |
| Scraping gagal / halaman "Just a moment..." | Situs memakai Cloudflare. Pastikan `playwright install chromium` sudah dijalankan |
| Bot timeout / koneksi lambat | Timeout sudah 30 detik (`bot/app.py`). Cek koneksi atau jalankan ulang |
| `UnicodeEncodeError` di terminal Windows | Jalankan `set PYTHONIOENCODING=utf-8` (CMD) atau `$env:PYTHONIOENCODING="utf-8"` (PowerShell) |
| Bot menolak command admin | Pastikan `TELEGRAM_ADMIN_ID` sama dengan user ID Telegram kamu |
