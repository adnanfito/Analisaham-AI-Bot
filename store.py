"""
News Store — Auto-select JSON files atau Supabase
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import NEWS_DIR, SIMILARITY_THRESHOLD, logger
from helpers import generate_id, similarity


# ---------------------------------------------------------------------------
# JSON File Store (local development)
# ---------------------------------------------------------------------------


class JSONStore:
    """Penyimpanan berita ke JSON files (local)."""

    def __init__(self, news_dir: Path = NEWS_DIR) -> None:
        self.news_dir = news_dir
        self.news_dir.mkdir(exist_ok=True)
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _load_all(self) -> Dict[str, Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        records: Dict[str, Dict[str, Any]] = {}
        for fp in sorted(self.news_dir.glob("*.json")):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    news_id = data.get("id", "")
                    if news_id:
                        data["_filepath"] = str(fp)
                        records[news_id] = data
            except (json.JSONDecodeError, KeyError):
                continue
        self._cache = records
        return records

    def _invalidate(self) -> None:
        self._cache = None

    def get_by_id(self, news_id: str) -> Optional[Dict[str, Any]]:
        all_news = self._load_all()
        if news_id in all_news:
            return all_news[news_id]
        matches = [k for k in all_news if k.startswith(news_id)]
        if len(matches) == 1:
            return all_news[matches[0]]
        if len(matches) > 1:
            logger.error("Ambiguous ID '%s'. Matches: %s", news_id, matches)
            return None
        return None

    def get_all(self) -> List[Dict[str, Any]]:
        items = list(self._load_all().values())
        items.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        return items

    def get_all_urls(self) -> set:
        return {r.get("url", "") for r in self._load_all().values()}

    def get_all_titles(self) -> List[str]:
        return [r.get("title", "") for r in self._load_all().values()]

    def get_by_status(
        self, status: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        items = [r for r in self._load_all().values() if r.get("status") == status]
        items.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        if limit:
            items = items[:limit]
        return items

    def is_duplicate_url(self, url: str) -> bool:
        return url in self.get_all_urls()

    def is_redundant_title(self, title: str) -> Tuple[bool, Optional[str]]:
        for existing in self.get_all_titles():
            if similarity(title, existing) >= SIMILARITY_THRESHOLD:
                return True, existing
        return False, None

    def save(self, record: Dict[str, Any]) -> bool:
        url = record.get("url", "")

        if self.is_duplicate_url(url):
            logger.warning("    ⚠ Duplicate URL: %s", url[:60])
            return False

        is_redundant, matched = self.is_redundant_title(record.get("title", ""))
        if is_redundant:
            logger.warning(
                "    ⚠ Redundant (~%s): '%s'",
                f"{SIMILARITY_THRESHOLD:.0%}",
                matched[:50],
            )
            return False

        news_id = generate_id(url)
        record["id"] = news_id

        safe_title = re.sub(r"[^\w\s-]", "", record.get("title", "untitled"))[:50]
        safe_title = re.sub(r"\s+", "_", safe_title).strip("_")
        filename = f"{news_id}_{safe_title}.json"

        filepath = self.news_dir / filename
        save_data = {k: v for k, v in record.items() if not k.startswith("_")}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)

        self._invalidate()
        return True

    def update(self, record: Dict[str, Any]) -> None:
        filepath = record.get("_filepath")
        if not filepath:
            logger.error("Cannot update without _filepath")
            return
        save_data = {k: v for k, v in record.items() if not k.startswith("_")}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
        self._invalidate()

    def stats(self) -> Dict[str, int]:
        all_news = self._load_all()
        raw = sum(1 for r in all_news.values() if r.get("status") == "raw")
        analyzed = sum(1 for r in all_news.values() if r.get("status") == "analyzed")
        return {"total": len(all_news), "raw": raw, "analyzed": analyzed}


# ---------------------------------------------------------------------------
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
            from db import SupabaseDB
            store = SupabaseDB()
            logger.info("📦 Using Supabase database")
            return store
        except Exception as exc:
            logger.warning("⚠ Supabase init failed (%s), falling back to JSON", exc)

    logger.info("📦 Using local JSON store")
    return JSONStore()