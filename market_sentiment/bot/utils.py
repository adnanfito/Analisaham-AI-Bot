"""
Utilitas handler — analyze, paginasi list, admin guard, tombol source
"""

from __future__ import annotations

import asyncio

from functools import wraps
from typing import Any, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from market_sentiment.core.config import TELEGRAM_ADMIN_ID, load_env
from market_sentiment.bot.constants import PAGE_SIZE
from market_sentiment.bot.formatters import escape, format_news_list
from market_sentiment.core.browser import BrowserManager
from market_sentiment.llm.analyzer import analyze_single
from market_sentiment.llm.client import GroqClient
from market_sentiment.storage.factory import get_store


# ═══════════════════════════════════════════════════════════════════════════
# Analyze Helper
# ═══════════════════════════════════════════════════════════════════════════


async def _run_analyze(record: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import datetime, timezone
    groq = GroqClient(load_env())
    loop = asyncio.get_event_loop()
    analysis = await loop.run_in_executor(None, analyze_single, groq, record)

    record["status"] = "analyzed"
    record["analysis"] = analysis
    record["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    if analysis.get("category"):
        record["category"] = analysis["category"]
    if analysis.get("ticker"):
        record["ticker"] = analysis["ticker"]
    if analysis.get("sentiment_direction"):
        record["sentiment"] = analysis["sentiment_direction"]

    store = get_store()
    store.update(record)
    BrowserManager.close()
    return record


# ═══════════════════════════════════════════════════════════════════════════
# Paginated List Helper
# ═══════════════════════════════════════════════════════════════════════════


async def _send_news_page(
    message, items: List[Dict[str, Any]], offset: int,
    total: int, list_type: str,
) -> None:
    page_items = items[offset: offset + PAGE_SIZE]
    if not page_items:
        await message.reply_text("📭 Tidak ada berita lagi.")
        return

    text = format_news_list(page_items, offset)

    header_map = {
        "all": "📰 Semua Berita",
        "cat_Market": "📈 Market",
        "cat_Macro": "🏛 Makro",
        "cat_Commodity": "⛏ Komoditas",
        "cat_Sectoral": "🏭 Sektoral",
        "cat_Corporate Action": "🏢 Corporate Action",
        "cat_Disclosure": "📋 Disclosure",
        "search_result": "🔍 Hasil Pencarian",
    }
    header = header_map.get(list_type)
    if not header:
        if list_type.startswith("src_") and items:
            sname = escape(items[0].get("source_name", "Sumber"))
            header = f"📡 {sname}"
        else:
            header = "📰 Berita"

    current_page = (offset // PAGE_SIZE) + 1
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    full_text = (
        f"{header} — {current_page}/{total_pages} "
        f"({total} berita)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{text}\n\n"
        f"💡 /analyze <code>ID</code> untuk analisis"
    )

    buttons = []
    if offset > 0:
        buttons.append(
            InlineKeyboardButton("⬅️ Sebelumnya", callback_data=f"page:{list_type}:{offset - PAGE_SIZE}")
        )
    if offset + PAGE_SIZE < total:
        buttons.append(
            InlineKeyboardButton("➡️ Lanjut", callback_data=f"page:{list_type}:{offset + PAGE_SIZE}")
        )

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    try:
        await message.edit_text(
            full_text, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True, reply_markup=markup,
        )
    except Exception:
        await message.reply_text(
            full_text, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True, reply_markup=markup,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Admin Wrapper
# ═══════════════════════════════════════════════════════════════════════════

def admin_only(func):
    """Decorator untuk membatasi akses hanya ke Admin (TELEGRAM_ADMIN_ID)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Ambil ID Admin dari config
        # Pastikan TELEGRAM_ADMIN_ID di .env sudah diisi ID kamu
        if str(user_id) != str(TELEGRAM_ADMIN_ID):
            await update.message.reply_text("⛔ <b>Akses Ditolak.</b> Kamu bukan admin.", parse_mode=ParseMode.HTML)
            return  # Stop, jangan jalankan fungsi aslinya
            
        return await func(update, context, *args, **kwargs)
    return wrapper
# ═══════════════════════════════════════════════════════════════════════════
# Source Inline Buttons
# ═══════════════════════════════════════════════════════════════════════════
def _source_inline_buttons(source: Dict[str, Any]) -> InlineKeyboardMarkup:
    sid = source.get("id", 0)
    is_active = source.get("is_active", True)
    toggle_label = "❌ Nonaktifkan" if is_active else "✅ Aktifkan"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"src_edit:{sid}"),
            InlineKeyboardButton(toggle_label, callback_data=f"src_toggle:{sid}"),
        ],
        [InlineKeyboardButton("🗑 Hapus", callback_data=f"src_delete:{sid}")],
    ])
