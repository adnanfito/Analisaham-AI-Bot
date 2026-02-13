"""
CLI Commands — collect, list, analyze, stats
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import logger
from helpers import parse_published_date, time_ago, generate_id
from store import get_store
from state import load_state, save_state
from sources import (
    load_sources,
    parse_feed,
    fetch_idx_announcements,
    get_new_entries,
    extract_rss_summary,
)
from browser import BrowserManager
from llm import GroqClient, filter_news_batch, analyze_single


# ---------------------------------------------------------------------------
# Phase 1-4: Collect → Parse → Filter → Store
# ---------------------------------------------------------------------------


def cmd_collect(groq_api_key: str) -> None:
    """Phase 1-4: Collect → Parse → Filter → Store. Support RSS, IDX, Stockbit JSON."""
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
                from sources import fetch_stockbit_news
                entries = fetch_stockbit_news(feed_url)
            else:
                entries = parse_feed(feed_url)
        except Exception as exc:
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
            # Stockbit API pakai "titleurl" sebagai link
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
                # Stockbit custom
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

    # ════════════════════════════════════════════════════════════════════
    # NEW: SORTING LOGIC (Newest First)
    # ════════════════════════════════════════════════════════════════════
    # Kita urutkan list 'relevant' berdasarkan published_at secara descending (terbaru diatas).
    # Ini memastikan:
    # 1. Disimpan ke DB urut waktu
    # 2. Notifikasi Telegram urut waktu
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
        # inserted_records sudah otomatis urut karena 'relevant' sudah di-sort di atas
        try:
            from bot import notify_new_articles
            notify_new_articles(inserted_records)
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)

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


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def cmd_list(status_filter: Optional[str] = None) -> None:
    store = get_store()

    if status_filter:
        items = store.get_by_status(status_filter)
    else:
        items = store.get_all()

    if not items:
        print("\n  Tidak ada berita.\n")
        return

    status_label = f" ({status_filter})" if status_filter else ""
    print(f"\n{'═' * 70}")
    print(f"  📰 News Feed{status_label} — {len(items)} article(s)")
    print(f"{'═' * 70}\n")

    for item in items:
        news_id = item.get("id", "?")
        status = item.get("status", "?")
        category = item.get("category", "?")
        title = item.get("title", "?")
        source = item.get("source_name", "?")
        pub = item.get("published_at", "")
        ago = time_ago(pub) if pub else ""
        sentiment = item.get("sentiment", "neutral")
        sub_cat = item.get("sub_category", "")

        if status == "analyzed":
            analysis = item.get("analysis", {})
            direction = (
                analysis.get("sentiment_direction", sentiment)
                if analysis
                else sentiment
            )
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(
                direction, "❓"
            )
            status_str = f"{emoji} ANALYZED | {direction.upper()}"
        else:
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(
                sentiment, "❓"
            )
            status_str = f"{emoji} RAW | {sentiment.upper()}"

        cat_display = f"{category}"
        if sub_cat:
            cat_display += f" ({sub_cat})"

        print(f"  ┌─ ID: {news_id}")
        print(f"  │  {status_str} | {cat_display}")
        print(f"  │  {title}")
        print(f"  │  {source} • {ago}")

        if status == "analyzed" and item.get("analysis"):
            analysis = item["analysis"]
            summary = analysis.get("summary", "")
            if summary:
                lines = summary.split("\n")
                for line in lines[:3]:
                    if line.strip():
                        print(f"  │  {line.strip()}")
                if len(lines) > 3:
                    print("  │  ...")
            key_data = analysis.get("key_data", [])
            if key_data:
                print(f"  │  📊 {' | '.join(key_data[:3])}")

        print("  │")
        if status == "raw":
            print(f"  │  → python main.py analyze {news_id}")
        print(f"  └{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


def cmd_analyze(
    groq_api_key: str, target: str, limit: Optional[int] = None
) -> None:
    groq = GroqClient(groq_api_key)
    store = get_store()

    if target == "all":
        items = store.get_by_status("raw", limit=limit)
        if not items:
            print("\n  Tidak ada berita raw untuk dianalisis.\n")
            return
    else:
        item = store.get_by_id(target)
        if not item:
            print(f"\n  ✗ Berita dengan ID '{target}' tidak ditemukan.\n")
            print(
                "  Gunakan 'python main.py list' untuk melihat ID yang tersedia.\n"
            )
            return
        if item.get("status") == "analyzed":
            print(f"\n  ℹ Berita '{target}' sudah dianalisis sebelumnya.")
            print(
                "  Gunakan 'python main.py list analyzed' untuk lihat hasilnya.\n"
            )
            reanalyze = input("  Analyze ulang? (y/n): ").strip().lower()
            if reanalyze != "y":
                return
        items = [item]

    logger.info("═" * 50)
    logger.info("Phase 5: Analyzing %d article(s)...", len(items))

    analyzed = 0

    for i, record in enumerate(items, 1):
        title = record.get("title", "")
        news_id = record.get("id", "?")
        logger.info("─" * 50)
        logger.info("[%d/%d] [%s] %s", i, len(items), news_id, title[:70])

        analysis = analyze_single(groq, record)

        record["status"] = "analyzed"
        record["analysis"] = analysis
        record["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        if analysis.get("category"):
            record["category"] = analysis["category"]
        if analysis.get("ticker"):
            record["ticker"] = analysis["ticker"]
        if analysis.get("sentiment_direction"):
            record["sentiment"] = analysis["sentiment_direction"]

        store.update(record)
        analyzed += 1

        direction = analysis.get("sentiment_direction", "neutral")
        emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(
            direction, "❓"
        )
        print(
            f"\n  {emoji} {direction.upper()} | {analysis.get('category', '?')}"
        )
        print(f"  {analysis.get('sentiment_reasoning', '')}")

        summary = analysis.get("summary", "")
        if summary:
            print()
            for line in summary.split("\n"):
                if line.strip():
                    print(f"  {line.strip()}")

        key_data = analysis.get("key_data", [])
        if key_data:
            print("\n  📊 Key Data:")
            for kd in key_data:
                print(f"     • {kd}")
        print()

        logger.info("    ✓ Analyzed & saved.")

        try:
            from bot import notify_analysis_result
            notify_analysis_result(record)
        except Exception:
            pass

        if i < len(items):
            time.sleep(1)

    BrowserManager.close()
    logger.info("═" * 50)
    logger.info("✓ Done. %d article(s) analyzed.", analyzed)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def cmd_stats() -> None:
    store = get_store()
    stats = store.stats()

    print(f"\n{'═' * 50}")
    print("  📊 News Store Statistics")
    print(f"{'─' * 50}")
    print(f"  Total articles : {stats['total']}")
    print(f"  Raw (pending)  : {stats['raw']}")
    print(f"  Analyzed       : {stats['analyzed']}")
    print(f"{'─' * 50}")

    store_all = store.get_all()

    cats: Dict[str, int] = {}
    for r in store_all:
        c = r.get("category", "Unknown")
        cats[c] = cats.get(c, 0) + 1
    if cats:
        print("\n  📁 By Category:")
        for c, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"     {c:20s} : {count}")

    sub_cats: Dict[str, int] = {}
    for r in store_all:
        sc = r.get("sub_category", "")
        if sc:
            sub_cats[sc] = sub_cats.get(sc, 0) + 1
    if sub_cats:
        print("\n  📋 IDX Sub-category:")
        for sc, count in sorted(sub_cats.items(), key=lambda x: -x[1]):
            print(f"     {sc:20s} : {count}")

    sentiments: Dict[str, int] = {}
    for r in store_all:
        s = r.get("sentiment", "neutral")
        sentiments[s] = sentiments.get(s, 0) + 1
    if sentiments:
        print("\n  📈 Sentiment:")
        emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
        for s, count in sorted(sentiments.items(), key=lambda x: -x[1]):
            print(f"     {emoji_map.get(s, '❓')} {s:10s} : {count}")

    print(f"\n{'═' * 50}\n")