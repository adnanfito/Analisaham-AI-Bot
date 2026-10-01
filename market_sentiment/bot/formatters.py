"""
Formatter pesan Telegram (HTML)
"""

from __future__ import annotations

import html

from typing import Any, Dict, List

from market_sentiment.bot.constants import CATEGORY_EMOJI, EMOJI
from market_sentiment.bot.repositories import count_active_subscribers, load_sources_data
from market_sentiment.core.helpers import format_published_date


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
def truncate(text: str, max_len: int = 200) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def escape(text: str) -> str:
    return html.escape(str(text)) if text else ""

# ═══════════════════════════════════════════════════════════════════════════
# Formatters
# ═══════════════════════════════════════════════════════════════════════════


def format_source_card(source: Dict[str, Any]) -> str:
    sid = source.get("id", "?")
    name = escape(source.get("name", "?"))
    feed_url = escape(source.get("feed_url", "?"))
    stype = escape(source.get("type", "rss"))
    category = escape(source.get("category", "Market"))
    is_active = source.get("is_active", True)
    status_emoji = "✅" if is_active else "❌"
    type_emoji = "📋" if stype == "idx_api" else "📰"
    return (
        f"{type_emoji} <b>{name}</b>\n"
        f"🆔 ID: <code>{sid}</code>\n"
        f"🔗 {feed_url}\n"
        f"📁 Type: {stype} | Category: {category}\n"
        f"{status_emoji} Status: {'Active' if is_active else 'Inactive'}"
    )


def format_news_list(items: List[Dict[str, Any]], offset: int = 0) -> str:
    """Format list berita dalam 1 bubble. Dengan waktu + link."""
    lines = []
    for i, item in enumerate(items, start=offset + 1):
        emoji = EMOJI.get(item.get("sentiment", "neutral"), "❓")
        status_icon = "✅" if item.get("status") == "analyzed" else "🟡"
        title = escape(item.get("title", "?"))
        news_id = item.get("id", "?")
        cat_emoji = CATEGORY_EMOJI.get(item.get("category", ""), "📁")
        cat = escape(item.get("category", "?"))
        source = escape(item.get("source_name", "?"))
        url = item.get("url", "")
        pub = format_published_date(item.get("published_at", ""))

        lines.append(
            f"<b>{i}.</b> {emoji}{status_icon} <b>{title}</b>\n"
            f"     {cat_emoji} {cat} · {source}\n"
            f"     🕐 {pub}\n"
            f"     🔗 <a href='{url}'>Baca</a> · <code>{news_id}</code>"
        )

    return "\n\n".join(lines)


def format_news_detail(item: Dict[str, Any]) -> str:
    """Format lengkap satu berita (untuk hasil analyze)."""
    news_id = item.get("id", "?")
    status = item.get("status", "raw")
    title = escape(item.get("title", "?"))
    category = escape(item.get("category", "?"))
    sentiment = item.get("sentiment", "neutral")
    sub_cat = item.get("sub_category", "")
    source = escape(item.get("source_name", "?"))
    url = item.get("url", "")
    emoji = EMOJI.get(sentiment, "❓")
    cat_emoji = CATEGORY_EMOJI.get(item.get("category", ""), "📁")
    pub = format_published_date(item.get("published_at", ""))

    cat_display = category
    if sub_cat:
        cat_display += f" — {escape(sub_cat)}"

    lines = [
        f"{emoji} <b>{title}</b>",
        "",
        f"{cat_emoji} {cat_display} · {sentiment.upper()}",
        f"📰 {source}",
    ]

    if pub:
        lines.append(f"🕐 {pub}")

    lines.append(f"🔗 <a href='{url}'>Baca selengkapnya →</a>")

    if status == "analyzed" and item.get("analysis"):
        analysis = item["analysis"]

        summary = analysis.get("summary", "")
        if summary:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            lines.append(escape(summary))

        key_data = analysis.get("key_data", [])
        if key_data:
            lines.append("")
            lines.append("📊 <b>Data Penting</b>")
            for kd in key_data[:7]:
                lines.append(f"  ▸ {escape(kd)}")

        reasoning = analysis.get("sentiment_reasoning", "")
        if reasoning:
            lines.append("")
            lines.append(f"💡 <i>{escape(reasoning)}</i>")

        tags = analysis.get("tags", [])
        if tags:
            lines.append("")
            lines.append(" ".join(f"#{escape(t)}" for t in tags[:6]))

    lines.append("")
    lines.append(f"🆔 <code>{news_id}</code>")

    return "\n".join(lines)


def format_stats_message(stats: Dict[str, int], all_news: List[Dict[str, Any]]) -> str:
    active_subs = count_active_subscribers()
    sources = load_sources_data()
    active_sources = len([s for s in sources if s.get("is_active", True)])

    lines = [
        "📊 <b>Statistik</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📰 Total berita    : <b>{stats['total']}</b>",
        f"🟡 Belum dianalisis : <b>{stats['raw']}</b>",
        f"✅ Sudah dianalisis : <b>{stats['analyzed']}</b>",
        f"👥 Subscriber       : <b>{active_subs}</b>",
        f"📡 Sumber berita    : <b>{active_sources}</b>",
    ]

    cats: Dict[str, int] = {}
    for r in all_news:
        c = r.get("category", "Unknown")
        cats[c] = cats.get(c, 0) + 1
    if cats:
        lines.append("")
        lines.append("📁 <b>Kategori:</b>")
        for c, count in sorted(cats.items(), key=lambda x: -x[1]):
            ce = CATEGORY_EMOJI.get(c, "📁")
            lines.append(f"  {ce} {c}: {count}")

    sentiments: Dict[str, int] = {}
    for r in all_news:
        s = r.get("sentiment", "neutral")
        sentiments[s] = sentiments.get(s, 0) + 1
    if sentiments:
        lines.append("")
        lines.append("📈 <b>Sentimen:</b>")
        for s, count in sorted(sentiments.items(), key=lambda x: -x[1]):
            lines.append(f"  {EMOJI.get(s, '❓')} {s}: {count}")

    return "\n".join(lines)
