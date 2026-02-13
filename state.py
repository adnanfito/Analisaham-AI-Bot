"""
State Management — auto-select JSON file atau Supabase
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from config import STATE_FILE, logger


def load_state(db=None) -> Dict[str, Any]:
    """Load state. Pakai Supabase kalau db tersedia."""
    if db and hasattr(db, "load_state"):
        return db.load_state()

    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        logger.warning("state.json corrupt, resetting.")
        return {}


def save_state(state: Dict[str, Any], db=None) -> None:
    """Simpan state. Pakai Supabase kalau db tersedia."""
    if db and hasattr(db, "save_state"):
        db.save_state(state)
        return

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)