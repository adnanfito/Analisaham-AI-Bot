"""
Phase 3: LLM Filter — saring berita relevan (Berita vs IDX)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from market_sentiment.core.config import (
    GROQ_FILTER_MAX_TOKENS,
    VALID_CATEGORIES,
    VALID_SENTIMENTS,
    logger,
)
from market_sentiment.llm.client import GroqClient


# ---------------------------------------------------------------------------
# Phase 3: LLM Filter (Split: Berita vs IDX)
# ---------------------------------------------------------------------------


def filter_news_batch(
    groq: GroqClient, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Router: pisah entries ke filter berita vs filter IDX."""
    if not entries:
        return []

    news_entries = [e for e in entries if e.get("source_type") != "idx_api"]
    idx_entries = [e for e in entries if e.get("source_type") == "idx_api"]

    relevant: List[Dict[str, Any]] = []

    if news_entries:
        logger.info("  📰 Filtering %d berita...", len(news_entries))
        relevant.extend(_filter_news(groq, news_entries))

    if idx_entries:
        logger.info("  📋 Filtering %d IDX announcements...", len(idx_entries))
        relevant.extend(_filter_idx(groq, idx_entries))

    return relevant


def _filter_news(
    groq: GroqClient, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filter berita dari situs berita (RSS)."""
    news_list = []
    for i, e in enumerate(entries):
        item = f'{i + 1}. [{e.get("_source_name", "")}] {e.get("title", "")}'
        summary = e.get("_rss_summary", "")
        if summary:
            item += f"\n   {summary[:200]}"
        news_list.append(item)

    system = """Kamu editor berita keuangan Indonesia.
Filter berita yang RELEVAN untuk investor saham.

RELEVAN:
- Pergerakan IHSG, indeks sektoral, saham individual
- Kebijakan Bank Indonesia (suku bunga, moneter)
- Data ekonomi makro (inflasi, GDP, neraca perdagangan, PMI)
- Harga komoditas (emas, minyak, CPO, batu bara, nikel)
- Corporate action (dividen, stock split, rights issue, IPO, buyback)
- Laporan keuangan emiten
- Kebijakan pemerintah berdampak ke pasar
- Arus dana asing (foreign flow)
- Sentimen global berdampak ke Indonesia (Fed, geopolitik)
- Regulasi OJK / BEI berdampak ke pasar

TIDAK RELEVAN:
- Kriminal, lifestyle, olahraga, hiburan
- Politik non-ekonomi
- Tips investasi generik, advertorial, promosi
- Berita daerah tanpa dampak pasar
- Berita teknologi/startup tanpa kaitan pasar modal

SELALU respond valid JSON."""

    user = f"""Berikut {len(entries)} berita:

{chr(10).join(news_list)}

Untuk SETIAP berita tentukan:
1. relevant: true/false
2. category: Market/Macro/Commodity/Sectoral/Corporate Action
3. sentiment: bullish/bearish/neutral
4. reason: alasan singkat (1 kalimat)

JSON format:
{{
  "results": [
    {{"index": 1, "relevant": true, "category": "Market", "sentiment": "bullish", "reason": "IHSG menguat"}},
    {{"index": 2, "relevant": false, "category": null, "sentiment": null, "reason": "Berita hiburan"}}
  ]
}}"""

    return _run_filter(groq, system, user, entries)


def _filter_idx(
    groq: GroqClient, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filter keterbukaan informasi dari IDX."""
    news_list = []
    for i, e in enumerate(entries):
        title = e.get("title", "")
        attachments = e.get("_attachments", [])
        att_count = len(attachments)
        att_info = f" ({att_count} file)" if att_count > 0 else ""
        news_list.append(f"{i + 1}. {title}{att_info}")

    system = """Kamu analis pasar modal Indonesia.
Filter keterbukaan informasi IDX yang PENTING untuk investor.

═══ PENTING — LOLOSKAN ═══
- Pembagian dividen (interim / final / tunai / saham)
- Stock split, reverse stock split
- Rights issue, HMETD, penambahan modal
- Akuisisi, merger, divestasi, penjualan aset material
- Buyback saham / pembelian kembali
- Laporan Keuangan Tahunan
- Laporan Keuangan Kuartalan (Q1, Q2, Q3)
- RUPS / RUPSLB (hasil keputusan)
- Perubahan susunan Direksi / Komisaris
- Transaksi material / afiliasi / benturan kepentingan
- Penawaran tender (tender offer)
- IPO / pencatatan saham baru / listing
- Suspend / unsuspend perdagangan
- Perjanjian kerjasama strategis bernilai material
- Default / gagal bayar obligasi
- Perubahan rating kredit emiten

═══ TIDAK PENTING — BUANG ═══
- Laporan Bulanan Registrasi Pemegang Efek (RUTIN)
- Penyampaian Bukti Iklan Laporan Keuangan (ADMINISTRATIF)
- Laporan Penggunaan Dana Hasil Penawaran Umum (RUTIN)
- Pemberitahuan perubahan alamat / logo / nama singkat
- Surat pernyataan / disclaimer administratif
- Pelaporan kepemilikan saham rutin tanpa perubahan signifikan
- Laporan bulanan obligasi / sukuk (RUTIN)
- Penyampaian bukti iklan / pengumuman yang sifatnya hanya formalitas

SELALU respond valid JSON."""

    user = f"""Berikut {len(entries)} keterbukaan informasi IDX:

{chr(10).join(news_list)}

Untuk SETIAP item tentukan:
1. relevant: true/false
2. sub_category: dividen/rights_issue/stock_split/akuisisi/buyback/lapkeu_tahunan/lapkeu_kuartal/rups/direksi/transaksi_material/tender_offer/ipo/suspend/lainnya
3. sentiment: bullish/bearish/neutral
4. reason: alasan singkat (1 kalimat)

JSON format:
{{
  "results": [
    {{"index": 1, "relevant": true, "sub_category": "dividen", "sentiment": "bullish", "reason": "Pembagian dividen tunai"}},
    {{"index": 2, "relevant": false, "sub_category": null, "sentiment": null, "reason": "Laporan bulanan registrasi rutin"}}
  ]
}}"""

    return _run_filter(groq, system, user, entries, is_idx=True)


# def _run_filter(
#     groq: GroqClient,
#     system: str,
#     user: str,
#     entries: List[Dict[str, Any]],
#     is_idx: bool = False,
# ) -> List[Dict[str, Any]]:
#     """Eksekusi LLM filter dan parse hasilnya."""
#     try:
#         raw = groq.chat(system, user, max_tokens=GROQ_FILTER_MAX_TOKENS)
#         data = json.loads(raw)

#         relevant = []
#         for r in data.get("results", []):
#             idx = r.get("index", 0) - 1
#             if 0 <= idx < len(entries) and r.get("relevant", False):
#                 entry = entries[idx]

#                 if is_idx:
#                     entry["_filter_category"] = "Disclosure"
#                     entry["_filter_sub_category"] = r.get("sub_category", "lainnya")

#                     sub = r.get("sub_category", "")
#                     if sub in ("lapkeu_tahunan", "lapkeu_kuartal"):
#                         entry["_is_lapkeu"] = True
#                 else:
#                     cat = r.get("category", "Market")
#                     if cat not in VALID_CATEGORIES:
#                         cat = "Market"
#                     entry["_filter_category"] = cat

#                 sentiment = r.get("sentiment", "neutral")
#                 if sentiment not in VALID_SENTIMENTS:
#                     sentiment = "neutral"
#                 entry["_filter_sentiment"] = sentiment
#                 entry["_filter_reason"] = r.get("reason", "")
#                 relevant.append(entry)

#         return relevant

#     except Exception as exc:
#         logger.error("  ✗ Filter error: %s", exc)
#         return entries

def _run_filter(
    groq: GroqClient,
    system: str,
    user: str,
    entries: List[Dict[str, Any]],
    is_idx: bool = False,
) -> List[Dict[str, Any]]:
    """Eksekusi LLM filter dan parse hasilnya."""
    try:
        raw = groq.chat(system, user, max_tokens=GROQ_FILTER_MAX_TOKENS)
        data = json.loads(raw)

        relevant = []
        results_list = data.get("results", [])
        
        # PROTEKSI 1: Pastikan data 'results' benar-benar sebuah List
        if not isinstance(results_list, list):
            logger.warning("  ⚠ Format LLM salah (results bukan list). Fallback: loloskan semua berita di batch ini.")
            return entries # Atau kembalikan [] jika ingin membuang semua isi batch

        for r in results_list:
            # PROTEKSI 2: Pastikan setiap item 'r' di dalam list adalah Dictionary
            if not isinstance(r, dict):
                logger.warning("  ⚠ Format item salah (bukan dictionary), item diabaikan.")
                continue # Lewati item yang rusak, lanjut ke item berikutnya
            
            idx = r.get("index", 0) - 1
            if 0 <= idx < len(entries) and r.get("relevant", False):
                entry = entries[idx]

                if is_idx:
                    entry["_filter_category"] = "Disclosure"
                    entry["_filter_sub_category"] = r.get("sub_category", "lainnya")

                    sub = r.get("sub_category", "")
                    if sub in ("lapkeu_tahunan", "lapkeu_kuartal"):
                        entry["_is_lapkeu"] = True
                else:
                    cat = r.get("category", "Market")
                    if cat not in VALID_CATEGORIES:
                        cat = "Market"
                    entry["_filter_category"] = cat

                sentiment = r.get("sentiment", "neutral")
                if sentiment not in VALID_SENTIMENTS:
                    sentiment = "neutral"
                entry["_filter_sentiment"] = sentiment
                entry["_filter_reason"] = r.get("reason", "")
                relevant.append(entry)

        return relevant

    except Exception as exc:
        # Jika JSON gagal diparse sama sekali, fallback ke semua entries (sesuai kodemu sebelumnya)
        logger.error("  ✗ Filter error: %s", exc)
        return entries
