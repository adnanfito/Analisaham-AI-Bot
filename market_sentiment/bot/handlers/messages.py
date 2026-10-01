"""
Text Message Handler (edit source)
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from market_sentiment.bot.formatters import format_source_card
from market_sentiment.bot.repositories import update_source_in_store


# ═══════════════════════════════════════════════════════════════════════════
# Text Message Handler
# ═══════════════════════════════════════════════════════════════════════════


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    edit_id = context.user_data.get("edit_source_id")
    edit_field = context.user_data.get("edit_field")

    if not edit_id or edit_field not in ("name", "feed_url"):
        return

    new_value = update.message.text.strip()
    if not new_value:
        await update.message.reply_text("❌ Nilai tidak boleh kosong. Coba lagi:")
        return
    if edit_field == "feed_url" and not new_value.startswith("http"):
        await update.message.reply_text("❌ URL harus diawali http:// atau https://. Coba lagi:")
        return

    source = update_source_in_store(edit_id, {edit_field: new_value})
    context.user_data.pop("edit_source_id", None)
    context.user_data.pop("edit_field", None)

    label = "Nama" if edit_field == "name" else "URL"
    if source:
        await update.message.reply_text(
            f"✅ {label} updated!\n\n{format_source_card(source)}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"❌ Gagal update {label}.")
