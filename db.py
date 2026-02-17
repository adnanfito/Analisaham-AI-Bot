"""
Database Client — Supabase
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import SIMILARITY_THRESHOLD, logger
from helpers import generate_id, similarity


class SupabaseDB:
    """Supabase database client."""

    def __init__(self) -> None:
        from supabase import create_client
        from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

        self._client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        self._titles_cache: Optional[List[str]] = None
        self._urls_cache: Optional[set] = None

    # ==================================================================
    # News — Read
    # ==================================================================

    def get_by_id(self, news_id: str) -> Optional[Dict[str, Any]]:
        resp = self._client.table("news").select("*").eq("id", news_id).execute()
        if resp.data:
            return self._deserialize(resp.data[0])

        resp = (
            self._client.table("news")
            .select("*")
            .like("id", f"{news_id}%")
            .execute()
        )
        if resp.data and len(resp.data) == 1:
            return self._deserialize(resp.data[0])
        if resp.data and len(resp.data) > 1:
            ids = [r["id"] for r in resp.data]
            logger.error("Ambiguous ID '%s'. Matches: %s", news_id, ids)
            return None
        return None

    def get_all(self) -> List[Dict[str, Any]]:
        resp = (
            self._client.table("news")
            .select("*")
            .order("published_at", desc=True)
            .execute()
        )
        return [self._deserialize(r) for r in resp.data]

    def get_by_status(
        self, status: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = (
            self._client.table("news")
            .select("*")
            .eq("status", status)
            .order("published_at", desc=True)
        )
        if limit:
            query = query.limit(limit)
        resp = query.execute()
        return [self._deserialize(r) for r in resp.data]
    
    def get_by_source(self, source_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Ambil berita spesifik berdasarkan source_id langsung dari database."""
        try:
            query = (
                self._client.table("news")
                .select("*")
                .eq("source_id", source_id)
                .order("published_at", desc=True)
            )
            if limit:
                query = query.limit(limit)
            resp = query.execute()
            return [self._deserialize(r) for r in resp.data]
        except Exception as exc:
            from config import logger
            logger.error("✗ get_by_source failed: %s", exc)
            return []

    def get_all_urls(self) -> set:
        if self._urls_cache is not None:
            return self._urls_cache
        resp = self._client.table("news").select("url").execute()
        self._urls_cache = {r["url"] for r in resp.data}
        return self._urls_cache

    def get_all_titles(self) -> List[str]:
        if self._titles_cache is not None:
            return self._titles_cache
        resp = self._client.table("news").select("title").execute()
        self._titles_cache = [r["title"] for r in resp.data]
        return self._titles_cache

    def stats(self) -> Dict[str, int]:
        try:
            resp = self._client.table("news_stats").select("*").execute()
            if resp.data:
                row = resp.data[0]
                return {
                    "total": row.get("total", 0),
                    "raw": row.get("raw_count", 0),
                    "analyzed": row.get("analyzed_count", 0),
                }
        except Exception:
            pass

        all_news = self.get_all()
        raw = sum(1 for r in all_news if r.get("status") == "raw")
        analyzed = sum(1 for r in all_news if r.get("status") == "analyzed")
        return {"total": len(all_news), "raw": raw, "analyzed": analyzed}

    # ==================================================================
    # News — Write
    # ==================================================================

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
        db_record = self._serialize_for_insert(record)

        try:
            self._client.table("news").insert(db_record).execute()
            self._urls_cache = None
            self._titles_cache = None
            return True
        except Exception as exc:
            logger.error("    ✗ DB insert failed: %s", exc)
            return False

    def update(self, record: Dict[str, Any]) -> None:
        news_id = record.get("id")
        if not news_id:
            logger.error("Cannot update without id")
            return

        db_record = self._serialize_for_update(record)

        try:
            self._client.table("news").update(db_record).eq("id", news_id).execute()
            self._urls_cache = None
            self._titles_cache = None
        except Exception as exc:
            logger.error("    ✗ DB update failed: %s", exc)

    # ==================================================================
    # Pipeline State
    # ==================================================================

    def load_state(self) -> Dict[str, Any]:
        resp = self._client.table("pipeline_state").select("*").execute()
        state = {}
        for row in resp.data:
            state[row["source_id"]] = {
                "last_top_link": row.get("last_top_link"),
                "last_scraped_at": row.get("last_scraped_at"),
                "name": row.get("source_name", ""),
            }
        return state

    def save_state(self, state: Dict[str, Any]) -> None:
        for source_id, data in state.items():
            record = {
                "source_id": str(source_id),
                "last_top_link": data.get("last_top_link"),
                "last_scraped_at": data.get("last_scraped_at"),
                "source_name": data.get("name", ""),
            }
            try:
                self._client.table("pipeline_state").upsert(record).execute()
            except Exception as exc:
                logger.error("    ✗ State save failed: %s", exc)

    # ==================================================================
    # Sources CRUD
    # ==================================================================

    def get_sources(self) -> List[Dict[str, Any]]:
        """Ambil semua sources."""
        resp = (
            self._client.table("sources")
            .select("*")
            .order("id", desc=False)
            .execute()
        )
        return resp.data

    def get_active_sources(self) -> List[Dict[str, Any]]:
        """Ambil sources yang aktif."""
        resp = (
            self._client.table("sources")
            .select("*")
            .eq("is_active", True)
            .order("id", desc=False)
            .execute()
        )
        return resp.data

    def get_source_by_id(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Ambil satu source by ID."""
        resp = (
            self._client.table("sources")
            .select("*")
            .eq("id", source_id)
            .execute()
        )
        if resp.data:
            return resp.data[0]
        return None

    def add_source(self, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Tambah source baru. Return inserted record."""
        insert_data = {
            "name": source.get("name", ""),
            "feed_url": source.get("feed_url", ""),
            "type": source.get("type", "rss"),
            "category": source.get("category", "Market"),
            "is_active": source.get("is_active", True),
        }
        try:
            resp = self._client.table("sources").insert(insert_data).execute()
            if resp.data:
                logger.info("📡 Source added: %s", insert_data["name"])
                return resp.data[0]
        except Exception as exc:
            logger.error("✗ Source insert failed: %s", exc)
        return None

    def update_source(self, source_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update source. Return updated record."""
        # Only allow valid fields
        allowed = {"name", "feed_url", "type", "category", "is_active"}
        clean = {k: v for k, v in updates.items() if k in allowed}

        if not clean:
            return None

        try:
            resp = (
                self._client.table("sources")
                .update(clean)
                .eq("id", source_id)
                .execute()
            )
            if resp.data:
                logger.info("📡 Source [%d] updated: %s", source_id, list(clean.keys()))
                return resp.data[0]
        except Exception as exc:
            logger.error("✗ Source update failed: %s", exc)
        return None

    def toggle_source(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Toggle is_active. Return updated record."""
        source = self.get_source_by_id(source_id)
        if not source:
            return None

        new_active = not source.get("is_active", True)
        return self.update_source(source_id, {"is_active": new_active})

    def delete_source(self, source_id: int) -> bool:
        """Hapus source. Return True jika berhasil."""
        try:
            self._client.table("sources").delete().eq("id", source_id).execute()
            logger.info("📡 Source [%d] deleted", source_id)
            return True
        except Exception as exc:
            logger.error("✗ Source delete failed: %s", exc)
            return False

    # ==================================================================
    # Serialization
    # ==================================================================

    def _serialize_for_insert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        clean = {k: v for k, v in record.items() if not k.startswith("_")}

        analysis = clean.pop("analysis", None)
        if analysis and isinstance(analysis, dict):
            clean["analysis_summary"] = analysis.get("summary", "")
            clean["analysis_sentiment"] = analysis.get("sentiment_direction", "")
            clean["analysis_reasoning"] = analysis.get("sentiment_reasoning", "")
            clean["analysis_category"] = analysis.get("category", "")
            clean["analysis_ticker"] = analysis.get("ticker")
            clean["analysis_tags"] = analysis.get("tags", [])
            clean["analysis_key_data"] = analysis.get("key_data", [])

        if clean.get("analyzed_at") is None:
            clean.pop("analyzed_at", None)

        return clean

    def _serialize_for_update(self, record: Dict[str, Any]) -> Dict[str, Any]:
        update_data: Dict[str, Any] = {
            "status": record.get("status"),
            "sentiment": record.get("sentiment"),
            "category": record.get("category"),
            "ticker": record.get("ticker"),
            "analyzed_at": record.get("analyzed_at"),
        }

        analysis = record.get("analysis")
        if analysis and isinstance(analysis, dict):
            update_data["analysis_summary"] = analysis.get("summary", "")
            update_data["analysis_sentiment"] = analysis.get("sentiment_direction", "")
            update_data["analysis_reasoning"] = analysis.get("sentiment_reasoning", "")
            update_data["analysis_category"] = analysis.get("category", "")
            update_data["analysis_ticker"] = analysis.get("ticker")
            update_data["analysis_tags"] = analysis.get("tags", [])
            update_data["analysis_key_data"] = analysis.get("key_data", [])

        return {k: v for k, v in update_data.items() if v is not None}

    def _deserialize(self, row: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(row)

        if record.get("analysis_summary") or record.get("analysis_sentiment"):
            record["analysis"] = {
                "summary": record.get("analysis_summary", ""),
                "sentiment_direction": record.get("analysis_sentiment", "neutral"),
                "sentiment_reasoning": record.get("analysis_reasoning", ""),
                "category": record.get("analysis_category", ""),
                "ticker": record.get("analysis_ticker"),
                "tags": record.get("analysis_tags", []),
                "key_data": record.get("analysis_key_data", []),
            }
        else:
            record["analysis"] = None

        return record
    
    # ==================================================================
    # Subscribers CRUD
    # ==================================================================

    def get_subscribers(self) -> List[Dict[str, Any]]:
        """Ambil semua subscriber."""
        resp = self._client.table("subscribers").select("*").execute()
        return resp.data

    def get_active_subscribers(self) -> List[int]:
        """Ambil chat_id subscriber aktif."""
        resp = (
            self._client.table("subscribers")
            .select("chat_id")
            .eq("active", True)
            .execute()
        )
        return [r["chat_id"] for r in resp.data]

    def get_subscriber(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Ambil satu subscriber."""
        resp = (
            self._client.table("subscribers")
            .select("*")
            .eq("chat_id", chat_id)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def upsert_subscriber(
        self, chat_id: int, username: str = "", first_name: str = "", active: bool = True
    ) -> bool:
        """Insert atau update subscriber. Return True jika baru."""
        existing = self.get_subscriber(chat_id)
        is_new = existing is None or not existing.get("active", True)

        self._client.table("subscribers").upsert({
            "chat_id": chat_id,
            "username": username,
            "first_name": first_name,
            "active": active,
        }).execute()

        return is_new

    def deactivate_subscriber(self, chat_id: int) -> None:
        """Nonaktifkan subscriber."""
        self._client.table("subscribers").update(
            {"active": False}
        ).eq("chat_id", chat_id).execute()

    def count_active_subscribers(self) -> int:
        """Hitung subscriber aktif."""
        resp = (
            self._client.table("subscribers")
            .select("chat_id", count="exact")
            .eq("active", True)
            .execute()
        )
        return resp.count or 0
    
    # ============================= Delete Old News ==================================== #
    
    def delete_old_news(self, days: int = 3) -> int:
        """Hapus berita yang lebih tua dari X hari berdasarkan published_at."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        try:
            # Hapus data yang published_at < cutoff
            resp = (
                self._client.table("news")
                .delete()
                .lt("published_at", cutoff_str)
                .execute()
            )
            deleted_count = len(resp.data) if resp.data else 0
            logger.info("🗑 Cleanup: %d news older than %d days deleted.", deleted_count, days)
            
            # Clear cache karena data berubah
            self._urls_cache = None
            self._titles_cache = None
            
            return deleted_count
        except Exception as exc:
            logger.error("✗ Cleanup failed: %s", exc)
            return 0
    
    # ============================= Search News ==================================== #
    def search_news(self, keyword: str) -> List[Dict[str, Any]]:
        """Mencari berita berdasarkan keyword pada judul ATAU rss_summary."""
        try:
            resp = (
                self._client.table("news")
                .select("*")
                # Supabase OR logic: Cari di title ATAU di rss_summary
                .or_(f"title.ilike.%{keyword}%,rss_summary.ilike.%{keyword}%")
                .order("published_at", desc=True)
                .execute()
            )
            return [self._deserialize(r) for r in resp.data]
        except Exception as exc:
            from config import logger
            logger.error("✗ Search failed: %s", exc)
            return []