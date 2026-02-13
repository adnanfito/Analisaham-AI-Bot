"""
Constants & Environment Configuration
"""

import os
import sys
import logging
from pathlib import Path
from typing import FrozenSet

# ---------------------------------------------------------------------------
# Load .env FIRST
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
SOURCES_FILE = BASE_DIR / "sources.json"
STATE_FILE = BASE_DIR / "state.json"
NEWS_DIR = BASE_DIR / "news"

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_FILTER_MAX_TOKENS = 2048
GROQ_ANALYSIS_MAX_TOKENS = 3072

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------
MIN_CONTENT_LENGTH = 100
BROWSER_DELAY = 3.0
SIMILARITY_THRESHOLD = 0.75

# ---------------------------------------------------------------------------
# Categories & Sentiments
# ---------------------------------------------------------------------------
VALID_CATEGORIES: FrozenSet[str] = frozenset(
    {"Market", "Macro", "Commodity", "Sectoral", "Corporate Action", "Disclosure"}
)
VALID_SENTIMENTS: FrozenSet[str] = frozenset({"bullish", "bearish", "neutral"})

# ---------------------------------------------------------------------------
# Cloudflare Detection
# ---------------------------------------------------------------------------
CLOUDFLARE_MARKERS = [
    "just a moment", "tunggu sebentar", "un moment",
    "einen moment", "un momento", "aguarde",
    "challenge-platform", "cf-challenge", "cf_chl_opt",
]

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID", "")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def load_env() -> str:
    """Load and validate GROQ_API_KEY from environment."""
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_api_key:
        logger.critical("Missing GROQ_API_KEY in .env")
        sys.exit(1)
    return groq_api_key