"""python -m experiments.engie.peak_allocation --data-dir DIR --out OUT [--cleaning DIR]: replay the year with the batteries held for the peak."""
from __future__ import annotations

import sys
from pathlib import Path

from .. import data
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    p = data.parser("Replay ENGIE's 2025 with the 80 batteries held for the evening peak, the plan reading only the grid's loading.")
    p.add_argument("--cleaning", default=None, help="a folder a meter-cleaning run wrote (default OUT/meter_cleaning, made when missing)")
    args = p.parse_args(argv)
    try:
        root = data.data_dir(args.data_dir)
        out = data.out_dir(args.out)
        run(root, out, Path(args.cleaning).expanduser() if args.cleaning else out / "meter_cleaning")
    except data.DataMissing as e:
        print(f"peak_allocation: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
