"""
Scheduler — Cron job untuk auto-collect berita setiap 15 menit.
Kirim notifikasi ke semua subscriber jika ada berita baru.
"""

from __future__ import annotations

import time
import threading
import schedule
from datetime import datetime, timezone, timedelta

from config import logger, load_env


def _job_collect() -> None:
    """Jalankan collect dan notify jika ada berita baru."""
    from store import get_store
    from commands import cmd_collect

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


def _run_scheduler() -> None:
    """Loop scheduler (blocking, jalankan di thread)."""
    logger.info("⏰ Scheduler started — collect setiap 5 menit")

    # Jalankan pertama kali saat startup (delay 10 detik biar bot siap)
    time.sleep(10)
    _job_collect()

    # Schedule tiap 5 menit
    schedule.every(5).minutes.do(_job_collect)

    while True:
        schedule.run_pending()
        time.sleep(30)


def start_scheduler() -> threading.Thread:
    """Start scheduler di background thread."""
    t = threading.Thread(target=_run_scheduler, daemon=True, name="scheduler")
    t.start()
    logger.info("⏰ Scheduler thread started (daemon)")
    return t