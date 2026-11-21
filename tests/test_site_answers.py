"""A single site's answer to its aggregator's request always goes out, signed, exactly once on the bus: a row with an unreadable time
is answered with a refusal like any other bad row, and an answer the bus did not take is sent again, under the same id, when the
request comes again or on a later tick."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from demo.runner.bus import Run, make_bus
from murmur import config
from murmur.agents import site_service
from murmur.agents.site_service import SiteNode
from murmur.protocol import envelope, signing
from murmur.protocol.transport import TownSession

RUN = "run-answers"
TOKENS = {"aggregator": "t-agg", "site-pv-01": "t-pv"}


def key(name: str):
    return signing.load_or_create(config.CONFIG_DIR / "secrets" / f"{name}.key")


def request(rows: list, rid: str) -> dict:
    return envelope.make("request", sender="aggregator", receiver="site-pv-01", transaction_id=rid, key=key("aggregator"),
                         message={"request": {"id": rid, "community": "SITE_PV_01", "made_at": "2025-01-28 14:00", "rows": rows}})


@pytest.fixture
def site(agent_config, sites):
    run = Run(RUN, tokens=dict(TOKENS))
    client = TestClient(make_bus({RUN: run}))
    feed = {t: x for t, x in sites["site-pv-01"]["feed"].items() if "2025-01-28 17:45" <= t <= "2025-01-28 19:00"}
    agent_config(agent_name="site-pv-01", site=sites["site-pv-01"]["site"], site_limits={}, site_feed=feed,
                 site_aggregator={"name": "aggregator", "public_key": signing.public_hex(key("aggregator"))})
    node = SiteNode()
    node.town = TownSession("http://testserver", RUN, node.name, TOKENS[node.name], http=client)
    door = TestClient(site_service.build_app(node))
    door.post("/demo/clock", json={"start": "2025-01-28 14:00", "at": "2025-01-28 14:00", "step_seconds": 60, "loop_days": 0, "hold": True})
    yield node, run
    client.close()


def answers(run: Run, rid: str) -> list[dict]:
    return [e for e in run.record if e["event"] == "accepted" and e["message_id"] == f"site-pv-01:aggregator:on_request:{rid}"]


def test_a_row_with_an_unreadable_time_is_refused_with_a_signed_answer(site):
    node, run = site
    out = node.take("community.request", "aggregator", request([{"ts": "noon", "battery_kw": 100.0}], "req-noon"))
    assert out == "request refused: a request's rows are a time and numbers that aren't negative"
    node._answer("req-noon")                                 # the thread take() starts may still be on its way: sending twice is one message
    got = answers(run, "req-noon")
    assert len(got) == 1 and envelope.check(got[0]["body"], node.pub) and got[0]["body"]["message"]["answer"]["taken"] is False


def test_an_answer_the_bus_did_not_take_goes_again_under_the_same_id_and_only_once(site, monkeypatch):
    node, run = site
    real = node._send
    monkeypatch.setattr(node, "_send", lambda kind, body: False)          # the bus is down for the first try
    node.take("community.request", "aggregator", request([{"ts": "2025-01-28 18:00", "battery_kw": 100.0}], "req-1"))
    node._answer("req-1")
    assert answers(run, "req-1") == [] and node.asked["req-1"]["sent"] is False
    monkeypatch.setattr(node, "_send", real)
    assert node.take("community.request", "aggregator", request([{"ts": "2025-01-28 18:00", "battery_kw": 100.0}], "req-1")) == "request noted before"
    node._answer("req-1")
    node._answer("req-1")
    assert len(answers(run, "req-1")) == 1 and node.asked["req-1"]["sent"] is True
    assert answers(run, "req-1")[0]["body"]["message"]["answer"]["taken"] is True
