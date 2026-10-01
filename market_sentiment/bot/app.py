"""
Bot Runner — registrasi command & handler, start polling
"""

from __future__ import annotations

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)
from telegram.request import HTTPXRequest

from market_sentiment.core.config import TELEGRAM_ADMIN_ID, TELEGRAM_BOT_TOKEN, logger
from market_sentiment.bot.constants import ADD_NAME, ADD_URL, ADD_TYPE, ADD_CATEGORY, SEARCH_KEYWORD
from market_sentiment.bot.handlers.callbacks import callback_handler
from market_sentiment.bot.handlers.general import (
    cmd_start,
    cmd_help,
    cmd_subscribe,
    cmd_unsubscribe,
)
from market_sentiment.bot.handlers.messages import text_message_handler
from market_sentiment.bot.handlers.news import (
    cmd_search_start,
    handle_search_keyword,
    cmd_search_cancel,
    cmd_list_handler,
    cmd_category_handler,
    cmd_stats_handler,
    cmd_analyze_handler,
    cmd_source_handler,
    cmd_collect_handler,
    cmd_cleanup,
)
from market_sentiment.bot.handlers.sources import (
    cmd_sources,
    cmd_toggle_source,
    add_source_start,
    add_source_name,
    add_source_url,
    add_source_type_cb,
    add_source_cat_cb,
    add_source_cancel,
)


# ═══════════════════════════════════════════════════════════════════════════
# Bot Runner
# ═══════════════════════════════════════════════════════════════════════════

# BOT_COMMANDS = [
#     BotCommand("start", "Menu utama"),
#     BotCommand("help", "Bantuan"),
#     BotCommand("list", "Semua berita"),
#     BotCommand("category", "Berita per kategori"),
#     BotCommand("analyze", "Analyze / re-analyze (+ ID)"),
#     BotCommand("collect", "Collect berita baru"),
#     BotCommand("cleanup", "Hapus berita > 3 hari"),
#     BotCommand("sources", "Lihat semua sources"),
#     BotCommand("add_source", "Tambah source baru"),
#     BotCommand("toggle_source", "Toggle aktif/nonaktif (+ ID)"),
#     BotCommand("stats", "Statistik"),
#     BotCommand("subscribe", "Aktifkan notifikasi"),
#     BotCommand("unsubscribe", "Matikan notifikasi"),
# ]

async def post_init(application) -> None:
    bot = application.bot

    # 1. Menu untuk PUBLIK (User biasa)
    # Mereka hanya bisa lihat menu basic
    public_commands = [
        BotCommand("start", "Mulai bot"),
        BotCommand("help", "Bantuan"),
        BotCommand("list", "Baca berita terbaru"),
        BotCommand("search", "🔍 Cari berita"),
        BotCommand("source", "📡 Pilih sumber berita"),
        BotCommand("category", "📚 Pilih kategori berita"),
        BotCommand("analyze", "Analisa berita"),
        BotCommand("subscribe", "Langganan notifikasi"),
        BotCommand("unsubscribe", "Stop notifikasi"),
    ]
    await bot.set_my_commands(public_commands, scope=BotCommandScopeDefault())

    # 2. Menu KHUSUS ADMIN (ID Kamu)
    # Kamu bisa melihat semua menu termasuk tools admin
    admin_commands = public_commands + [
        BotCommand("stats", "🔒 Statistik Server"),
        BotCommand("collect", "🔒 Scraping Manual"),
        BotCommand("cleanup", "🔒 Hapus data lama"),
        BotCommand("sources", "🔒 Kelola Sumber"),
        BotCommand("add_source", "🔒 Tambah Sumber"),
        BotCommand("toggle_source", "Toggle aktif/nonaktif (+ ID)"),
        BotCommand("stats", "Statistik"),
    ]
    
    # Menu ini hanya muncul di chat ID kamu
    if TELEGRAM_ADMIN_ID:
        try:
            await bot.set_my_commands(
                admin_commands, 
                scope=BotCommandScopeChat(chat_id=int(TELEGRAM_ADMIN_ID))
            )
        except Exception as e:
            logger.warning(f"Gagal set menu khusus admin: {e}")

    logger.info("🤖 Bot commands registered (Public & Admin scopes)")


def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("Missing TELEGRAM_BOT_TOKEN in .env")
        return

    logger.info("🤖 Starting Telegram bot...")

    # Start scheduler
    from market_sentiment.pipeline.scheduler import start_scheduler
    start_scheduler()

    # ══════════════════════════════════════════════════════════════════
    # FIX: Konfigurasi Timeout untuk Koneksi Lambat / Indonesia
    # ══════════════════════════════════════════════════════════════════
    trequest = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30.0,      # Diperbesar jadi 30 detik
        write_timeout=30.0,
        connect_timeout=30.0,   # Diperbesar jadi 30 detik
        pool_timeout=30.0,
        http_version="1.1",
    )

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(trequest)     
        .post_init(post_init)
        .build()
    )
    # ══════════════════════════════════════════════════════════════════

    # Add Source conversation
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_source", add_source_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_source_name)],
            ADD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_source_url)],
            ADD_TYPE: [CallbackQueryHandler(add_source_type_cb, pattern=r"^srctype:")],
            ADD_CATEGORY: [CallbackQueryHandler(add_source_cat_cb, pattern=r"^srccat:")],
        },
        fallbacks=[CommandHandler("cancel", add_source_cancel)],
    ))

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("list", cmd_list_handler))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("search", cmd_search_start)],
        states={
            SEARCH_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_keyword)],
        },
        fallbacks=[CommandHandler("cancel", cmd_search_cancel)],
    ))
    app.add_handler(CommandHandler("source", cmd_source_handler))
    app.add_handler(CommandHandler("category", cmd_category_handler))
    app.add_handler(CommandHandler("stats", cmd_stats_handler))
    app.add_handler(CommandHandler("analyze", cmd_analyze_handler))
    app.add_handler(CommandHandler("collect", cmd_collect_handler))
    app.add_handler(CommandHandler("cleanup", cmd_cleanup))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("toggle_source", cmd_toggle_source))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Text input
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    logger.info("🤖 Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)
