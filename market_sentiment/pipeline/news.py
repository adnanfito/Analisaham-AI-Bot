"""
Pipeline News — list, analyze, stats
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, Optional

from market_sentiment.core.config import logger
from market_sentiment.core.helpers import time_ago
from market_sentiment.storage.factory import get_store
from market_sentiment.core.browser import BrowserManager
from market_sentiment.llm.client import GroqClient
from market_sentiment.llm.analyzer import analyze_single


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
            from market_sentiment.bot.notifier import notify_analysis_result
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
