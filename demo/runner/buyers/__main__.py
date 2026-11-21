"""One stand-in buyer: python -m demo.runner.buyers NAME --port PORT (the configuration in $MURMUR_CONFIG_DIR)."""
from __future__ import annotations

import argparse
import logging
import threading

import uvicorn

from murmur import config
from murmur.protocol import wire
from murmur.protocol.transport import TownSession

from .stand_in import StandInBuyer
from .utility_doors import build_app


def main() -> None:
    ap = argparse.ArgumentParser(prog="demo.runner.buyers", description="one stand-in buyer, listening on its configuration's bind_host")
    ap.add_argument("name", help="the buyer's name on the bus: utility or grid-operator")
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    buyer = StandInBuyer(a.name)
    if a.name != "utility":                               # each buyer joins the bus under its own name, with its own token
        buyer.town = TownSession(buyer.cfg["town_url"], buyer.cfg["town_run_id"], a.name, config.secret(f"{a.name}_town_token"))
    buyer.cfg.setdefault("utility_settle_quiet_s", 30.0)
    wire.open_log(str(config.log_dir() / f"town_wire_{a.name}.jsonl"))
    buyer.town.join_until_up(then=lambda: threading.Thread(target=buyer.inbox_loop, daemon=True).start(), log=lambda m: print(m, flush=True))
    threading.Thread(target=buyer.tick_loop, daemon=True).start()
    uvicorn.run(build_app(buyer), host=buyer.cfg["bind_host"], port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
