"""
Market Sentiment Analysis Pipeline v2
======================================

Usage:
  python main.py                   Collect berita baru (Phase 1-4)
  python main.py list              Lihat semua berita
  python main.py list raw          Lihat berita pending analysis
  python main.py list analyzed     Lihat berita yang sudah dianalisis
  python main.py analyze <id>      Analyze satu berita by ID
  python main.py analyze all       Analyze semua berita raw
  python main.py analyze all 5     Analyze 5 berita raw terbaru
  python main.py stats             Statistik ringkas
  python main.py bot               Jalankan Telegram bot
"""

import sys
import traceback
from pathlib import Path

# Pastikan project directory ada di sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_env, logger
from browser import BrowserManager
from commands import cmd_collect, cmd_list, cmd_analyze, cmd_stats


HELP_TEXT = """
Market Sentiment Pipeline v2
══════════════════════════════

Usage:
  python main.py                   Collect berita baru (Phase 1-4)
  python main.py list              Lihat semua berita + ID
  python main.py list raw          Lihat berita pending analysis
  python main.py list analyzed     Lihat berita yang sudah dianalisis
  python main.py analyze <id>      Analyze satu berita (by ID)
  python main.py analyze all       Analyze semua berita pending
  python main.py analyze all 5     Analyze 5 berita pending terbaru
  python main.py stats             Statistik ringkas
  python main.py bot               Jalankan Telegram bot
  python main.py help              Tampilkan bantuan ini
"""


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "collect"

    if command == "help":
        print(HELP_TEXT)
        return

    if command == "bot":
        from bot import run_bot
        run_bot()
        return

    groq_api_key = load_env()
    logger.info("✓ Environment loaded.")

    if command == "collect":
        cmd_collect(groq_api_key)

    elif command == "list":
        status_filter = args[1] if len(args) > 1 else None
        cmd_list(status_filter)

    elif command == "analyze":
        if len(args) < 2:
            print("\n  Usage:")
            print("    python main.py analyze <id>      Analyze satu berita")
            print("    python main.py analyze all       Analyze semua pending")
            print("    python main.py analyze all 5     Analyze 5 pending terbaru\n")
            return
        target = args[1]
        limit = int(args[2]) if len(args) > 2 and args[1] == "all" else None
        cmd_analyze(groq_api_key, target, limit)

    elif command == "stats":
        cmd_stats()

    else:
        print(f"\n  ✗ Unknown command: '{command}'")
        print(HELP_TEXT)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nInterrupted.")
    except Exception:
        logger.critical("Unhandled exception:\n%s", traceback.format_exc())
        sys.exit(1)
    finally:
        BrowserManager.close()