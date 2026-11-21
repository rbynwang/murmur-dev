"""python -m experiments.engie.referee --data-dir DIR --out OUT [--readings FILE]: call every report slot of ENGIE's 2025 release."""
from __future__ import annotations

import sys
from pathlib import Path

from .. import data
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    p = data.parser("Call every report slot of ENGIE's 2025 trust data at 30 minutes and at 2 hours, name the compromised participants, "
                    "and plant lies of known kind to see what is caught.")
    p.add_argument("--readings", default=None, help="a model's answers on the notes (default: the recorded model_readings.json of this package)")
    args = p.parse_args(argv)
    try:
        run(data.data_dir(args.data_dir), data.out_dir(args.out), Path(args.readings).expanduser() if args.readings else None)
    except data.DataMissing as e:
        print(f"referee: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
