"""
Pipeline Collect — Phase 1-4: Collect → Parse → Filter → Store
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from market_sentiment.core.config import logger
from market_sentiment.core.helpers import parse_published_date, generate_id
from market_sentiment.storage.factory import get_store
from market_sentiment.storage.state import load_state, save_state
from market_sentiment.collectors.sources import (
    load_sources,
    parse_feed,
    fetch_idx_announcements,
    get_new_entries,
    extract_rss_summary,
)
from market_sentiment.llm.client import GroqClient
from market_sentiment.llm.filter import filter_news_batch
from tenacity import retry, stop_after_attempt, wait_fixed


# ---------------------------------------------------------------------------
# Phase 1-4: Collect → Parse → Filter → Store
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    # Ganti reraise=True dengan retry_error_callback
    retry_error_callback=lambda retry_state: logger.error(
        "❌ Gagal total setelah 3 kali percobaan. Menunggu siklus berikutnya. Error: %s", 
        retry_state.outcome.exception()
    ),
    before_sleep=lambda retry_state: logger.warning(
        "Network error / Collect failed. Retrying in 5 seconds... (Attempt %d/3). Error: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception()
    )
)
def cmd_collect(groq_api_key: str) -> None:
    """Phase 1-4: Collect → Parse → Filter → Store. Support RSS, IDX, Stockbit JSON."""
    
    # --- AWAL DARI KODEMU ASLI ---
    groq = GroqClient(groq_api_key)
    store = get_store()

    is_supabase = hasattr(store, "load_state")
    db = store if is_supabase else None

    sources = load_sources()
    state = load_state(db)
    logger.info("Found %d active source(s).", len(sources))

    all_new: List[Tuple[Dict[str, Any], List[Dict[str, Any]], str]] = []

    # ──────── SCRAPE SEMUA SUMBER ─────────
    for source in sources:
        name = source.get("name", "?")
        feed_url = source.get("feed_url", "")
        sid = str(source.get("id", ""))
        stype = source.get("type", "rss")

        logger.info("Checking: %s [%s]", name, stype)

        try:
            if stype == "idx_api":
                entries = fetch_idx_announcements(feed_url)
            elif stype == "stockbit_api":
                from market_sentiment.collectors.sources import fetch_stockbit_news
                entries = fetch_stockbit_news(feed_url)
            elif stype == "sitemap.xml":
                from market_sentiment.collectors.sources import fetch_investor_sitemap
                entries = fetch_investor_sitemap(feed_url)
            else:
                entries = parse_feed(feed_url)
        except Exception as exc:
            # Error saat fetch data per sumber tidak akan membatalkan seluruh collect,
            # hanya di-skip. Ini perilaku aslimu.
            logger.error("  ✗ Failed: %s", exc)
            continue

        if not entries:
            continue

        last_link = state.get(sid, {}).get("last_top_link")
        new_entries, top_link = get_new_entries(entries, last_link)

        if not new_entries:
            logger.info("  ✓ Up to date.")
            continue

        logger.info("  🆕 %d new.", len(new_entries))
        all_new.append((source, new_entries, top_link))

    if not all_new:
        logger.info("═" * 50)
        logger.info("No new articles. Done.")
        return

    # ──────── PHASE 2: PARSE ENTRY ──────────
    total = sum(len(e) for _, e, _ in all_new)
    logger.info("═" * 50)
    logger.info("Phase 2: Parsing %d entries...", total)

    parsed: List[Dict[str, Any]] = []
    for source, entries, _ in all_new:
        stype = source.get("type", "rss")
        for entry in entries:
            url = entry.get("link") or entry.get("titleurl", "")
            if not url:
                continue
            parsed.append({
                "title": entry.get("title", ""),
                "url": url,
                "published_at": parse_published_date(entry, source_type=stype),
                "source_id": int(source.get("id", 0)),
                "source_name": source.get("name", ""),
                "source_type": stype,
                "_rss_summary": extract_rss_summary(entry),
                "_source_name": source.get("name", ""),
                "_source_category": source.get("category", "Market"),
                "_emiten": entry.get("_emiten", ""),
                "_attachments": entry.get("_attachments", []),
                "_no_pengumuman": entry.get("_no_pengumuman", ""),
                "_jenis": entry.get("_jenis", ""),
                "_perihal": entry.get("_perihal", ""),
                "_sb_postid": entry.get("id", ""),             
                "_sb_content": entry.get("content", ""),       
                "_sb_created": entry.get("created", ""),    
            })

    # ──────── PHASE 3: LLM FILTER ───────────
    logger.info("═" * 50)
    logger.info("Phase 3: LLM Filter (%d entries)...", len(parsed))

    batch_size = 20
    relevant: List[Dict[str, Any]] = []
    filtered_out = 0

    for i in range(0, len(parsed), batch_size):
        batch = parsed[i : i + batch_size]
        logger.info("  Batch %d-%d...", i + 1, min(i + batch_size, len(parsed)))
        result = filter_news_batch(groq, batch)
        relevant.extend(result)
        filtered_out += len(batch) - len(result)
        if i + batch_size < len(parsed):
            time.sleep(1)

    logger.info("  ✓ %d relevant, %d filtered out.", len(relevant), filtered_out)

    relevant.sort(key=lambda x: x.get("published_at", "") or "", reverse=True)

    # ──────── PHASE 4: STORE TO DB ───────────
    logger.info("═" * 50)
    logger.info("Phase 4: Storing (Sorted by Date)...")

    inserted = 0
    skipped = 0
    inserted_records: List[Dict[str, Any]] = []

    for entry in relevant:
        cat = entry.get("_filter_category", entry.get("_source_category", "Market"))
        sentiment = entry.get("_filter_sentiment", "neutral")
        sub_category = entry.get("_filter_sub_category")

        ticker = None
        emiten = entry.get("_emiten", "")
        if emiten and len(emiten) == 4 and emiten.isalpha():
            ticker = emiten.upper()

        url = entry["url"]
        if entry.get("_is_lapkeu"):
            attachments = entry.get("_attachments", [])
            for att in attachments:
                if not att.get("is_lampiran", False):
                    url = att["url"]
                    break
            logger.info("  📊 Lapkeu: using primary PDF only")

        record = {
            "title": entry["title"],
            "url": url,
            "published_at": entry.get("published_at"),
            "source_id": entry.get("source_id"),
            "source_name": entry.get("source_name"),
            "source_type": entry.get("source_type"),
            "category": cat,
            "sentiment": sentiment,
            "ticker": ticker,
            "filter_reason": entry.get("_filter_reason", ""),
            "rss_summary": entry.get("_rss_summary", ""),
            "status": "raw",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "analysis": None,
            "analyzed_at": None,
        }

        if sub_category:
            record["sub_category"] = sub_category

        if store.save(record):
            inserted += 1
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(sentiment, "❓")
            sub_label = f" [{sub_category}]" if sub_category else ""
            logger.info(
                "  %s [%s] %s%s",
                emoji,
                record.get("id", "?")[:8],
                entry["title"][:55],
                sub_label,
            )
            saved = store.get_by_id(generate_id(entry["url"]))
            if saved:
                inserted_records.append(saved)
        else:
            skipped += 1

    # ──────── NOTIF TELEGRAM ────────────────
    if inserted_records:
        try:
            from market_sentiment.bot.notifier import notify_new_articles
            notify_new_articles(inserted_records)
        except Exception as exc:
            # Jika Telegram error (seperti getaddrinfo failed), ini akan me-raise error
            # dan ditangkap oleh decorator @retry di atas, sehingga seluruh fungsi cmd_collect diulang.
            logger.warning("Telegram notification failed: %s", exc)
            raise exc # Sengaja dilempar agar tenacity menangkapnya dan melakukan retry

    # ──────── UPDATE STATE LAST PROCESSED ───
    for source, _, top_link in all_new:
        sid = str(source["id"])
        state[sid] = {
            "last_top_link": top_link,
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
            "name": source.get("name", ""),
        }
    save_state(state, db)

    stats = store.stats()
    logger.info("═" * 50)
    logger.info(
        "✓ Done. New: %d | Skipped: %d | Filtered: %d",
        inserted,
        skipped,
        filtered_out,
    )
    logger.info(
        "  Store: %d total (%d raw, %d analyzed)",
        stats["total"],
        stats["raw"],
        stats["analyzed"],
    )
