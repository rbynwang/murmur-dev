"""Builds the demo pages from the recorded evenings into one folder, under their published file names.

  python -m demo.page_builder.build --out DIR

It writes the six replay pages (the two-view split view and its Data view copy, index.html, the three-view evening, the whole
evening, the two year sets), the method note, the year's results and the architecture page. The build reads only files in
this repository, and the same recordings always give the same bytes.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .pages import pages

LIMIT = 16_000_000          # a page must stay under 16 MB


def main() -> None:
    a = argparse.ArgumentParser(description="Builds the demo pages under their published file names.")
    a.add_argument("--out", required=True, type=Path, help="the folder to write the pages into")
    out: Path = a.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    for name, text in pages().items():
        data = text.encode("utf-8")
        if len(data) > LIMIT:
            raise SystemExit(f"{name} is {len(data) / 1e6:.1f} MB, and a page must stay under 16 MB")
        (out / name).write_bytes(data)
        print(f"{name}: {len(data):,} bytes")


if __name__ == "__main__":
    main()
