"""python -m experiments.engie.meter_cleaning --data-dir DIR --out OUT: clean the 2025 grid readings, prove the cleaning, read the ruler."""
from __future__ import annotations

import sys

from .. import data
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    args = data.parser("Clean ENGIE's 2025 grid readings, prove the cleaning on the 2023 true state, and read the batteries' true response.").parse_args(argv)
    try:
        root = data.data_dir(args.data_dir)
        run(root, data.out_dir(args.out))
    except data.DataMissing as e:
        print(f"meter_cleaning: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
