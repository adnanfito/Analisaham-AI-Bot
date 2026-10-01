"""
Repositories — subscriber & source CRUD (Supabase / JSON fallback)
"""

from __future__ import annotations

import json

from typing import Any, Dict, List, Optional

from market_sentiment.core.config import (
    SOURCES_FILE,
    SUBSCRIBERS_FILE,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    TELEGRAM_CHAT_ID,
    logger,
)


# ═══════════════════════════════════════════════════════════════════════════
# Backend Helper
# ═══════════════════════════════════════════════════════════════════════════

def _use_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _get_db():
    from market_sentiment.storage.supabase_db import SupabaseDB
    return SupabaseDB()

# ═══════════════════════════════════════════════════════════════════════════
# Subscriber Store (Supabase / JSON fallback)
# ═══════════════════════════════════════════════════════════════════════════



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
