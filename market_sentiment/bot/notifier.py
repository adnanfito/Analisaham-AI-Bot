"""
Notifikasi ke semua subscriber
"""

from __future__ import annotations

import asyncio

from typing import Any, Dict, List

from telegram.constants import ParseMode

from market_sentiment.core.config import TELEGRAM_BOT_TOKEN, logger
from market_sentiment.bot.constants import CATEGORY_EMOJI, EMOJI
from market_sentiment.bot.formatters import escape, format_news_detail
from market_sentiment.bot.repositories import get_active_subscribers
from market_sentiment.core.helpers import format_published_date


# ═══════════════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════════════


async def send_to_all(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    from telegram import Bot
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for chat_id in get_active_subscribers():
        try:
            await bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning("Failed to notify %s: %s", chat_id, exc)


def notify_sync(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(send_to_all(text))
        else:
            loop.run_until_complete(send_to_all(text))
    except RuntimeError:
        asyncio.run(send_to_all(text))


def notify_new_articles(articles: List[Dict[str, Any]]) -> None:
    if not articles:
        return
    lines = [f"🆕 <b>{len(articles)} berita baru!</b>\n"]
    for item in articles[:10]:
        emoji = EMOJI.get(item.get("sentiment", "neutral"), "❓")
        title = escape(item.get("title", "?"))
        news_id = item.get("id", "?")
        cat = escape(item.get("category", "?"))
        cat_emoji = CATEGORY_EMOJI.get(item.get("category", ""), "📁")
        url = item.get("url", "")
        pub = format_published_date(item.get("published_at", ""))
        
        # Ekstrak nama sumber berita
        source = escape(item.get("source_name", "?"))

        lines.append(f"{emoji} <b>{title}</b>")
        # Tambahkan ikon koran (📰) dan nama sumber di antara kategori dan waktu
        lines.append(f"   {cat_emoji} {cat} · 📰 {source} · 🕐 {pub}")
        lines.append(f"   🔗 <a href='{url}'>Baca</a> · <code>{news_id}</code>")
        lines.append("")

    if len(articles) > 10:
        lines.append(f"... dan {len(articles) - 10} lainnya")
    lines.append("\n💡 /analyze <code>ID</code> untuk analisis")
    notify_sync("\n".join(lines))
    
def notify_analysis_result(item: Dict[str, Any]) -> None:
    notify_sync(format_news_detail(item))
