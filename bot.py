"""
Telegram Bot — Interactive commands + notifications (multi-user)
Full CRUD sources via Supabase / JSON fallback.
Subscribers via Supabase / JSON fallback.
"""

from __future__ import annotations

import asyncio
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeChat, BotCommandScopeDefault
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config import (
    BASE_DIR,
    SOURCES_FILE,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    TELEGRAM_ADMIN_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    logger,
    load_env,
)

from telegram.request import HTTPXRequest
from store import get_store
from llm import GroqClient, analyze_single
from browser import BrowserManager
from helpers import format_published_date
from functools import wraps


# ═══════════════════════════════════════════════════════════════════════════
# Backend Helper
# ═══════════════════════════════════════════════════════════════════════════

def _use_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _get_db():
    from db import SupabaseDB
    return SupabaseDB()

# ═══════════════════════════════════════════════════════════════════════════
# Subscriber Store (Supabase / JSON fallback)
# ═══════════════════════════════════════════════════════════════════════════

SUBSCRIBERS_FILE = BASE_DIR / "subscribers.json"


def _load_subscribers_json() -> Dict[str, Dict[str, Any]]:
    if not SUBSCRIBERS_FILE.exists():
        return {}
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_subscribers_json(subs: Dict[str, Dict[str, Any]]) -> None:
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, indent=2, ensure_ascii=False)


def add_subscriber(chat_id: int, username: str = "", first_name: str = "") -> bool:
    """Tambah/aktifkan subscriber. Return True jika baru."""
    if _use_supabase():
        try:
            return _get_db().upsert_subscriber(chat_id, username, first_name, active=True)
        except Exception as exc:
            logger.warning("⚠ Supabase subscriber failed: %s", exc)

    # JSON fallback
    subs = _load_subscribers_json()
    key = str(chat_id)
    is_new = key not in subs or not subs[key].get("active", True)
    subs[key] = {
        "chat_id": chat_id,
        "username": username,
        "first_name": first_name,
        "active": True,
    }
    _save_subscribers_json(subs)
    return is_new


def remove_subscriber(chat_id: int) -> None:
    """Nonaktifkan subscriber."""
    if _use_supabase():
        try:
            _get_db().deactivate_subscriber(chat_id)
            return
        except Exception as exc:
            logger.warning("⚠ Supabase subscriber failed: %s", exc)

    subs = _load_subscribers_json()
    key = str(chat_id)
    if key in subs:
        subs[key]["active"] = False
        _save_subscribers_json(subs)


def get_active_subscribers() -> List[int]:
    """Daftar chat_id subscriber aktif."""
    active = []

    if _use_supabase():
        try:
            active = _get_db().get_active_subscribers()
        except Exception as exc:
            logger.warning("⚠ Supabase subscribers failed: %s", exc)

    if not active:
        # JSON fallback
        subs = _load_subscribers_json()
        active = [d["chat_id"] for d in subs.values() if d.get("active", True)]

    # Tambah admin dari env
    if TELEGRAM_CHAT_ID:
        admin_id = int(TELEGRAM_CHAT_ID)
        if admin_id not in active:
            active.append(admin_id)

    return active


def count_active_subscribers() -> int:
    """Hitung subscriber aktif."""
    if _use_supabase():
        try:
            return _get_db().count_active_subscribers()
        except Exception:
            pass

    subs = _load_subscribers_json()
    count = len([s for s in subs.values() if s.get("active", True)])
    if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID) not in subs:
        count += 1
    return count


# ═══════════════════════════════════════════════════════════════════════════
# Sources Backend (Supabase / JSON fallback)
# ═══════════════════════════════════════════════════════════════════════════


def load_sources_data() -> List[Dict[str, Any]]:
    if _use_supabase():
        try:
            return _get_db().get_sources()
        except Exception as exc:
            logger.warning("⚠ Supabase sources failed: %s", exc)
    if not SOURCES_FILE.exists():
        return []
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def _save_sources_json(sources: List[Dict[str, Any]]) -> None:
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2, ensure_ascii=False)


def find_source_by_id_any(source_id: int) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            return _get_db().get_source_by_id(source_id)
        except Exception:
            pass
    for s in load_sources_data():
        if s.get("id") == source_id:
            return s
    return None


def add_source_to_store(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            return _get_db().add_source(source)
        except Exception as exc:
            logger.error("⚠ Supabase add_source failed: %s", exc)
            return None
    sources = load_sources_data()
    new_id = max((s.get("id", 0) for s in sources), default=0) + 1
    source["id"] = new_id
    sources.append(source)
    _save_sources_json(sources)
    return source


def update_source_in_store(source_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            return _get_db().update_source(source_id, updates)
        except Exception as exc:
            logger.error("⚠ Supabase update_source failed: %s", exc)
            return None
    sources = load_sources_data()
    for s in sources:
        if s.get("id") == source_id:
            s.update(updates)
            _save_sources_json(sources)
            return s
    return None


def toggle_source_in_store(source_id: int) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            return _get_db().toggle_source(source_id)
        except Exception as exc:
            logger.error("⚠ Supabase toggle_source failed: %s", exc)
            return None
    sources = load_sources_data()
    for s in sources:
        if s.get("id") == source_id:
            s["is_active"] = not s.get("is_active", True)
            _save_sources_json(sources)
            return s
    return None


def delete_source_from_store(source_id: int) -> bool:
    if _use_supabase():
        try:
            return _get_db().delete_source(source_id)
        except Exception as exc:
            logger.error("⚠ Supabase delete_source failed: %s", exc)
            return False
    sources = load_sources_data()
    new = [s for s in sources if s.get("id") != source_id]
    if len(new) < len(sources):
        _save_sources_json(new)
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Conversation States
# ═══════════════════════════════════════════════════════════════════════════

ADD_NAME, ADD_URL, ADD_TYPE, ADD_CATEGORY = range(4)
SEARCH_KEYWORD = 10

SOURCE_TYPES = ["rss", "idx_api", "stockbit_api", "sitemap.xml"]
SOURCE_CATEGORIES = [
    "Market", "Macro", "Commodity", "Sectoral", "Corporate Action", "Disclosure",
]

CATEGORY_EMOJI = {
    "Market": "📈",
    "Macro": "🏛",
    "Commodity": "⛏",
    "Sectoral": "🏭",
    "Corporate Action": "🏢",
    "Disclosure": "📋",
}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
PAGE_SIZE = 10


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


# ═══════════════════════════════════════════════════════════════════════════
# Command Handlers — News
# ════════════════���══════════════════════════════════════════════════════════

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
        from commands import cmd_collect

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

# ═══════════════════════════════════════════════════════════════════════════
# Command Handlers — Sources CRUD
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


# ═══════════════════════════════════════════════════════════════════════════
# Callback Query Handler
# ════════════════════════════════════════════════════════════════��══════════


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
    from scheduler import start_scheduler
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