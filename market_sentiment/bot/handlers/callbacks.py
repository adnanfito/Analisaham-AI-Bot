"""
Callback Query Handler (inline buttons)
"""

from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from market_sentiment.core.config import logger
from market_sentiment.bot.constants import SOURCE_TYPES, SOURCE_CATEGORIES, CATEGORY_EMOJI
from market_sentiment.bot.formatters import escape, format_source_card
from market_sentiment.bot.repositories import (
    find_source_by_id_any,
    update_source_in_store,
    toggle_source_in_store,
    delete_source_from_store,
)
from market_sentiment.bot.utils import _send_news_page, _source_inline_buttons
from market_sentiment.storage.factory import get_store


# ═══════════════════════════════════════════════════════════════════════════
# Callback Query Handler
# ═══════════════════════════════════════════════════════════════════════════


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # ── Category selection ────────────────────────────────────────────
    if data.startswith("cat:"):
        cat = data[4:]
        store = get_store()

        if cat == "all":
            items = store.get_all()
            list_type = "all"
        else:
            all_news = store.get_all()
            items = [n for n in all_news if n.get("category") == cat]
            list_type = f"cat_{cat}"

        if not items:
            await query.edit_message_text("📭 Tidak ada berita di kategori ini.")
            return

        context.user_data[f"list_cache_{list_type}"] = items
        await _send_news_page(query.message, items, 0, len(items), list_type)
        
    # ── Source selection (Filter by Source) ───────────────────────────
    elif data.startswith("src:"):
        try:
            source_id = int(data[4:])
        except ValueError:
            source_id = 0

        store = get_store()
        
        # GUNAKAN FUNGSI DB YANG BARU AGAR LEBIH CEPAT
        if hasattr(store, "get_by_source"):
            items = store.get_by_source(source_id)
        else:
            # Fallback kalau belum update db.py
            all_news = store.get_all()
            items = [n for n in all_news if n.get("source_id") == source_id]
            
        list_type = f"src_{source_id}"

        if not items:
            await query.edit_message_text("📭 Tidak ada berita dari sumber ini.")
            return

        context.user_data[f"list_cache_{list_type}"] = items
        await _send_news_page(query.message, items, 0, len(items), list_type)

    # ── Pagination ────────────────────────────────────────────────────
    elif data.startswith("page:"):
        parts = data.split(":")
        list_type = parts[1]
        offset = int(parts[2])

        cache_key = f"list_cache_{list_type}"
        items = context.user_data.get(cache_key)

        if not items:
            store = get_store()
            if list_type == "all":
                items = store.get_all()
            elif list_type.startswith("cat_"):
                cat_name = list_type[4:]
                items = [n for n in store.get_all() if n.get("category") == cat_name]
            elif list_type.startswith("src_"):
                sid = int(list_type[4:])
                if hasattr(store, "get_by_source"):
                    items = store.get_by_source(sid)
                else:
                    items = [n for n in store.get_all() if n.get("source_id") == sid]
            else:
                items = store.get_all()
            context.user_data[cache_key] = items

        await _send_news_page(query.message, items, offset, len(items), list_type)

    # ── Source toggle ─────────────────────────────────────────────────
    elif data.startswith("src_toggle:"):
        source_id = int(data.split(":")[1])
        source = toggle_source_in_store(source_id)
        if source:
            await query.edit_message_text(
                format_source_card(source), parse_mode=ParseMode.HTML,
                reply_markup=_source_inline_buttons(source),
            )

    # ── Source edit ───────────────────────────────────────────────────
    elif data.startswith("src_edit:"):
        source_id = int(data.split(":")[1])
        source = find_source_by_id_any(source_id)
        if source:
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📝 Nama", callback_data=f"srcedit:{source_id}:name"),
                    InlineKeyboardButton("🔗 URL", callback_data=f"srcedit:{source_id}:feed_url"),
                ],
                [
                    InlineKeyboardButton("📁 Type", callback_data=f"srcedit:{source_id}:type"),
                    InlineKeyboardButton("🏷 Category", callback_data=f"srcedit:{source_id}:category"),
                ],
            ])
            await query.edit_message_text(
                f"✏️ <b>Edit Source #{source_id}</b>\n\n{format_source_card(source)}\n\nPilih field:",
                parse_mode=ParseMode.HTML, reply_markup=markup,
            )

    # ── Source edit field ─────────────────────────────────────────────
    elif data.startswith("srcedit:"):
        parts = data.split(":")
        source_id, field = int(parts[1]), parts[2]
        context.user_data["edit_source_id"] = source_id
        context.user_data["edit_field"] = field

        if field == "type":
            buttons = [[InlineKeyboardButton(t, callback_data=f"srcsettype:{source_id}:{t}")] for t in SOURCE_TYPES]
            await query.edit_message_text(
                f"📁 Pilih type baru untuk source #{source_id}:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        elif field == "category":
            buttons = [[InlineKeyboardButton(f"{CATEGORY_EMOJI.get(c, '📁')} {c}", callback_data=f"srcsetcat:{source_id}:{c}")] for c in SOURCE_CATEGORIES]
            await query.edit_message_text(
                f"🏷 Pilih category baru untuk source #{source_id}:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            label = "nama" if field == "name" else "URL"
            await query.edit_message_text(
                f"📝 Kirim <b>{label}</b> baru untuk source #{source_id}:\n\n/cancel untuk batal",
                parse_mode=ParseMode.HTML,
            )

    # ── Source set type ───────────────────────────────────────────────
    elif data.startswith("srcsettype:"):
        parts = data.split(":")
        source_id, new_type = int(parts[1]), parts[2]
        source = update_source_in_store(source_id, {"type": new_type})
        context.user_data.pop("edit_source_id", None)
        context.user_data.pop("edit_field", None)
        if source:
            await query.edit_message_text(
                f"✅ Type updated!\n\n{format_source_card(source)}", parse_mode=ParseMode.HTML,
            )

    # ── Source set category ───────────────────────────────────────────
    elif data.startswith("srcsetcat:"):
        parts = data.split(":")
        source_id, new_cat = int(parts[1]), parts[2]
        source = update_source_in_store(source_id, {"category": new_cat})
        context.user_data.pop("edit_source_id", None)
        context.user_data.pop("edit_field", None)
        if source:
            await query.edit_message_text(
                f"✅ Category updated!\n\n{format_source_card(source)}", parse_mode=ParseMode.HTML,
            )

    # ── Source delete ─────────────────────────────────────────────────
    elif data.startswith("src_delete:"):
        source_id = int(data.split(":")[1])
        source = find_source_by_id_any(source_id)
        if source:
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ya, hapus", callback_data=f"src_del_yes:{source_id}"),
                InlineKeyboardButton("❌ Batal", callback_data=f"src_del_no:{source_id}"),
            ]])
            await query.edit_message_text(
                f"🗑 <b>Hapus source ini?</b>\n\n{format_source_card(source)}",
                parse_mode=ParseMode.HTML, reply_markup=markup,
            )

    elif data.startswith("src_del_yes:"):
        source_id = int(data.split(":")[1])
        source = find_source_by_id_any(source_id)
        name = source.get("name", "?") if source else "?"
        if delete_source_from_store(source_id):
            await query.edit_message_text(
                f"🗑 Source <b>{escape(name)}</b> (#{source_id}) dihapus.",
                parse_mode=ParseMode.HTML,
            )
            logger.info("📡 Source deleted: [%d] %s", source_id, name)
        else:
            await query.edit_message_text("❌ Gagal menghapus source.")

    elif data.startswith("src_del_no:"):
        source_id = int(data.split(":")[1])
        source = find_source_by_id_any(source_id)
        text = f"👍 Batal hapus.\n\n{format_source_card(source)}" if source else "👍 Batal hapus."
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
