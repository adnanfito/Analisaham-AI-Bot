"""
Content Extraction — HTML articles + PDF documents
Supports both sync (CLI) and async (Telegram bot) contexts.
"""

from __future__ import annotations

import base64
import os
import tempfile
from io import BytesIO
from typing import Optional

import requests

from config import MIN_CONTENT_LENGTH, logger
from helpers import clean_text, generate_id, is_cloudflare_blocked


# ---------------------------------------------------------------------------
# PDF Extraction
# ---------------------------------------------------------------------------


def extract_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    import fitz
    text_parts = []
    with fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf") as doc:
        for pg in doc:
            text_parts.append(pg.get_text())
    return clean_text("\n".join(text_parts))


def is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf") or "/pdf/" in url.lower()


# ---------------------------------------------------------------------------
# Selector-based extraction (fallback)
# ---------------------------------------------------------------------------

# Ordered by specificity — more specific selectors first
ARTICLE_SELECTORS = [
    # Bloomberg Technoz
    "div.detail-in",
    "div.article",

    # Common Indonesian news sites
    ".detail__body-text",            # detik.com
    ".read__content",                # kompas.com
    ".article__content",
    ".article-body",
    ".post-content",
    ".entry-content",
    ".story-body",
    ".content-body",
    ".detail-content",
    ".newsDetail",
    '[class*="article-body"]',
    '[class*="article-content"]',
    '[class*="post-content"]',
    '[class*="entry-content"]',
    '[class*="story-body"]',
    '[class*="content-body"]',
    '[class*="detail-content"]',
    '[itemprop="articleBody"]',

    # Generic fallback
    "article",
]


def _extract_from_selectors(html_content: str) -> Optional[str]:
    """Fallback extraction via BeautifulSoup selectors."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")

        for sel in ARTICLE_SELECTORS:
            el = soup.select_one(sel)
            if not el:
                continue

            # Remove noise
            for tag in el.find_all(["script", "style", "nav", "aside", "footer", "iframe", "noscript"]):
                tag.decompose()

            # Remove ads / related articles
            for tag in el.find_all(attrs={"class": lambda c: c and any(
                x in " ".join(c).lower() for x in [
                    "related", "banner", "ads", "promo", "social",
                    "share", "comment", "sidebar", "widget", "tag",
                ]
            )}):
                tag.decompose()

            # Extract paragraphs
            paragraphs = el.find_all("p")
            if paragraphs:
                texts = []
                for p in paragraphs:
                    t = p.get_text(strip=True)
                    # Skip very short / noisy paragraphs
                    if len(t) > 20:
                        texts.append(t)
                text = "\n\n".join(texts)
                if len(text) >= MIN_CONTENT_LENGTH:
                    return text

            # No <p> tags? Try all text
            text = el.get_text(separator="\n", strip=True)
            if len(text) >= MIN_CONTENT_LENGTH:
                return text

        # Last resort: all <p> tags in body
        paragraphs = soup.find_all("p")
        texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
        if texts:
            combined = "\n\n".join(texts)
            if len(combined) >= MIN_CONTENT_LENGTH:
                return combined

    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Standalone browser session (thread-safe)
# ---------------------------------------------------------------------------


def _run_browser_html(url: str) -> Optional[str]:
    """Scrape HTML via standalone Playwright. Thread-safe."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    from newspaper import Article

    stealth = Stealth()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        try:
            context = browser.new_context(
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
            stealth.apply_stealth_sync(page)

            logger.info("    🌐 Browser navigating...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            html_content = page.content()
            title = page.title()

            # Cloudflare retry
            for attempt in range(3):
                if not is_cloudflare_blocked(title) and not is_cloudflare_blocked(html_content):
                    break
                wait_sec = 8 + (attempt * 5)
                logger.info(
                    "    ⏳ Cloudflare challenge (attempt %d/3), waiting %ds...",
                    attempt + 1, wait_sec,
                )
                page.wait_for_timeout(wait_sec * 1000)
                html_content = page.content()
                title = page.title()

            # Cookie/consent wall
            try:
                for selector in [
                    "button:has-text('Accept')",
                    "button:has-text('Setuju')",
                    "button:has-text('Agree')",
                    "[data-testid='close-button']",
                    ".modal-close",
                    "#onetrust-accept-btn-handler",
                ]:
                    btn = page.query_selector(selector)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
            except Exception:
                pass

            # Scroll for lazy-load
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(2000)

            html_content = page.content()
            page.close()
            context.close()

            if html_content and not is_cloudflare_blocked(html_content):
                # Try newspaper3k
                art = Article(url)
                art.set_html(html_content)
                art.parse()
                if art.text and len(art.text) >= MIN_CONTENT_LENGTH:
                    logger.info("    🔓 Scraped via stealth browser (%d chars)", len(art.text))
                    return clean_text(art.text)

                # Fallback: selector extraction
                text = _extract_from_selectors(html_content)
                if text and len(text) >= MIN_CONTENT_LENGTH:
                    logger.info("    🔓 Scraped via browser + selector (%d chars)", len(text))
                    return clean_text(text)

                logger.warning("    ⚠ Browser got HTML but extraction failed")
            else:
                logger.warning("    ⚠ Cloudflare still blocking after retries")

        except Exception as exc:
            logger.error("    ✗ Browser HTML failed: %s", exc)
        finally:
            browser.close()

    return None


def _run_browser_pdf(url: str) -> Optional[str]:
    """Download & extract PDF via standalone Playwright. Thread-safe."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    stealth = Stealth()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        logger.info("    🌐 Browser started for PDF")

        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="id-ID",
                timezone_id="Asia/Jakarta",
                accept_downloads=True,
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            if "idx.co.id" in url:
                page.goto(
                    "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                page.wait_for_timeout(5000)

            # Method A: JavaScript fetch()
            try:
                b64_data = page.evaluate(
                    """async (url) => {
                    try {
                        const resp = await fetch(url, {
                            credentials: 'include',
                            headers: { 'Accept': 'application/pdf' }
                        });
                        if (!resp.ok) return null;
                        const buffer = await resp.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        let binary = '';
                        for (let i = 0; i < bytes.length; i++) {
                            binary += String.fromCharCode(bytes[i]);
                        }
                        return btoa(binary);
                    } catch(e) {
                        return null;
                    }
                }""",
                    url,
                )

                if b64_data:
                    pdf_bytes = base64.b64decode(b64_data)
                    if len(pdf_bytes) > 100:
                        text = extract_pdf_text_from_bytes(pdf_bytes)
                        if text and len(text) >= MIN_CONTENT_LENGTH:
                            logger.info("    �� PDF via JS fetch (%d chars)", len(text))
                            page.close()
                            context.close()
                            return text
            except Exception as exc:
                logger.warning("    ⚠ JS fetch failed: %s", exc)

            # Method B: expect_download
            try:
                with page.expect_download(timeout=30000) as download_info:
                    page.evaluate("(url) => { window.location.href = url; }", url)
                download = download_info.value

                tmp_path = os.path.join(
                    tempfile.gettempdir(), f"idx_{generate_id(url)}.pdf"
                )
                download.save_as(tmp_path)

                with open(tmp_path, "rb") as f:
                    pdf_bytes = f.read()
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

                if pdf_bytes and len(pdf_bytes) > 100:
                    text = extract_pdf_text_from_bytes(pdf_bytes)
                    if text and len(text) >= MIN_CONTENT_LENGTH:
                        logger.info("    📎 PDF via download (%d chars)", len(text))
                        page.close()
                        context.close()
                        return text
            except Exception as exc:
                logger.warning("    ⚠ Download method failed: %s", exc)

            page.close()
            context.close()

        except Exception as exc:
            logger.error("    ✗ Browser PDF failed: %s", exc)
        finally:
            browser.close()

    return None


# ---------------------------------------------------------------------------
# HTML Scraping (requests → stealth browser)
# ---------------------------------------------------------------------------


def _scrape_html(url: str) -> Optional[str]:
    """Scrape HTML: requests + selector → stealth browser fallback."""
    from newspaper import Article

    # 1. requests (cepat)
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
        })
        resp = session.get(url, timeout=15)

        if resp.status_code == 200 and not is_cloudflare_blocked(resp.text):
            # Try newspaper3k first
            art = Article(url)
            art.set_html(resp.text)
            art.parse()
            if art.text and len(art.text) >= MIN_CONTENT_LENGTH:
                logger.info("    🌐 Scraped via requests + newspaper (%d chars)", len(art.text))
                return clean_text(art.text)

            # Fallback: selector extraction
            text = _extract_from_selectors(resp.text)
            if text and len(text) >= MIN_CONTENT_LENGTH:
                logger.info("    🌐 Scraped via requests + selector (%d chars)", len(text))
                return clean_text(text)

        if resp.status_code == 200 and is_cloudflare_blocked(resp.text):
            logger.info("    🔒 Cloudflare detected, switching to browser...")

    except Exception as exc:
        logger.info("    ⚠ Requests failed: %s, trying browser...", exc)

    # 2. Stealth browser (fallback)
    return _run_browser_html(url)


# ---------------------------------------------------------------------------
# PDF Scraping
# ---------------------------------------------------------------------------


def _scrape_pdf(url: str) -> Optional[str]:
    """Download & extract PDF text."""

    # 1. requests
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=30,
        )
        if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", "").lower():
            text = extract_pdf_text_from_bytes(resp.content)
            if text and len(text) >= MIN_CONTENT_LENGTH:
                logger.info("    📎 PDF via requests (%d chars)", len(text))
                return text
    except Exception:
        pass

    # 2. Standalone browser
    logger.info("    🔓 PDF via stealth browser...")
    return _run_browser_pdf(url)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrape_article(url: str) -> Optional[str]:
    """Scrape full article. Auto-detect PDF vs HTML. Thread-safe."""
    if is_pdf_url(url):
        return _scrape_pdf(url)
    return _scrape_html(url)