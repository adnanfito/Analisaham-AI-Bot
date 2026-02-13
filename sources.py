"""
RSS & IDX Data Sources — Fetch + Parse
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import requests

from config import SOURCES_FILE, SUPABASE_URL, SUPABASE_SERVICE_KEY, logger
from helpers import clean_text, strip_html


# ---------------------------------------------------------------------------
# Source Loading (auto-select Supabase or JSON)
# ---------------------------------------------------------------------------


def load_sources() -> List[Dict[str, Any]]:
    """Load active sources. Auto-select Supabase atau JSON."""
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            from db import SupabaseDB
            db = SupabaseDB()
            sources = db.get_active_sources()
            logger.info("📡 Sources loaded from Supabase (%d active)", len(sources))
            return sources
        except Exception as exc:
            logger.warning("⚠ Supabase sources failed (%s), fallback to JSON", exc)

    # Fallback: JSON
    if not SOURCES_FILE.exists():
        logger.critical("sources.json not found!")
        sys.exit(1)
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        sources = json.load(f)
    return [s for s in sources if s.get("is_active", True)]


# ---------------------------------------------------------------------------
# RSS Parsing
# ---------------------------------------------------------------------------


def parse_feed(feed_url: str) -> List[Dict[str, Any]]:
    feed = feedparser.parse(feed_url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Failed to parse feed: {feed.bozo_exception}")
    return feed.entries


# def extract_rss_summary(entry: Dict[str, Any]) -> str:
#     for content_item in entry.get("content", []):
#         text = strip_html(content_item.get("value", ""))
#         if text:
#             return clean_text(text)[:500]
#     summary = entry.get("summary", "")
#     text = strip_html(summary)
#     if text:
#         return clean_text(text)[:500]
#     return ""

def extract_rss_summary(entry: Dict[str, Any]) -> str:
    """
    Extract clean summary from entry. 
    Handles both RSS (list of dicts) and API/Stockbit (string) content formats.
    """
    # 1. Cek field 'content'
    raw_content = entry.get("content")
    
    # KASUS A: Content adalah STRING (misal: Stockbit API)
    if isinstance(raw_content, str):
        return clean_text(strip_html(raw_content))[:500]

    # KASUS B: Content adalah LIST (misal: RSS Feedparser)
    # Biasanya formatnya: [{'type': 'text/html', 'value': '...'}]
    if isinstance(raw_content, list):
        for content_item in raw_content:
            # Pastikan item di dalam list adalah dict sebelum di-.get()
            if isinstance(content_item, dict):
                text = strip_html(content_item.get("value", ""))
                if text:
                    return clean_text(text)[:500]

    # 2. Fallback ke field 'summary' (biasanya RSS punya ini jika content kosong)
    summary = entry.get("summary", "")
    if summary:
        text = strip_html(summary)
        return clean_text(text)[:500]

    return ""


# ---------------------------------------------------------------------------
# New Entry Detection
# ---------------------------------------------------------------------------


def get_new_entries(
    entries: List[Dict[str, Any]], last_top_link: Optional[str]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not entries:
        return [], None
    current_top_link = entries[0].get("link")
    if not last_top_link:
        return entries, current_top_link
    if current_top_link == last_top_link:
        return [], current_top_link
    new_entries: List[Dict[str, Any]] = []
    for entry in entries:
        if entry.get("link") == last_top_link:
            break
        new_entries.append(entry)
    return new_entries, current_top_link


# ---------------------------------------------------------------------------
# IDX Announcements
# ---------------------------------------------------------------------------


def fetch_idx_announcements(api_url: str) -> List[Dict[str, Any]]:
    data = _fetch_idx_via_requests(api_url)

    if data is None:
        logger.info("    🔓 IDX API blocked, using stealth browser...")
        data = _fetch_idx_via_browser(api_url)

    if data is None:
        logger.error("    ✗ IDX API failed (both methods)")
        return []

    return _parse_idx_data(data)


def _fetch_idx_via_requests(api_url: str) -> Optional[Dict[str, Any]]:
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
            "Origin": "https://www.idx.co.id",
            "X-Requested-With": "XMLHttpRequest",
        })

        session.get(
            "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
            timeout=15,
        )

        today = datetime.now().strftime("%Y%m%d")
        url = re.sub(r"dateTo=\d+", f"dateTo={today}", api_url)
        resp = session.get(url, timeout=30)

        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            return None

        return resp.json()

    except Exception:
        return None


def _fetch_idx_via_browser(api_url: str) -> Optional[Dict[str, Any]]:
    import json as _json
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    stealth = Stealth()
    today = datetime.now().strftime("%Y%m%d")
    url = re.sub(r"dateTo=\d+", f"dateTo={today}", api_url)

    api_data = []

    def _on_response(response):
        if "GetAnnouncement" in response.url:
            try:
                body = response.text()
                parsed = _json.loads(body)
                api_data.append(parsed)
            except Exception:
                pass

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
            page.on("response", _on_response)

            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)

            if api_data:
                logger.info("    ✓ IDX API intercepted via browser")
                page.close()
                context.close()
                return api_data[0]

            try:
                body_text = page.inner_text("body")
                page.close()
                context.close()
                return _json.loads(body_text)
            except Exception:
                pass

            page.close()
            context.close()
            return None

        except Exception as exc:
            logger.error("    ✗ IDX browser error: %s", exc)
            return None

        finally:
            browser.close()


def _parse_idx_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    replies = data.get("Replies", [])

    if not replies:
        results = data.get("Results", data.get("results", []))
        if not results and isinstance(data, list):
            results = data
        replies = [
            {"pengumuman": item, "attachments": item.get("attachments", [])}
            for item in results
        ]

    entries: List[Dict[str, Any]] = []

    for reply in replies:
        pengumuman = reply.get("pengumuman", {})
        attachments = reply.get("attachments", [])

        emiten = pengumuman.get("Kode_Emiten", "").strip()
        if not emiten:
            emiten = pengumuman.get("kode_emiten", "").strip()

        judul = (
            pengumuman.get("JudulPengumuman", "")
            or pengumuman.get("judul", "")
            or pengumuman.get("PerihalPengumuman", "")
            or pengumuman.get("perihal", "")
        ).strip()

        tanggal = (
            pengumuman.get("TglPengumuman", "")
            or pengumuman.get("tanggal", "")
            or pengumuman.get("CreatedDate", "")
        )

        no_pengumuman = pengumuman.get("NoPengumuman", "").strip()
        jenis = pengumuman.get("JenisPengumuman", "").strip()
        perihal = pengumuman.get("PerihalPengumuman", "").strip()

        attachment_links: List[Dict[str, Any]] = []
        for att in attachments:
            pdf_url = att.get("FullSavePath", "")
            if not pdf_url:
                pdf_url = att.get("file_path", att.get("FilePath", ""))
                if pdf_url and not pdf_url.startswith("http"):
                    pdf_url = f"https://www.idx.co.id{pdf_url}"

            original_name = (
                att.get("OriginalFilename", "") or att.get("PDFFilename", "")
            ).strip()

            is_attachment = att.get("IsAttachment", False)

            if pdf_url:
                attachment_links.append({
                    "url": pdf_url,
                    "filename": original_name,
                    "is_lampiran": is_attachment,
                })

        primary_link = ""
        for att in attachment_links:
            if not att["is_lampiran"]:
                primary_link = att["url"]
                break
        if not primary_link and attachment_links:
            primary_link = attachment_links[0]["url"]

        if not primary_link:
            aid = pengumuman.get("Id2", pengumuman.get("Id", ""))
            if aid:
                primary_link = (
                    f"https://www.idx.co.id/id/perusahaan-tercatat/"
                    f"keterbukaan-informasi/{aid}"
                )
            else:
                continue

        title = f"[{emiten}] {judul}" if emiten else judul

        entries.append({
            "link": primary_link,
            "title": title,
            "published": tanggal,
            "_emiten": emiten,
            "_no_pengumuman": no_pengumuman,
            "_jenis": jenis,
            "_perihal": perihal,
            "_attachments": attachment_links,
        })

    logger.info("    📋 Parsed %d IDX announcements", len(entries))
    return entries

def fetch_stockbit_news(feed_url: str) -> list:
    """
    Fetch news from Stockbit API.
    Prioritizes 'titleurl' (external news link) over Stockbit post link.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # 1. Request ke API
        resp = requests.get(feed_url, headers=headers, timeout=15)
        
        if resp.status_code != 200:
            logger.warning("Stockbit API status code: %s", resp.status_code)
            return []

        # 2. Parse JSON
        try:
            js = resp.json()
        except ValueError:
            return []

        # 3. Ambil list data dengan aman
        # Struktur JSON: {"message": "...", "data": [...]}
        data_list = js.get("data", [])
        
        if not isinstance(data_list, list):
            logger.warning("Stockbit API format changed: 'data' is not a list")
            return []

        entries = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            
            post_id = item.get("postid")
            if not post_id:
                continue

            # 4. LOGIKA LINK BERITA (PENTING)
            # Ambil link eksternal (misal: idxchannel.com, cnbcindonesia.com)
            external_link = item.get("titleurl")
            
            # Jika ada link eksternal, pakai itu. Jika tidak, baru pakai link post Stockbit.
            # Field 'link' ini yang nanti dipakai commands.py untuk scraping konten.
            final_link = external_link if external_link else f"https://stockbit.com/post/{post_id}"

            entries.append({
                "id": str(post_id),
                "title": item.get("title") or item.get("content", "")[:100],
                
                # Masukkan ke field 'link' agar sistem membacanya sebagai URL utama
                "link": final_link,
                
                # Simpan field asli untuk referensi (opsional)
                "titleurl": external_link,
                "created": item.get("created", ""),
                "content": item.get("content", ""),
                "source": "Stockbit",
                
                # Username di JSON Anda adalah string "StockbitNews", aman diambil langsung
                "username": item.get("username", "StockbitNews"),
            })
            
        return entries

    except Exception as exc:
        logger.error("Stockbit fetch error: %s", exc)
        return []