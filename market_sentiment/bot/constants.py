"""
Konstanta bot — conversation states, tipe/kategori source, emoji, paging
"""

from __future__ import annotations



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
EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
PAGE_SIZE = 10
