"""
Command Handlers — General (start, help, subscribe)
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from market_sentiment.core.config import TELEGRAM_ADMIN_ID, logger
from market_sentiment.bot.formatters import escape
from market_sentiment.bot.repositories import (
    add_subscriber,
    remove_subscriber,
    count_active_subscribers,
)


# ═══════════════════════════════════════════════════════════════════════════
# Command Handlers — General
# ═══════════════════════════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Simpan subscriber baru (logika lama tetap dipakai)
    is_new = add_subscriber(
        update.effective_chat.id,
        user.username or "",
        user.first_name or "",
    )

    # 1. Header Sapaan
    if is_new:
        header = f"👋 Halo <b>{escape(user.first_name or 'Trader')}</b>! Selamat datang.\n"
        header += "✅ Notifikasi berita telah <b>diaktifkan</b>."
    else:
        header = f"👋 Welcome back, <b>{escape(user.first_name or 'Trader')}</b>!"

    # 2. Body: Penjelasan Bot & Fitur
    welcome_msg = (
        f"{header}\n\n"
        "🤖 <b>Market Sentiment Bot</b>\n"
        "Asisten pintar yang memantau berita pasar modal & menganalisis sentimen "
        "menggunakan AI untuk membantu keputusan trading kamu.\n\n"
        "🚀 <b>Apa yang bisa saya lakukan?</b>\n"
        "• 📰 <b>Agregasi Berita:</b> Mengumpulkan info dari IDX, CNBC, Stockbit, dll.\n"
        "• 🧠 <b>AI Analysis:</b> Menentukan sentimen (Bullish/Bearish) berita.\n"
        "• 🔔 <b>Real-time Alert:</b> Mengirim notifikasi berita penting.\n\n"
        "💡 <b>Mulai dari mana?</b>\n"
        "Ketik /list untuk melihat berita terbaru hari ini, atau\n"
        "Ketik /help untuk panduan lengkap perintah."
    )

    await update.message.reply_text(welcome_msg, parse_mode=ParseMode.HTML)

    # Log jika user baru
    if is_new:
        active = count_active_subscribers()
        logger.info(
            "👤 New subscriber: %s (total: %d)",
            user.username or update.effective_chat.id, active,
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 <b>Panduan Lengkap Market Bot</b>\n\n"
        
        "📰 <b>Membaca Berita</b>\n"
        "• /list\n"
        "  Menampilkan daftar semua berita terbaru yang sudah dikumpulkan.\n"
        "• /search\n"
        "  Cari berita berdasarkan kata kunci.\n"
        "• /source\n"
        "  Memilih berita berdasarkan sumber berita (IDX, BloombergTechnoz, dll).\n"
        "• /category\n"
        "  Memilih berita berdasarkan topik (Market, Makro, Komoditas, dll).\n\n"
        
        "🧠 <b>Analisis AI</b>\n"
        "• /analyze <code>ID_BERITA</code>\n"
        "  Meminta AI menganalisis berita secara mendalam.\n"
        "  <i>Contoh:</i> <code>/analyze a1b2c3d4</code>\n"
        "  (Dapatkan <code>ID_BERITA</code> dari perintah /list)\n\n"
        
        "🔔 <b>Langganan</b>\n"
        "• /subscribe : Mengaktifkan notifikasi otomatis.\n"
        "• /unsubscribe : Mematikan notifikasi.\n\n"
        
        "📊 <b>Lainnya</b>\n"
        "• /help : Menampilkan pesan bantuan ini."
    )
    
    # Opsional: Jika user adalah admin, tampilkan menu rahasia
    # (Pastikan variable TELEGRAM_ADMIN_ID sudah di-import dari config)
    if str(update.effective_user.id) == str(TELEGRAM_ADMIN_ID):
        help_text += (
            "\n\n🛠 <b>Admin Commands</b>\n"
            "• /stats : Melihat statistik jumlah berita & kinerja bot.\n"
            "• /collect : Trigger manual scraping.\n"
            "• /cleanup : Hapus data lama (>3 hari).\n"
            "• /sources : Manajemen sumber berita.\n"
            "• /add_source : Tambah sumber baru.\n"
            "• /edit_source <code>ID</code> : Edit sumber.\n"
            "• /delete_source <code>ID</code> : Hapus sumber.\n"
            "• /toggle_source <code>ID</code> : On/Off sumber."
        )

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    add_subscriber(update.effective_chat.id, user.username or "", user.first_name or "")
    await update.message.reply_text("✅ Notifikasi <b>aktif</b>.", parse_mode=ParseMode.HTML)


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remove_subscriber(update.effective_chat.id)
    await update.message.reply_text(
        "🔕 Notifikasi <b>dimatikan</b>. /subscribe untuk aktifkan.",
        parse_mode=ParseMode.HTML,
    )
