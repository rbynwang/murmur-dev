"""Writes the synthetic test dataset in tests/fixtures/data/ and the single sites in tests/fixtures/sites.json, in the file forms an evening reads.

The synthetic community of demo/runner/synthetic.py over two days of 15-minute steps (2025-01-27 and 2025-01-28): three homes (two with a car,
all with a battery), one small office building, one solar-and-battery plant and one data center. Seeded, and gzip files carry no timestamp, so
the output is the same bytes on every machine (tests/test_runner.py holds the committed files to that).

  python tests/fixtures/make_fixtures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAYS = ("2025-01-27", "2025-01-28")


def main() -> None:
    sys.path.insert(0, str(HERE.parents[1]))
    from demo.runner.synthetic import Community
    n = Community(DAYS).write(HERE / "data", HERE / "sites.json")
    print(f"{n} files in {HERE / 'data'}")


if __name__ == "__main__":
    main()
