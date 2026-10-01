"""
Command Handlers — News (search, list, category, stats, analyze, collect)
"""

from __future__ import annotations

import asyncio

from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, ContextTypes

from market_sentiment.core.config import load_env
from market_sentiment.bot.constants import SEARCH_KEYWORD, SOURCE_CATEGORIES, CATEGORY_EMOJI
from market_sentiment.bot.formatters import escape, format_news_detail, format_stats_message
from market_sentiment.bot.utils import _run_analyze, _send_news_page, admin_only
from market_sentiment.storage.factory import get_store


# ═══════════════════════════════════════════════════════════════════════════
# Command Handlers — News
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Search News — Conversation Wizard
# ═══════════════════════════════════════════════════════════════════════════

async def cmd_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔍 <b>Pencarian Berita</b>\n\n"
        "Silakan masukkan kata kunci yang ingin dicari\n"
        "(contoh: <code>MSCI</code>, <code>BBCA</code>, <code>Dividen</code>):\n\n"
        "<i>Ketik /cancel untuk membatalkan.</i>",
        parse_mode=ParseMode.HTML
    )
    return SEARCH_KEYWORD

async def handle_search_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyword = update.message.text.strip()
    if not keyword:
        await update.message.reply_text("❌ Kata kunci tidak boleh kosong. Silakan masukkan lagi:")
        return SEARCH_KEYWORD

    msg = await update.message.reply_text(f"⏳ Mencari berita dengan kata kunci: <b>{escape(keyword)}</b>...", parse_mode=ParseMode.HTML)

    store = get_store()
    
    # Gunakan fungsi search_news jika sudah di-update di store.py/db.py
    # Jika tidak, gunakan fallback pencarian manual di memory
    if hasattr(store, "search_news"):
        results = store.search_news(keyword)
    else:
        all_news = store.get_all()
        results = []
        for n in all_news:
            title = n.get("title", "").lower()
            summary = ""
            if n.get("analysis") and isinstance(n["analysis"], dict):
                summary = n["analysis"].get("summary", "").lower()
            
            if keyword.lower() in title or keyword.lower() in summary:
                results.append(n)

    if not results:
        await msg.edit_text(f"📭 Tidak ditemukan berita untuk kata kunci: <b>{escape(keyword)}</b>.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    # Kita simpan hasil pencarian ke cache untuk Pagination (tombol Next/Prev)
    list_type = "search_result"
    context.user_data[f"list_cache_{list_type}"] = results
    
    # Hapus pesan loading dan tampilkan hasilnya menggunakan fungsi list default
    await msg.delete()
    await _send_news_page(update.message, results, 0, len(results), list_type)

    return ConversationHandler.END

async def cmd_search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Pencarian dibatalkan.")
    return ConversationHandler.END


async def cmd_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_store()
    items = store.get_all()
    if not items:
        await update.message.reply_text("📭 Belum ada berita.")
        return
    context.user_data["list_cache_all"] = items
    await _send_news_page(update.message, items, 0, len(items), "all")


async def cmd_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_store()
    all_news = store.get_all()

    cats: Dict[str, int] = {}
    for r in all_news:
        c = r.get("category", "Unknown")
        cats[c] = cats.get(c, 0) + 1

    if not cats:
        await update.message.reply_text("📭 Belum ada berita.")
        return

    buttons = []
    row = []
    for cat in SOURCE_CATEGORIES:
        count = cats.get(cat, 0)
        if count == 0:
            continue
        emoji = CATEGORY_EMOJI.get(cat, "📁")
        row.append(
            InlineKeyboardButton(
                f"{emoji} {cat} ({count})",
                callback_data=f"cat:{cat}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(f"📰 Semua ({len(all_news)})", callback_data="cat:all")
    ])

    await update.message.reply_text(
        "📁 <b>Pilih Kategori</b>\n\n"
        "Tap kategori untuk melihat daftar berita:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

@admin_only
async def cmd_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_store()
    await update.message.reply_text(
        format_stats_message(store.stats(), store.get_all()),
        parse_mode=ParseMode.HTML,
    )


async def cmd_analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> /analyze <code>ID</code>\n\n"
            "Gunakan /list atau /category untuk melihat ID berita.",
            parse_mode=ParseMode.HTML,
        )
        return

    news_id = context.args[0]
    store = get_store()
    record = store.get_by_id(news_id)

    if not record:
        await update.message.reply_text(
            f"❌ ID <code>{escape(news_id)}</code> tidak ditemukan.\n\n"
            "Gunakan /list untuk melihat ID yang tersedia.",
            parse_mode=ParseMode.HTML,
        )
        return

    status = record.get("status", "raw")
    title = escape(record.get("title", "?"))

    if status == "analyzed":
        msg = await update.message.reply_text(
            f"🔄 <b>Re-analyzing...</b>\n\n{title}",
            parse_mode=ParseMode.HTML,
        )
    else:
        msg = await update.message.reply_text(
            f"⏳ <b>Analyzing...</b>\n\n{title}",
            parse_mode=ParseMode.HTML,
        )

    try:
        record = await _run_analyze(record)
        await msg.edit_text(
            format_news_detail(record),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        await msg.edit_text(f"❌ Error: {escape(str(exc))}")
        
async def cmd_source_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_store()
    all_news = store.get_all()

    # Kelompokkan berita berdasarkan source_id dan source_name
    sources_map: Dict[int, Dict[str, Any]] = {}
    for r in all_news:
        sid = r.get("source_id")
        sname = r.get("source_name", "Unknown")
        if not sid:
            continue
        if sid not in sources_map:
            sources_map[sid] = {"name": sname, "count": 0}
        sources_map[sid]["count"] += 1

    if not sources_map:
        await update.message.reply_text("📭 Belum ada berita.")
        return

    buttons = []
    row = []
    # Urutkan berdasarkan jumlah berita terbanyak
    for sid, data in sorted(sources_map.items(), key=lambda x: -x[1]["count"]):
        name = escape(data["name"])
        count = data["count"]
        row.append(
            InlineKeyboardButton(
                f"📡 {name} ({count})",
                callback_data=f"src:{sid}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(f"📰 Semua ({len(all_news)})", callback_data="cat:all")
    ])

    await update.message.reply_text(
        "📡 <b>Pilih Sumber Berita</b>\n\n"
        "Tap sumber untuk melihat daftar berita:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

@admin_only
async def cmd_collect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Mengumpulkan berita baru...")
    try:
        from market_sentiment.pipeline.collect import cmd_collect

        store = get_store()
        before = store.stats().get("total", 0)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, cmd_collect, load_env())

        store = get_store()
        after = store.stats().get("total", 0)
        new_count = after - before

        if new_count > 0:
            await update.message.reply_text(
                f"✅ Ditemukan <b>{new_count} berita baru</b>.\n\n"
                f"Gunakan /list untuk melihat atau /analyze <code>ID</code> untuk analisis.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("📭 Belum ada berita terbaru.")

    except Exception as exc:
        await update.message.reply_text(f"❌ Error: {escape(str(exc))}")

@admin_only
async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menghapus berita lama (> 3 hari)."""
    store = get_store()
    
    # Cek apakah store memiliki method delete_old_news (hanya SupabaseDB yang punya)
    if not hasattr(store, "delete_old_news"):
        await update.message.reply_text("❌ Fitur cleanup hanya tersedia untuk mode Database (Supabase).")
        return

    msg = await update.message.reply_text("⏳ Sedang membersihkan berita lama (> 3 hari)...")

    try:
        # Jalankan di thread terpisah agar tidak memblokir bot
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, store.delete_old_news, 3)

        if count > 0:
            await msg.edit_text(f"🗑 <b>Berhasil!</b>\n\n{count} berita lama telah dihapus dari database.", parse_mode=ParseMode.HTML)
        else:
            await msg.edit_text("✅ Database bersih. Tidak ada berita yang lebih tua dari 3 hari.")
            
    except Exception as exc:
        await msg.edit_text(f"❌ Error: {str(exc)}")
