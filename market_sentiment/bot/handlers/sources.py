"""
Command Handlers — Sources CRUD + Add Source wizard
"""

from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, ContextTypes

from market_sentiment.core.config import logger
from market_sentiment.bot.constants import (
    ADD_NAME,
    ADD_URL,
    ADD_TYPE,
    ADD_CATEGORY,
    SOURCE_TYPES,
    SOURCE_CATEGORIES,
    CATEGORY_EMOJI,
)
from market_sentiment.bot.formatters import escape, format_source_card
from market_sentiment.bot.repositories import (
    load_sources_data,
    add_source_to_store,
    toggle_source_in_store,
)
from market_sentiment.bot.utils import admin_only, _source_inline_buttons


# ═══════════════════════════════════════════════════════════════════════════
# Command Handlers — Sources CRUD
# ═══════════════════════════════════════════════════════════════════════════
@admin_only
async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sources = load_sources_data()
    if not sources:
        await update.message.reply_text("📭 Belum ada sources.\n\n/add_source untuk tambah.")
        return

    active = len([s for s in sources if s.get("is_active", True)])
    await update.message.reply_text(
        f"📡 <b>{len(sources)} Source(s)</b> ({active} active)",
        parse_mode=ParseMode.HTML,
    )
    for source in sources:
        await update.message.reply_text(
            format_source_card(source), parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=_source_inline_buttons(source),
        )

@admin_only
async def cmd_toggle_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Usage: /toggle_source <code>ID</code>", parse_mode=ParseMode.HTML)
        return
    try:
        source_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus angka.")
        return

    source = toggle_source_in_store(source_id)
    if source:
        status = "✅ Active" if source.get("is_active") else "❌ Inactive"
        await update.message.reply_text(
            f"{status}: <b>{escape(source.get('name', '?'))}</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"❌ Source ID {source_id} tidak ditemukan.")

# ═══════════════════════════════════════════════════════════════════════════
# Add Source — Conversation Wizard
# ═══════════════════════════════════════════════════════════════════════════

@admin_only
async def add_source_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📡 <b>Tambah Source Baru</b>\n\n"
        "Step 1/4: Kirim <b>nama</b> source\n"
        "Contoh: <code>CNBC Indonesia</code>\n\n"
        "/cancel untuk batal",
        parse_mode=ParseMode.HTML,
    )
    return ADD_NAME


async def add_source_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Nama tidak boleh kosong. Coba lagi:")
        return ADD_NAME
    context.user_data["new_source_name"] = name
    await update.message.reply_text(
        f"✅ Nama: <b>{escape(name)}</b>\n\n"
        "Step 2/4: Kirim <b>URL feed</b>\n"
        "Contoh: <code>https://www.cnbcindonesia.com/market/rss</code>\n\n"
        "/cancel untuk batal",
        parse_mode=ParseMode.HTML,
    )
    return ADD_URL


async def add_source_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("❌ URL harus diawali http:// atau https://. Coba lagi:")
        return ADD_URL
    context.user_data["new_source_url"] = url
    buttons = [[InlineKeyboardButton(t, callback_data=f"srctype:{t}")] for t in SOURCE_TYPES]
    await update.message.reply_text(
        f"✅ URL: <code>{escape(url)}</code>\n\nStep 3/4: Pilih <b>type</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ADD_TYPE


async def add_source_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    stype = query.data.replace("srctype:", "")
    context.user_data["new_source_type"] = stype
    buttons = [[InlineKeyboardButton(f"{CATEGORY_EMOJI.get(c, '📁')} {c}", callback_data=f"srccat:{c}")] for c in SOURCE_CATEGORIES]
    await query.edit_message_text(
        f"✅ Type: <b>{escape(stype)}</b>\n\nStep 4/4: Pilih <b>category</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ADD_CATEGORY


async def add_source_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    category = query.data.replace("srccat:", "")
    name = context.user_data.pop("new_source_name", "")
    url = context.user_data.pop("new_source_url", "")
    stype = context.user_data.pop("new_source_type", "rss")

    result = add_source_to_store({
        "name": name, "feed_url": url,
        "type": stype, "category": category, "is_active": True,
    })

    if result:
        text = f"✅ <b>Source berhasil ditambahkan!</b>\n\n{format_source_card(result)}\n\n/collect untuk mulai scraping."
    else:
        text = "❌ Gagal menambahkan source."

    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    logger.info("📡 Source added: %s", name)
    return ConversationHandler.END


async def add_source_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_source_name", None)
    context.user_data.pop("new_source_url", None)
    context.user_data.pop("new_source_type", None)
    await update.message.reply_text("❌ Dibatalkan.")
    return ConversationHandler.END
