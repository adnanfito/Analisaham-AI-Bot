"""
Browser Manager — Stealth Playwright browser (singleton)
Supports both sync (CLI) and async (Telegram bot) contexts.
"""

from __future__ import annotations

import asyncio
import time
import threading
from typing import Any, Optional

from config import BROWSER_DELAY, logger
from helpers import is_cloudflare_blocked


class BrowserManager:
    _instance: Optional["BrowserManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._playwright: Any = None
        self._pw_context: Any = None
        self._browser: Any = None
        self._stealth: Any = None
        self._request_count: int = 0
        self._thread_id: Optional[int] = None

    @classmethod
    def get(cls) -> "BrowserManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance._start()
            return cls._instance

    def _start(self) -> None:
        """Start browser di thread yang benar."""
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        self._stealth = Stealth()
        self._pw_context = sync_playwright()
        self._playwright = self._pw_context.start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._thread_id = threading.current_thread().ident
        logger.info("🌐 Stealth browser launched.")

    def fetch_html(self, url: str) -> str:
        """Fetch halaman HTML via stealth browser."""
        if self._request_count > 0:
            logger.info("    ⏳ Waiting %.1fs...", BROWSER_DELAY)
            time.sleep(BROWSER_DELAY)
        self._request_count += 1

        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = context.new_page()
        self._stealth.apply_stealth_sync(page)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            html = page.content()
            title = page.title()

            if is_cloudflare_blocked(title) or is_cloudflare_blocked(html):
                logger.info("    ⏳ Cloudflare challenge, waiting 10s...")
                page.wait_for_timeout(10000)
                html = page.content()

            return html
        finally:
            page.close()
            context.close()

    @classmethod
    def close(cls) -> None:
        with cls._lock:
            if cls._instance:
                try:
                    if cls._instance._browser:
                        cls._instance._browser.close()
                    if cls._instance._playwright:
                        cls._instance._playwright.stop()
                    logger.info("🌐 Browser closed.")
                except Exception:
                    pass
                cls._instance = None


def _run_in_thread(func, *args):
    """Jalankan fungsi sync di thread baru, return result."""
    result = [None]
    error = [None]

    def _worker():
        try:
            result[0] = func(*args)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=120)

    if error[0]:
        raise error[0]
    return result[0]


async def run_sync_in_thread(func, *args):
    """Jalankan fungsi sync (Playwright) di thread terpisah dari async context."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)