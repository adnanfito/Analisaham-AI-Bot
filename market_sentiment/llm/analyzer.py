"""
Phase 5: Deep Analysis — analisis sentimen satu berita
"""

from __future__ import annotations

import json
from typing import Any, Dict

from market_sentiment.core.config import (
    GROQ_ANALYSIS_MAX_TOKENS,
    MIN_CONTENT_LENGTH,
    VALID_CATEGORIES,
    VALID_SENTIMENTS,
    logger,
)
from market_sentiment.collectors.scraper import scrape_article
from market_sentiment.llm.client import GroqClient


# ---------------------------------------------------------------------------
# Phase 5: Deep Analysis
# ---------------------------------------------------------------------------


def analyze_single(groq: GroqClient, record: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze satu berita. Thread-safe (scraper handles its own browser)."""
    url = record.get("url", "")
    title = record.get("title", "")

    logger.info("    📰 Scraping full article...")
    content = scrape_article(url)

    if not content or len(content) < MIN_CONTENT_LENGTH:
        logger.warning("    ⚠ Using title + RSS summary")
        content = f"{title}\n\n{record.get('rss_summary', '')}"

    system_prompt = """Kamu adalah analis berita keuangan Indonesia yang berpengalaman.
Analisis artikel berita ini secara mendalam.
SELALU respond dengan valid JSON."""

    user_prompt = f"""Analisis artikel berita keuangan berikut secara mendalam dan profesional.

JUDUL: {title}

ISI ARTIKEL:
{content[:5000]}

Respond dengan JSON format berikut:
{{
  "summary": "Tulis ringkasan naratif yang profesional dan informatif (3-5 paragraf pendek). Paragraf pertama berisi inti berita. Paragraf selanjutnya memuat detail penting seperti angka, data, dampak, dan konteks. Gunakan gaya jurnalistik yang mudah dipahami investor. Pisahkan paragraf dengan baris baru (\\n\\n). Jangan gunakan bullet point. Paragraf terakhir berisi kesimpulan implikasi bagi pasar atau investor.",
  "sentiment_direction": "bullish/bearish/neutral",
  "sentiment_reasoning": "Jelaskan dalam 2-3 kalimat mengapa sentimen ini relevan bagi investor dan apa implikasinya terhadap pasar atau saham terkait.",
  "category": "Market/Macro/Commodity/Sectoral/Corporate Action/Disclosure",
  "tags": ["keyword1", "keyword2", "keyword3"],
  "ticker": "BBRI atau null (kode saham 4 huruf UPPERCASE jika relevan dengan emiten tertentu)",
  "key_data": ["IHSG +1.22%", "Net buy asing Rp1.8T", "BI rate 5.75%"]
}}

PANDUAN PENULISAN SUMMARY:
- Tulis seolah kamu analis riset yang menulis untuk klien investor
- Sertakan angka dan data spesifik dari artikel
- Jelaskan konteks dan dampak terhadap pasar/investor
- Hindari kalimat generik, fokus pada fakta dan implikasi
- Gunakan bahasa Indonesia yang profesional dan mudah dipahami"""

    try:
        raw = groq.chat(
            system_prompt, user_prompt, max_tokens=GROQ_ANALYSIS_MAX_TOKENS
        )
        analysis = json.loads(raw)

        cat = analysis.get("category", record.get("category", "Market"))
        if cat not in VALID_CATEGORIES:
            cat = record.get("category", "Market")
        analysis["category"] = cat

        direction = analysis.get("sentiment_direction", "neutral")
        if direction not in VALID_SENTIMENTS:
            direction = "neutral"
        analysis["sentiment_direction"] = direction

        ticker = analysis.get("ticker")
        if ticker and (not isinstance(ticker, str) or len(ticker) != 4):
            ticker = None
        analysis["ticker"] = ticker.upper() if ticker else None

        tags = analysis.get("tags", [])
        analysis["tags"] = (
            [str(t).lower().strip() for t in tags if t]
            if isinstance(tags, list)
            else []
        )

        return analysis
    except Exception as exc:
        logger.error("    ✗ Analysis error: %s", exc)
        return {
            "summary": "",
            "sentiment_direction": "neutral",
            "sentiment_reasoning": "",
            "category": record.get("category", "Market"),
            "tags": [],
            "ticker": None,
            "key_data": [],
        }
