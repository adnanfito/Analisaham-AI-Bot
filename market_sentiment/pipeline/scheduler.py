"""
Scheduler — Cron job untuk auto-collect berita setiap 15 menit.
Kirim notifikasi ke semua subscriber jika ada berita baru.
"""

from __future__ import annotations

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta

from market_sentiment.core.config import logger, load_env

last_collect_time = None  # Variabel global untuk menyimpan waktu terakhir collect selesai

def _job_collect() -> None:
    """Jalankan collect dan notify jika ada berita baru."""
    from market_sentiment.storage.factory import get_store
    from market_sentiment.pipeline.collect import cmd_collect

    try:
        wib = timezone(timedelta(hours=7))
        now = datetime.now(wib).strftime("%H:%M:%S")
        logger.info("⏰ [Scheduler] Running collect job at %s", now)

        store = get_store()
        before = store.stats().get("total", 0)

        groq_api_key = load_env()
        cmd_collect(groq_api_key)

        # Cek berita baru
        store = get_store()
        after = store.stats().get("total", 0)
        new_count = after - before

        if new_count > 0:
            logger.info("⏰ [Scheduler] %d berita baru ditemukan!", new_count)
            # Notifikasi sudah dihandle di cmd_collect → notify_new_articles
        else:
            logger.info("⏰ [Scheduler] Tidak ada berita baru.")

    except Exception as exc:
        logger.error("⏰ [Scheduler] Collect failed: %s", exc)


def start_scheduler() -> None:
    """Mulai scheduler menggunakan APScheduler (Standar Industri)."""
    logger.info("⏰ APScheduler started — Dinamis (Siang 10m, Malam 30m)")

    # 1. Tentukan Zona Waktu (Wajib untuk APScheduler agar akurat)
    wib_tz = pytz.timezone('Asia/Jakarta')
    
    # 2. Inisialisasi Scheduler yang berjalan di background
    scheduler = BackgroundScheduler(timezone=wib_tz)

    # 3. JADWAL SIANG (Jam 06:00 sampai 16:59) -> Tiap 10 Menit
    # Sintaks '*/10' artinya "setiap kelipatan 10 menit"
    scheduler.add_job(
        _job_collect, 
        trigger='cron', 
        hour='6-16', 
        minute='*/10',
        id='job_siang',
        replace_existing=True
    )

    # 4. JADWAL MALAM (Jam 17:00 sampai 23:59, dan 00:00 sampai 05:59) -> Tiap 30 Menit
    scheduler.add_job(
        _job_collect, 
        trigger='cron', 
        hour='17-23', 
        minute='*/30',
        id='job_malam',
        replace_existing=True
    )
    
    scheduler.add_job(
        _job_collect, 
        trigger='cron', 
        hour='0-5', 
        minute='0', 
        id='job_dinihari',
        replace_existing=True
    )

    # 5. Jalankan scheduler!
    scheduler.start()
    
    # (Opsional) Langsung jalankan 1x saat bot baru di-restart
    # Biar kamu tidak usah nunggu jadwal pertama untuk lihat botnya jalan
    logger.info("⏰ Menjalankan _job_collect inisial saat startup...")
    _job_collect()