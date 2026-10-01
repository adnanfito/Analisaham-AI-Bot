"""
Store Factory — auto-select Supabase atau JSON lokal
"""

from __future__ import annotations

import os

from market_sentiment.core.config import logger
from market_sentiment.storage.json_store import JSONStore


# Factory: Auto-select store backend
# ---------------------------------------------------------------------------


def get_store():
    """
    Auto-select store backend:
      - SUPABASE_URL set → SupabaseDB
      - Otherwise → JSONStore (local)
    """
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    if supabase_url and supabase_key:
        try:
            from market_sentiment.storage.supabase_db import SupabaseDB
            store = SupabaseDB()
            logger.info("📦 Using Supabase database")
            return store
        except Exception as exc:
            logger.warning("⚠ Supabase init failed (%s), falling back to JSON", exc)

    logger.info("📦 Using local JSON store")
    return JSONStore()
