"""Single sites and the aggregator: a site's limits and its answer to a request, the site service's HTTP doors and its control-token door, the
signed request, answer and report rows a site and the aggregator exchange over the in-process bus, the messages and report rows the aggregator
keeps, flags or refuses, the sites and requests it starts from, and a delivery that arrives twice."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from demo.runner.bus import Run, make_bus
from murmur import config
from murmur.agents import aggregator, site_service
from murmur.agents.aggregator import Aggregator, is_number, row_faults
from murmur.agents.community import community
from murmur.agents.site import Limits, Site
from murmur.agents.site_service import SiteNode
from murmur.protocol import doors, envelope, signing
from murmur.protocol.transport import TownSession

RUN, REQ = "run-sites", "req-site-pv-01-2025-01-28"
TOKENS = {"aggregator": "t-agg", "site-pv-01": "t-pv"}
ANSWER_ID = f"site-pv-01:aggregator:on_request:{REQ}"
ROW = community.row("SITE_PV_01", "2025-01-28 18:00", 240.0, 41.67, 0.15634, "follows the aggregator's request")
NOT_NUMBER = "the row holds something that is not a number where a number goes"
STUCK = "the same power 4 quarter hours running"


def key(name: str):
    return signing.load_or_create(config.CONFIG_DIR / "secrets" / f"{name}.key")


def pv(sites: dict, **kw) -> Site:
    return Site(**sites["site-pv-01"]["site"], **kw)


def quarter(hhmm: str, kw: float = 240.0) -> dict:
    return {**ROW, "timestamp": f"2025-01-28 {hhmm}", "reported_p_net_kw": kw}


def site_node(agent_config, sites: dict, **limits) -> SiteNode:
    """site-pv-01 as its service runs it, fed its fixture quarter hours from 17:45 to 19:00."""
    feed = {t: x for t, x in sites["site-pv-01"]["feed"].items() if "2025-01-28 17:45" <= t <= "2025-01-28 19:00"}
    agent_config(agent_name="site-pv-01", site=sites["site-pv-01"]["site"], site_limits=limits, site_feed=feed,
                 site_aggregator={"name": "aggregator", "public_key": signing.public_hex(key("aggregator"))})
    return SiteNode()


def aggregator_node(agent_config, sites: dict) -> Aggregator:
    agent_config(agent_name="aggregator", aggregator_requests=sites["site-pv-01"]["requests"],
                 aggregator_communities={"site-pv-01": {"id": "SITE_PV_01", "limit_out_kw": 1350.0, "public_key": signing.public_hex(key("site"))}})
    return Aggregator()


def on_bus(node, client: TestClient):
    node.town = TownSession("http://testserver", RUN, node.name, TOKENS[node.name], http=client)
    return node


def at(door: TestClient, ts: str) -> None:
    """Holds the node's replay clock on one quarter hour through its own door, which also starts its play."""
    assert door.post("/demo/clock", json={"start": ts, "loop_days": 0, "hold": True}).json()["now"] == ts


def drain(node) -> list[str]:
    """Hands every message waiting for the node to its own handler, oldest first, and returns their kinds."""
    kinds = []
    while (msg := node.town.claim()) is not None:
        node.handle(msg)
        kinds.append(msg["kind"])
    return kinds


def landed(run: Run, message_id: str) -> dict:
    """The body of a message a node sends from a thread of its own, once the bus holds it."""
    end = time.time() + 5.0
    while message_id not in run.messages and time.time() < end:
        time.sleep(0.01)
    return run.messages[message_id]["body"]


def report(signer, row: dict = ROW, to: str = "aggregator") -> dict:
    return envelope.make("report", sender="site-pv-01", receiver=to, transaction_id="report:SITE_PV_01:2025-01-28", key=signer, sender_role="bpp", message={"report": row})


def request(signer, rows: list, rid: str = "req-1", to: str = "site-pv-01", site_id: str = "SITE_PV_01") -> dict:
    return envelope.make("request", sender="aggregator", receiver=to, transaction_id=rid, key=signer,
                         message={"request": {"id": rid, "community": site_id, "made_at": "2025-01-28 14:00", "rows": rows}})


@pytest.fixture
def bus():
    run = Run(RUN, tokens=dict(TOKENS), lease_s=0.1)
    client = TestClient(make_bus({RUN: run}))
    yield run, client
    client.close()


@pytest.fixture
def control_token():
    path = config.CONFIG_DIR / "secrets" / doors.TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("door-token\n")
    yield path
    path.unlink()


@pytest.fixture
def evening(bus, agent_config, sites):
    """The aggregator's 14:00 request goes down at 17:45 and the site answers it; the site's rows from 17:45 to 18:45 go up, and the aggregator reads them all."""
    run, client = bus
    agg, site = on_bus(aggregator_node(agent_config, sites), client), on_bus(site_node(agent_config, sites), client)
    e = SimpleNamespace(run=run, agg=agg, site=site, agg_door=TestClient(aggregator.build_app(agg)), site_door=TestClient(site_service.build_app(site)))
    at(e.agg_door, "2025-01-28 17:45")
    at(e.site_door, "2025-01-28 17:45")
    site.tick()                                    # the first quarter hour sets the store from the feed: 900 kWh
    agg.tick()
    assert drain(site) == ["community.request"]
    landed(run, ANSWER_ID)
    at(e.site_door, "2025-01-28 18:45")
    site.tick()
    assert drain(agg) == ["community.report", "community.answer"] + ["community.report"] * 4
    return e


def test_a_site_gives_what_is_asked_while_its_charge_lasts_and_says_where_it_runs_out(sites):
    s = pv(sites, store_kwh=900.0)                 # 720 kWh above the 10 % floor: 648 kWh at the connection through 0.9
    assert s.ask({18: 540.0, 19: 540.0, 20: 540.0}) == {"site": "SITE_PV_01", "pause": {}, "battery": {
        18: {"asked_kw": 540.0, "will_give_kw": 540.0},
        19: {"asked_kw": 540.0, "will_give_kw": 108.0, "why_less": "the charge runs out"},
        20: {"asked_kw": 540.0, "will_give_kw": 0.0, "why_less": "the charge runs out"}}}
    assert s.asked_kw == {18: 540.0, 19: 540.0, 20: 540.0} and s.store_kwh == 900.0


def test_a_site_gives_no_more_than_its_nameplate_or_its_own_limits(sites):
    full = pv(sites, store_kwh=1620.0)
    assert full.ask({18: 1000.0})["battery"][18] == {"asked_kw": 1000.0, "will_give_kw": 900.0, "why_less": "above the battery's rating"}
    assert full.ask({18: 900.0004})["battery"][18] == {"asked_kw": 900.0, "will_give_kw": 900.0}            # less than a watt short is no shortfall to explain
    capped = pv(sites, store_kwh=1620.0, limits=Limits(give_max_kw=300.0))
    assert capped.ask({18: 540.0})["battery"][18] == {"asked_kw": 540.0, "will_give_kw": 300.0, "why_less": "the site set a limit"}
    held = pv(sites, store_kwh=1620.0, limits=Limits(hold=True, why="the site keeps its battery for itself tonight"))
    assert held.ask({18: 540.0})["battery"][18] == {"asked_kw": 540.0, "will_give_kw": 0.0, "why_less": "the site keeps its battery for itself tonight"}


def test_a_request_with_a_negative_or_unreadable_amount_or_a_pause_for_a_battery_is_refused_and_the_request_in_force_stays(sites):
    s = pv(sites, store_kwh=900.0)
    s.ask({18: 540.0})
    for bad in ({18: -1.0}, {24: 10.0}, {"18": 10.0}, {18: float("nan")}, {18: True}):
        with pytest.raises(community.Refused, match="battery rows are an hour of the day and a number that isn't negative"):
            s.ask(bad)
    with pytest.raises(community.Refused, match="only a data center is asked to pause work"):
        s.ask({18: 0.0}, {18: 50.0})
    assert (s.asked_kw, s.pause_kw) == ({18: 540.0}, {})


def test_a_site_is_a_solar_and_battery_plant_or_a_data_center_and_its_store_starts_inside_its_band(sites):
    assert (pv(sites).store_kwh, pv(sites, store_kwh=5000.0).store_kwh) == (180.0, 1620.0)
    with pytest.raises(ValueError, match="a solar-and-battery plant or a data center"):
        Site("SITE_X", "wind_farm", 100.0, 200.0)


def test_the_battery_gives_only_what_the_connection_has_room_for_and_the_gap_is_kept(sites):
    s = pv(sites, store_kwh=900.0)
    s.ask({18: 540.0})
    r = s.step("2025-01-28 18:00", base_kw=1000.0, recorded_kw=0.0, own_kwh=0.0)         # 1000 of the connection's 1350 kW already go out
    assert (r["battery_kw"], r["sent_out_kw"], round(s.store_kwh, 3)) == (350.0, 1350.0, 802.778)
    assert s.gaps == [{"ts": "2025-01-28 18:00", "asked_kw": 540.0, "given_kw": 350.0, "gap_kw": -190.0}]


def test_a_data_center_owes_the_work_it_pauses_and_runs_it_back_evenly_before_it_is_due(sites):
    dc = Site(**{**sites["site-dc-01"]["site"], "wait_h": 1.0}, store_kwh=400.0, limits=Limits(pause_max_kw=60.0))
    assert dc.ask({}, {20: 100.0}) == {"site": "SITE_DC_01", "battery": {}, "pause": {20: 60.0}}
    first = dc.step("2025-01-28 20:45", -800.0, 0.0, 0.0, postponable_share=0.5)
    assert (first["paused_kw"], first["sent_out_kw"], dc.owed_kwh()) == (60.0, -740.0, 15.0)
    owed = []
    for mm in ("00", "15", "30", "45"):                                                     # the pauses are over: 15 kWh over the next four quarter hours, its hour of wait
        r = dc.step(f"2025-01-28 21:{mm}", -800.0, 0.0, 0.0, postponable_share=0.5)
        owed.append((r["run_again_kw"], r["sent_out_kw"], dc.owed_kwh()))
    assert owed == [(15.0, -815.0, 11.25), (15.0, -815.0, 7.5), (15.0, -815.0, 3.75), (15.0, -815.0, 0.0)]


def test_the_site_service_shows_its_health_and_its_site_and_its_doors_stand_open_without_a_control_token(agent_config, sites):
    node = site_node(agent_config, sites, give_max_kw=300.0)
    app = TestClient(site_service.build_app(node))
    at(app, "2025-01-28 17:45")
    assert app.get("/health").json() == {"ok": True, "agent": "site-pv-01", "pubkey": node.pub, "now": "2025-01-28 17:45", "label": "Single site", "town": False,
                                         "doors": "open", "town_calls": None}
    assert app.get("/site").json() == {"agent": "site-pv-01", "pubkey": node.pub, "now": "2025-01-28 17:45", "site": "SITE_PV_01", "kind": "pv_bess", "store_kwh": 180.0,
                                       "work_still_owed_kwh": 0.0, "limits": {"give_max_kw": 300.0, "hold": False, "pause_max_kw": None}, "quarter_hours_run": 0,
                                       "first": None, "last": None, "rows_sent_up": 0, "rows_waiting": 0, "requests": {}, "gaps": [], "not_kept": {}}


def test_a_post_door_refuses_a_missing_or_wrong_control_token_and_an_empty_token_file_shuts_every_door(agent_config, sites, control_token):
    node = site_node(agent_config, sites)
    app, clock = TestClient(site_service.build_app(node)), {"start": "2025-01-28 17:45", "loop_days": 0, "hold": True}
    assert app.get("/health").json()["doors"] == "token" and app.get("/site").status_code == 200
    missing, wrong = app.post("/demo/clock", json=clock), app.post("/demo/clock", json=clock, headers={doors.HEADER: "not-the-token"})
    assert (missing.status_code, wrong.status_code) == (401, 401)
    assert missing.json() == {"detail": "This door needs the control token, in the X-Murmur-Token header."}
    assert (node.started, node.clock.held) == (False, False)
    assert app.post("/demo/clock", json=clock, headers={doors.HEADER: "door-token"}).json()["now"] == "2025-01-28 17:45" and node.started
    control_token.write_text("")
    assert [app.post("/demo/reset", headers=h).status_code for h in ({}, {doors.HEADER: ""}, {doors.HEADER: "door-token"})] == [401, 401, 401] and node.started
    assert app.get("/health").json()["doors"] == "token"


def test_a_site_takes_a_request_only_from_its_aggregator_under_its_key_and_answers_a_negative_row_with_a_refusal(bus, agent_config, sites, tmp_path):
    run, client = bus
    site, signer = on_bus(site_node(agent_config, sites), client), key("aggregator")
    at(TestClient(site_service.build_app(site)), "2025-01-28 14:00")
    rows = [{"ts": "2025-01-28 18:00", "battery_kw": 540.0}]
    stranger = "rejected: only its aggregator asks this site, and only with a request"
    assert site.take("community.request", "community", request(signer, rows)) == stranger
    assert site.take("community.report", "aggregator", request(signer, rows)) == stranger
    assert site.take("community.request", "aggregator", request(signing.load_or_create(tmp_path / "forged.key"), rows)) == "rejected: bad signature"
    assert site.take("community.request", "aggregator", request(signer, rows, to="site-dc-01")) == "rejected: not made for this site"
    assert site.take("community.request", "aggregator", request(signer, rows, site_id="SITE_DC_01")) == "rejected: not a request for this site"
    assert site.take("community.request", "aggregator", request(signer, [])) == "rejected: not a request for this site"
    assert site.refused == {stranger.removeprefix("rejected: "): 2, "bad signature": 1, "not made for this site": 1, "not a request for this site": 2} and site.asked == {}
    out = site.take("community.request", "aggregator", request(signer, [{"ts": "2025-01-28 18:00", "battery_kw": -5.0}], rid="req-neg"))
    why = "a request's rows are a time and numbers that aren't negative"
    assert isinstance(out, envelope.Refused) and out == f"request refused: {why}"
    answer = landed(run, "site-pv-01:aggregator:on_request:req-neg")
    assert envelope.check(answer, site.pub)
    assert answer["message"]["answer"] == {"request": "req-neg", "community": "SITE_PV_01", "taken": False, "why": why, "at": "2025-01-28 14:00"}
    assert site.view()["requests"] == {"req-neg": {"at": "2025-01-28 14:00", "answer": None, "taken": False}}


def test_a_site_and_the_aggregator_exchange_signed_messages_over_the_bus_and_the_aggregator_keeps_each_quarter_hour(evening):
    e = evening
    pubs = {"aggregator": e.agg.pub, "site-pv-01": e.site.pub}
    accepted = [m for m in e.run.record if m["event"] == "accepted"]
    assert [(m["from"], m["kind"]) for m in accepted] == [("site-pv-01", "community.report"), ("aggregator", "community.request"), ("site-pv-01", "community.answer")] \
        + [("site-pv-01", "community.report")] * 4
    assert all(envelope.check(m["body"], pubs[m["from"]]) for m in accepted)
    assert [(m["by"], m["status"], m["note"]["result"]) for m in e.run.record if m["event"] == "ack"] == [
        ("site-pv-01", "processed", "request taken: 40 quarter hours"), ("aggregator", "processed", "report row noted"), ("aggregator", "processed", "answer noted: taken")] \
        + [("aggregator", "processed", "report row noted")] * 4
    assert e.agg.answers[REQ] == {"from": "site-pv-01", "taken": True, "rows": 40, "too_late": None, "first": None, "last": None, "why": "the charge runs out",
                                  "at": "2025-01-28 17:45", "heard_at": "2025-01-28 17:45"}
    rows = e.agg_door.get("/aggregator/rows", params={"community": "site-pv-01"}).json()["rows"]
    assert [(r["timestamp"][11:], r["reported_p_net_kw"], r["reported_soc_percent"], r["quote_side"], r["text"]) for r in rows] == [
        ("17:45", -300.0, 50.0, "buy", "runs its own schedule"),
        *[(t, 240.0, soc, "sell", "follows the aggregator's request") for t, soc in (("18:00", 41.67), ("18:15", 33.33), ("18:30", 25.0), ("18:45", 16.67))]]
    assert e.agg.flags == [] and e.agg.refused == {}                # four equal rows are no stuck value while the request asks one flat amount
    assert e.agg_door.get("/aggregator/rows", params={"community": "site-dc-01"}).status_code == 404
    view = e.site_door.get("/site").json()
    assert {k: view[k] for k in ("store_kwh", "quarter_hours_run", "first", "last", "rows_sent_up", "rows_waiting", "gaps", "not_kept")} == {
        "store_kwh": 300.0, "quarter_hours_run": 5, "first": "2025-01-28 17:45", "last": "2025-01-28 18:45", "rows_sent_up": 5, "rows_waiting": 0, "gaps": [], "not_kept": {}}
    assert view["requests"][REQ]["answer"]["battery"]["19"] == {"asked_kw": 540.0, "will_give_kw": 108.0, "why_less": "the charge runs out"}


def test_a_delivery_made_twice_is_noted_once_and_a_different_row_for_a_kept_quarter_hour_is_refused(evening):
    e = evening
    assert e.site.take("community.request", "aggregator", e.run.messages[f"aggregator:site-pv-01:request:{REQ}"]["body"]) == "request noted before"
    assert e.agg.take("community.answer", "site-pv-01", e.run.messages[ANSWER_ID]["body"]) == "answer noted before"
    at(e.site_door, "2025-01-28 19:00")
    e.site.tick()                                                   # 120 kWh left above the floor: 432 kW for this quarter hour, not 540
    assert e.site.site.gaps == [{"ts": "2025-01-28 19:00", "asked_kw": 540.0, "given_kw": 432.0, "gap_kw": -108.0}]
    first = e.agg.town.claim()
    assert e.agg.take(first["kind"], first["from"], first["body"]) == "report row noted"          # kept, and no ack goes back
    time.sleep(0.15)
    again = e.agg.town.claim()                                      # the lease ran out: the bus hands the same message out again
    assert (again["message_id"], again["body"]) == (first["message_id"], first["body"]) and again["fence"] != first["fence"]
    e.agg.handle(again)
    assert (e.run.record[-1]["status"], e.run.record[-1]["note"]) == ("processed", {"result": "report row noted before"}) and e.agg.town.claim() is None
    kept = e.agg.rows["site-pv-01"]
    assert (len(kept), kept[-1]["timestamp"], kept[-1]["reported_p_net_kw"], kept[-1]["reported_soc_percent"]) == (6, "2025-01-28 19:00", 132.0, 10.0)
    other = report(e.site.key, {**kept[-1], "reported_p_net_kw": 500.0})
    assert e.agg.take("community.report", "site-pv-01", other) == "rejected: a second, different row for the same quarter hour"
    assert (len(e.agg.rows["site-pv-01"]), e.agg.rows["site-pv-01"][-1]["reported_p_net_kw"]) == (6, 132.0)
    assert e.agg.flags == [{"community": "site-pv-01", "timestamp": "2025-01-28 19:00", "what": "a second, different row for the same quarter hour: the first stands"}]


def test_a_row_the_bus_does_not_take_waits_and_goes_up_on_the_next_tick_in_order_and_once(bus, agent_config, sites):
    run, client = bus
    site, seen = on_bus(site_node(agent_config, sites), client), []
    door = TestClient(site_service.build_app(site))
    for ts, token in (("2025-01-28 18:00", "not-yet"), ("2025-01-28 18:15", TOKENS["site-pv-01"])):        # the bus lets the site in only at 18:15
        run.tokens["site-pv-01"] = token
        at(door, ts)
        site.tick()
        seen.append([door.get("/site").json()[k] for k in ("quarter_hours_run", "rows_sent_up", "rows_waiting")])
    assert seen == [[2, 0, 2], [3, 3, 0]] and [m["message_id"][-5:] for m in run.record if m["event"] == "accepted"] == ["17:45", "18:00", "18:15"]   # none lost or sent twice


def test_row_faults_keeps_a_well_formed_row_and_refuses_one_that_is_no_report_row_or_for_another_site_or_off_the_quarter_hour():
    assert row_faults(ROW, "SITE_PV_01", 1350.0, []) == ([], [])
    for bad, why in (("a line", "not a report row"), ({k: v for k, v in ROW.items() if k != "timestamp"}, "not a report row"),
                     ({**ROW, "member": "home-01"}, "not a report row"), ({**ROW, "entity_id": "SITE_DC_01"}, "the row is for another community"),
                     ({**ROW, "timestamp": "2025-01-28 18:10"}, "the row's time is not a quarter hour"),
                     ({**ROW, "timestamp": "2025-01-28T18:00"}, "the row's time is not a quarter hour"), ({**ROW, "timestamp": None}, "the row's time is not a quarter hour")):
        assert row_faults(bad, "SITE_PV_01", 1350.0, []) == ([why], [])


def test_row_faults_refuses_anything_but_a_number_where_a_number_goes_and_keeps_power_and_prices_below_zero():
    for field, value in (("reported_p_net_kw", "240"), ("reported_soc_percent", float("nan")), ("quote_price_usd_kwh", float("inf")), ("meter_p_net_kw", True), ("text", 5)):
        assert row_faults({**ROW, field: value}, "SITE_PV_01", 1350.0, []) == ([NOT_NUMBER], [])
    assert row_faults({**ROW, "reported_p_net_kw": -300.0, "quote_side": "buy", "quote_price_usd_kwh": -0.01}, "SITE_PV_01", 1350.0, []) == ([], [])
    assert [is_number(v) for v in (0, -2.5, True, "1", None, float("nan"), float("-inf"))] == [True, True, False, False, False, False, False]


def test_a_kept_row_is_flagged_for_a_charge_outside_its_band_more_than_its_connection_or_one_power_held_four_quarter_hours_unasked():
    assert row_faults({**ROW, "reported_soc_percent": 95.0}, "SITE_PV_01", 1350.0, []) == ([], ["charge outside 10 to 90%"])
    assert row_faults({**ROW, "reported_soc_percent": -5.0}, "SITE_PV_01", 1350.0, []) == ([], ["charge outside 10 to 90%"])
    assert row_faults(quarter("18:00", 1352.0), "SITE_PV_01", 1350.0, []) == ([], ["more sent out than the connection allows"])
    assert row_faults(quarter("18:00", 1351.0), "SITE_PV_01", 1350.0, []) == ([], [])          # within a tenth of a percent of the connection
    assert row_faults(quarter("18:00", 5000.0), "SITE_PV_01", None, []) == ([], [])             # no limit known at the connection
    run = [quarter("17:15"), quarter("17:30"), quarter("17:45")]
    flat = {f"2025-01-28 {t}": 540.0 for t in ("17:15", "17:30", "17:45", "18:00")}
    assert row_faults(ROW, "SITE_PV_01", 1350.0, run) == ([], [STUCK])
    assert row_faults(ROW, "SITE_PV_01", 1350.0, run, flat) == ([], [])
    assert row_faults(ROW, "SITE_PV_01", 1350.0, run, {**flat, "2025-01-28 18:00": 300.0}) == ([], [STUCK])
    assert row_faults(ROW, "SITE_PV_01", 1350.0, [quarter("17:00"), quarter("17:30"), quarter("17:45")]) == ([], [])      # a missing quarter hour breaks the run
    assert row_faults(quarter("18:00", 0.0), "SITE_PV_01", 1350.0, [quarter(t, 0.0) for t in ("17:15", "17:30", "17:45")]) == ([], [])


def test_the_aggregator_keeps_nothing_from_a_stranger_a_forged_or_misaddressed_message_or_an_answer_to_nothing_it_asked(agent_config, sites, tmp_path):
    agg, signer = aggregator_node(agent_config, sites), key("site")
    answer = envelope.make("on_request", sender="site-pv-01", receiver="aggregator", transaction_id=REQ, key=signer, sender_role="bpp",
                           message={"answer": {"request": REQ, "community": "SITE_PV_01", "taken": True}})
    took = [agg.take("community.report", "site-dc-01", report(signer)), agg.take("community.report", "site-pv-01", ["not", "a", "body"]),
            agg.take("community.report", "site-pv-01", report(signing.load_or_create(tmp_path / "forged.key"))),
            agg.take("community.report", "site-pv-01", report(signer, to="community")), agg.take("community.report", "site-pv-01", report(signer, {**ROW, "entity_id": "SITE_DC_01"})),
            agg.take("community.answer", "site-pv-01", answer), agg.take("community.status", "site-pv-01", report(signer))]
    assert took == ["rejected: " + w for w in ("not a community on this aggregator's list", "not a signed message", "bad signature", "not made for this aggregator",
                                               "the row is for another community", "an answer to nothing this aggregator asked", "unknown kind")]
    assert all(isinstance(t, envelope.Refused) for t in took) and (agg.rows, agg.answers, agg.flags) == ({"site-pv-01": []}, {}, [])
    assert agg.take("community.report", "site-pv-01", report(signer)) == "report row noted"


def test_a_site_enrolled_without_a_key_is_held_to_the_key_its_first_signed_message_carries(agent_config, tmp_path):
    agent_config(agent_name="aggregator", aggregator_communities={"site-pv-01": {"id": "SITE_PV_01", "limit_out_kw": 1350.0}})
    agg = Aggregator()
    first, other = signing.load_or_create(tmp_path / "first.key"), signing.load_or_create(tmp_path / "other.key")
    assert agg.take("community.report", "site-pv-01", report(first)) == "report row noted"
    assert agg.take("community.report", "site-pv-01", report(other, quarter("18:15"))) == "rejected: bad signature"
    assert agg.pins == {"site-pv-01": signing.public_hex(first)} and agg.view()["communities"]["site-pv-01"]["key"] == "pinned at its first message"


def test_the_aggregator_starts_only_from_sites_with_an_id_a_positive_connection_limit_and_a_real_key_and_requests_of_their_own(agent_config, sites):
    req = sites["site-pv-01"]["requests"][0]
    for site, plan, why in (({"id": "SITE_PV_01", "limit_out_kw": -5.0}, [], "aggregator_communities"), ({"id": "SITE PV 01"}, [], "aggregator_communities"),
                            ({"id": "SITE_PV_01", "public_key": "ab" * 31}, [], "aggregator_communities"),
                            ({"id": "SITE_PV_01"}, [{**req, "to": "site-dc-01"}], "aggregator_requests"), ({"id": "SITE_PV_01"}, [req, req], "two requests share an id")):
        agent_config(agent_name="aggregator", aggregator_communities={"site-pv-01": site}, aggregator_requests=plan)
        with pytest.raises(ValueError, match=why):
            Aggregator()
