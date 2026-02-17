"""
Utility / Helper Functions
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

from dateutil import parser as dateutil_parser

from config import CLOUDFLARE_MARKERS


def generate_id(url: str) -> str:
    """Generate short unique ID dari URL. 8 karakter hex."""
    return hashlib.md5(url.encode()).hexdigest()[:8]


def is_cloudflare_blocked(text: str) -> bool:
    """Cek apakah HTML response adalah Cloudflare challenge page."""
    lower = text[:3000].lower()
    return any(marker in lower for marker in CLOUDFLARE_MARKERS)


def clean_text(text: str) -> str:
    """Bersihkan whitespace berlebihan."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def strip_html(html: str) -> str:
    """Strip HTML tags, return plain text."""
    return re.sub(r"<[^>]+>", " ", html).strip()


def similarity(a: str, b: str) -> float:
    """Hitung similarity ratio antara 2 string."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def parse_published_date(entry: dict, source_type: str = "rss") -> str:
    """
    Parse tanggal publish dari RSS, IDX, atau Stockbit secara cerdas.
    Mencegah double-conversion timezone yang membuat waktu loncat.
    """
    from datetime import datetime, timezone, timedelta
    import re
    
    try:
        from dateutil.parser import parse as dateutil_parse
    except ImportError:
        dateutil_parse = None

    # 1. Ambil raw string berdasarkan source_type
    if source_type == "stockbit_api":
        # Stockbit menggunakan 'created' (Contoh: "2026-02-14 13:00:08")
        raw = entry.get("created", "")
    else:
        raw = entry.get("published", "") or entry.get("updated", "")
    
    # 2. Cek apakah ini struct_time dari feedparser (Khusus RSS)
    if "published_parsed" in entry and entry["published_parsed"]:
        import calendar
        ts = calendar.timegm(entry["published_parsed"])
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    
    if not raw or raw == "0000-00-00 00:00:00":
        return datetime.now(timezone.utc).isoformat()

    # Definisi Timezone
    utc = timezone.utc
    wib = timezone(timedelta(hours=7))

    # ---------------------------------------------------------
    # KHUSUS IDX API (Format Epoch Microsoft)
    # ---------------------------------------------------------
    if source_type == "idx_api":
        epoch_match = re.search(r"/Date\((\d+)\)/", raw)
        if epoch_match:
            ts = int(epoch_match.group(1)) / 1000
            return datetime.fromtimestamp(ts, tz=utc).isoformat()

    # ---------------------------------------------------------
    # PARSING STRING (Universal: IDX, Stockbit, RSS)
    # ---------------------------------------------------------
    dt = None

    # Cara 1: dateutil (Paling robust untuk format aneh)
    if dateutil_parse:
        try:
            dt = dateutil_parse(raw)
        except (ValueError, TypeError):
            pass

    # Cara 2: Fallback Manual (Format "2026-02-14 13:00:08" masuk ke sini)
    if dt is None:
        formats = [
            "%Y-%m-%d %H:%M:%S",         # Format Stockbit & DB
            "%Y-%m-%dT%H:%M:%S%z",      # ISO dengan timezone
            "%Y-%m-%dT%H:%M:%SZ",       # ISO UTC
            "%Y-%m-%dT%H:%M:%S",        # ISO Naive
            "%d %b %Y %H:%M:%S",        # Format web
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return datetime.now(utc).isoformat()

    # ---------------------------------------------------------
    # LOGIKA PERBAIKAN TIMEZONE
    # ---------------------------------------------------------
    
    # KASUS A: String punya info timezone (Aware)
    if dt.tzinfo is not None:
        return dt.astimezone(utc).isoformat()

    # KASUS B: String TIDAK punya info timezone (Naive)
    else:
        # Stockbit dan IDX API (jika string) diasumsikan WIB
        if source_type in ["idx_api", "stockbit_api"]:
            dt = dt.replace(tzinfo=wib)
        else:
            # Default RSS biasanya UTC
            dt = dt.replace(tzinfo=utc)
            
        return dt.astimezone(utc).isoformat()


def time_ago(iso_str: str) -> str:
    """Convert ISO timestamp ke '2 jam lalu' format."""
    try:
        dt = dateutil_parser.parse(iso_str)
        now = datetime.now(timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return "baru saja"
        if minutes < 60:
            return f"{minutes} menit lalu"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} jam lalu"
        days = hours // 24
        return f"{days} hari lalu"
    except Exception:
        return ""

def format_published_date(date_str: str) -> str:
    """Format tanggal publish ke format Indonesia yang readable dengan relative time."""
    if not date_str:
        return ""

    try:
        from datetime import datetime, timezone, timedelta

        dt = None

        # ISO format (paling umum dari parse_published_date)
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                break
            except ValueError:
                continue

        if dt is None:
            try:
                from dateutil.parser import parse as dateutil_parse
                dt = dateutil_parse(date_str)
            except Exception:
                return date_str[:19]

        # Pastikan ada timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert ke WIB (UTC+7)
        wib = timezone(timedelta(hours=7))
        dt_wib = dt.astimezone(wib)
        now_wib = datetime.now(wib)

        # Relative time
        diff = now_wib - dt_wib
        total_seconds = int(diff.total_seconds())

        if total_seconds < 0:
            relative = "baru saja"
        elif total_seconds < 60:
            relative = "baru saja"
        elif total_seconds < 3600:
            m = total_seconds // 60
            relative = f"{m} menit lalu"
        elif total_seconds < 86400:
            h = total_seconds // 3600
            relative = f"{h} jam lalu"
        elif diff.days == 1:
            relative = "kemarin"
        elif diff.days < 7:
            relative = f"{diff.days} hari lalu"
        elif diff.days < 30:
            w = diff.days // 7
            relative = f"{w} minggu lalu"
        else:
            relative = None

        # Format hari & bulan Indonesia
        hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        bulan = [
            "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
        ]

        day_name = hari[dt_wib.weekday()]
        date_str_fmt = (
            f"{day_name}, {dt_wib.day} {bulan[dt_wib.month]} {dt_wib.year} "
            f"· {dt_wib.strftime('%H:%M')} WIB"
        )

        if relative:
            return f"{date_str_fmt} ({relative})"
        return date_str_fmt

    except Exception:
        return date_str[:19] if len(date_str) > 19 else date_str