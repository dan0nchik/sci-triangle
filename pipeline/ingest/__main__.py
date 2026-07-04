"""CLI: `python -m ingest --wave N` (idempotent).

Examples:
    python -m ingest --wave 1
    python -m ingest --wave 1 --wave 2
    python -m ingest --all
    python -m ingest --wave 1 --no-ocr --limit 20
    python -m ingest --report          # only regenerate corpus/README.md
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .pipeline import run
from .report import write_readme
from .util import log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ingest", description="sci-tangle ingest (direction A)")
    ap.add_argument("--wave", type=int, action="append", dest="waves",
                    help="wave number (repeatable): 1,2,3,4")
    ap.add_argument("--all", action="store_true", help="process all waves 1-4")
    ap.add_argument("--limit", type=int, default=None, help="cap #files (debug)")
    ap.add_argument("--no-ocr", action="store_true", help="disable OCR fallback")
    ap.add_argument("--report", action="store_true",
                    help="only (re)build corpus/README.md from existing outputs")
    args = ap.parse_args(argv)

    if args.report:
        write_readme()
        log(f"Wrote {config.README_PATH}")
        return 0

    if args.all:
        waves = [1, 2, 3, 4]
    elif args.waves:
        waves = sorted(set(args.waves))
    else:
        ap.error("specify --wave N (repeatable), --all, or --report")
        return 2

    stats = run(waves, limit=args.limit, use_ocr=not args.no_ocr)
    write_readme()
    log(f"README updated: {config.README_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
