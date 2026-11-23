"""The audience's door: the six presets, the cooldown, the round of votes and the evening's twenty (crowd.py), a tap's way through
the console's door on a free port (POST /live/surprise), and what the feed tells every viewer of it."""
from __future__ import annotations

import http.client
import json
from types import SimpleNamespace

import pytest

from demo.console import commands as C
from demo.console import crowd as K
from demo.console import feed as F
from demo.console import server as S
from demo.console import timeline as T

KEY = "a-test-key_0123456789-ABCDEFGHIJ"
V1 = {"schema": "murmur.live.v1", "parts": {}}


class Wall:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def crowd(presets=K.PRESETS) -> tuple[K.Crowd, Wall]:
    wall = Wall()
    c = K.Crowd(wall, on=True)
    c.reset(presets)
    c.open = True
    return c, wall


# ---------------------------------------------------------------------- the presets, the cooldown and the votes
def test_every_preset_is_a_surprise_the_console_fills_in_by_itself():
    facts = {"play": "running", "roster": {"homes": [{"id": "home-01", "battery": True}], "buildings": [{"id": "building-01"}], "buyers": ["utility"]}}
    made = {k: C.check({"do": "surprise", "kind": k}, facts)[0] for k in K.PRESETS}
    assert len(K.PRESETS) == 6 and all(made.values()) and "note" not in K.PRESETS
    assert (made["battery_low"]["pct"], made["emergency"]["kw"], made["weather"]["pv"]) == (10, 20, 0.2)


def test_the_first_tap_fires_at_once_and_starts_a_cooldown_of_10_seconds():
    c, wall = crowd()
    assert (K.COOLDOWN_S, K.MOST, K.ADDRESS_VOTES) == (10.0, 20, 200) and c.tap("weather", "v1", "a") == K.FIRE
    assert c.state() == {"open": True, "presets": list(K.PRESETS), "cooldown_s": 10, "votes": {}, "left": 19, "most": 20,
                         "last": {"kind": "weather", "by": "viewer", "ago_s": 0}}
    wall.t += 9.2
    assert c.state()["cooldown_s"] == 1 and c.due() is None
    wall.t += 1
    assert c.state()["cooldown_s"] == 0 and c.due() is None and c.tap("car_now", "v2", "a") == K.FIRE


def test_a_tap_during_the_cooldown_is_a_vote_one_a_viewer_in_a_round():
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    assert [c.tap("emergency", "v1", "a"), c.tap("car_now", "v1", "a"), c.tap("emergency", "v2", "b"), c.tap("car_now", "v3", "c")] == [K.VOTE, K.AGAIN, K.VOTE, K.VOTE]
    assert c.state()["votes"] == {"emergency": 2, "car_now": 1} and c.state()["left"] == 19 and c.due() is None


def test_when_the_cooldown_ends_the_round_s_winner_fires_and_the_next_round_begins():
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    for viewer, kind in (("v1", "car_now"), ("v2", "emergency"), ("v3", "emergency")):
        c.tap(kind, viewer, viewer)
    wall.t += 10
    assert c.due() == "emergency" and c.due() is None
    s = c.state()
    assert (s["cooldown_s"], s["votes"], s["left"], s["last"]) == (10, {}, 18, {"kind": "emergency", "by": "vote", "ago_s": 0})
    assert c.tap("car_now", "v1", "a") == K.VOTE                      # a new round: the same viewer votes again


def test_of_equal_votes_the_preset_voted_for_first_wins():
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    wall.t += 1
    c.tap("battery_fault", "v2", "b")
    wall.t += 1
    c.tap("car_now", "v3", "c")
    wall.t += 30
    assert c.due() == "battery_fault"


def test_a_tap_after_the_cooldown_while_votes_wait_is_one_more_vote_and_never_a_second_surprise():
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    c.tap("car_now", "v2", "b")
    wall.t += 11
    assert c.tap("emergency", "v3", "c") == K.VOTE and c.state()["left"] == 19 and c.due() == "car_now"


def test_an_evening_has_twenty_and_the_next_has_twenty_again():
    c, wall = crowd()
    for i in range(K.MOST):
        assert c.tap("weather", f"v{i}", "a") == K.FIRE
        wall.t += 10
    assert c.tap("weather", "v9", "a") == K.DONE and c.state()["left"] == 0 and c.state()["open"] is False
    c.reset()
    assert c.state()["left"] == 20 and c.tap("weather", "v9", "a") == K.FIRE


def test_votes_left_when_the_evening_s_twenty_are_spent_or_it_has_ended_fire_nothing():
    c, wall = crowd()
    for i in range(K.MOST - 1):
        c.tap("weather", f"v{i}", "a")
        wall.t += 10
    c.tap("weather", "v4", "a")
    assert c.tap("car_now", "v5", "b") == K.DONE
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    c.tap("car_now", "v2", "b")
    c.open = False
    wall.t += 10
    assert c.due() is None and c.state()["votes"] == {} and c.state()["left"] == 19


def test_one_address_has_two_hundred_votes_in_a_round_so_a_hall_votes_and_one_machine_cannot_fill_it():
    c, wall = crowd()
    c.tap("weather", "v0", "a")
    did = [c.tap("car_now", f"made-up-{i}", "one-address") for i in range(K.ADDRESS_VOTES + 3)]
    assert did.count(K.VOTE) == K.ADDRESS_VOTES and did[-3:] == [K.AGAIN] * 3 and c.tap("emergency", "v1", "another") == K.VOTE


def test_the_door_is_shut_unless_it_was_opened_for_an_audience_and_an_evening_plays():
    wall = Wall()
    c = K.Crowd(wall)
    c.open = True
    assert c.tap("weather", "v1", "a") == K.CLOSED and c.state() is None
    c, wall = crowd()
    c.open = False
    assert c.tap("weather", "v1", "a") == K.CLOSED and c.state()["open"] is False


def test_an_evening_takes_only_the_presets_its_network_can_play_and_no_other_word():
    c, wall = crowd(["weather", "car_now", "note", "nonsense"])
    assert c.state()["presets"] == ["car_now", "weather"]
    assert [c.tap(k, "v1", "a") for k in ("building_need", "note", "", "WEATHER")] == [K.CLOSED] * 4 and c.state()["left"] == 20


def test_a_surprise_that_could_not_be_posted_is_given_back_to_the_evening():
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    c.unfire()
    assert (c.state()["left"], c.state()["cooldown_s"], c.state()["last"]) == (K.MOST, 0, None) and c.tap("weather", "v1", "a") == K.FIRE


# ---------------------------------------------------------------------- a tap at the console's door
class Driver:
    def __init__(self) -> None:
        self.taps: list[tuple[str, str, str]] = []
        self.did = K.FIRE
        self.crowd = SimpleNamespace(on=False)        # the console was not started for an audience

    def tap(self, kind: str, viewer: str, address: str) -> str:
        self.taps.append((kind, viewer, address))
        return self.did


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    page = tmp_path_factory.mktemp("crowd") / "index.html"
    page.write_bytes(b"page")
    srv = S.serve("127.0.0.1", 0, page, F.Log(), None, KEY, V1)
    yield SimpleNamespace(srv=srv, port=srv.server_address[1])
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def door(served):
    served.driver = served.srv.driver = Driver()
    return served


def tap(door, body, headers: dict | None = None, method: str = "POST", path: str = "/live/surprise") -> SimpleNamespace:
    conn = http.client.HTTPConnection("127.0.0.1", door.port, timeout=10)
    try:
        sent = {"Host": f"127.0.0.1:{door.port}", "Content-Type": "application/json"} | (headers or {})
        conn.request(method, path, body=body if isinstance(body, (bytes, str)) else json.dumps(body), headers=sent)
        r = conn.getresponse()
        return SimpleNamespace(code=r.status, headers={k.lower(): v for k, v in r.getheaders()}, body=r.read())
    finally:
        conn.close()


def test_a_tap_needs_no_key_and_reaches_the_driver_with_its_preset_alone(door):
    r = tap(door, {"kind": "weather"}, {"X-Murmur-Viewer": "viewer-token-0123456789"})
    assert (r.code, json.loads(r.body)) == (200, {"did": "fire"}) and r.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in r.headers
    assert door.driver.taps == [("weather", "viewer-token-0123456789", "127.0.0.1")]


@pytest.mark.parametrize("did", [K.VOTE, K.AGAIN, K.DONE, K.CLOSED])
def test_the_door_answers_with_the_crowd_s_own_word(door, did):
    door.driver.did = did
    assert json.loads(tap(door, {"kind": "car_now"}).body) == {"did": did}


@pytest.mark.parametrize("body", [{"kind": "note"}, {"kind": "building_closed"}, {"kind": "weather", "pv": 0}, {"kind": "weather", "note": "hello"},
                                  {"kind": "car_now", "who": "home-01"}, {"do": "surprise", "kind": "weather"}, {"kind": ["weather"]}, {"kind": 1}, {},
                                  ["weather"], "weather", "", b"{", b"\xff", '{"kind": "weather", "kind": "note"}', {"Kind": "weather"}])
def test_anything_but_one_preset_is_refused_in_the_one_fixed_sentence(door, body):
    r = tap(door, body)
    assert (r.code, json.loads(r.body)) == (400, {"error": C.say("preset")}) and door.driver.taps == []


def test_a_tap_is_at_most_256_bytes(door):
    fits = '{"kind": "weather"' + " " * (S.TAP_LIMIT - 19) + "}"
    assert len(fits) == S.TAP_LIMIT and tap(door, fits).code == 200
    assert tap(door, fits + " ").code == 400 and tap(door, " " * 5000).code == 400 and len(door.driver.taps) == 1


@pytest.mark.parametrize("kind", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_a_tap_is_sent_as_json_which_no_other_origin_s_form_can_send(door, kind):
    assert tap(door, {"kind": "weather"}, {"Content-Type": kind}).code == 400 and door.driver.taps == []
    assert tap(door, {"kind": "weather"}, {"Content-Type": "application/json; charset=utf-8"}).code == 200


@pytest.mark.parametrize("sent, viewer, address", [
    ({}, "127.0.0.1", "127.0.0.1"),
    ({"X-Murmur-Viewer": "short"}, "127.0.0.1", "127.0.0.1"),
    ({"X-Murmur-Viewer": "has a space in it, and more"}, "127.0.0.1", "127.0.0.1"),
    ({"X-Forwarded-For": "203.0.113.9"}, "203.0.113.9", "203.0.113.9"),
    ({"X-Forwarded-For": "198.51.100.1, 203.0.113.9"}, "203.0.113.9", "203.0.113.9"),
    ({"X-Forwarded-For": "203.0.113.9", "X-Murmur-Viewer": "A" * 64}, "A" * 64, "203.0.113.9"),
    ({"X-Forwarded-For": "x" * 300}, "x" * 64, "x" * 64)])
def test_a_viewer_is_its_page_s_token_else_the_address_a_gateway_wrote_else_the_caller_s(door, sent, viewer, address):
    tap(door, {"kind": "weather"}, sent)
    assert door.driver.taps == [("weather", viewer, address)]


def test_a_tap_wants_the_door_s_own_host_and_a_door_whose_driver_takes_none_refuses_it(door):
    assert tap(door, {"kind": "weather"}, {"Host": "example.org"}).code == 403 and door.driver.taps == []
    door.srv.driver = SimpleNamespace()
    assert tap(door, {"kind": "weather"}).code == 400


ASKS = {"Origin": "https://pages.example.org", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-murmur-viewer"}


def test_on_a_console_for_an_audience_another_origin_s_page_may_ask_to_send_a_tap_and_is_told_yes(door):
    door.driver.crowd.on = True
    r = tap(door, "", ASKS, "OPTIONS")
    assert (r.code, r.body, r.headers["access-control-allow-origin"], r.headers["access-control-allow-methods"]) == (204, b"", "*", "POST")
    assert {h.strip().lower() for h in r.headers["access-control-allow-headers"].split(",")} == {"content-type", "x-murmur-viewer"}
    r = tap(door, {"kind": "weather"}, {"Origin": "https://pages.example.org", "X-Murmur-Viewer": "viewer-token-0123456789"})
    assert (r.code, r.headers["access-control-allow-origin"]) == (200, "*") and door.driver.taps == [("weather", "viewer-token-0123456789", "127.0.0.1")]
    assert tap(door, {"kind": "note"}).headers["access-control-allow-origin"] == "*"          # a refusal's words can be read as well


@pytest.mark.parametrize("path", ["/", "/how", "/live/state.json", "/console/state", "/console/do", "/live/surprise/", "/nowhere"])
def test_no_other_question_of_another_origin_is_answered(door, path):
    door.driver.crowd.on = True
    r = tap(door, "", ASKS | {"Access-Control-Request-Headers": "x-murmur-console"}, "OPTIONS", path)
    assert (r.code, r.body) == (403, b"") and not [h for h in r.headers if h.startswith("access-control")]


def test_a_console_with_no_audience_or_behind_a_gateway_that_answers_for_it_says_nothing_to_another_origin(door):
    assert tap(door, "", ASKS, "OPTIONS").code == 403 and "access-control-allow-origin" not in tap(door, {"kind": "weather"}).headers
    door.driver.crowd.on, door.srv.cors = True, False
    try:
        assert tap(door, "", ASKS, "OPTIONS").code == 403 and "access-control-allow-origin" not in tap(door, {"kind": "weather"}).headers
    finally:
        door.srv.cors = True
    assert tap(door, "", ASKS | {"Host": "example.org"}, "OPTIONS").code == 403


# ---------------------------------------------------------------------- what the feed tells every viewer
def test_the_feed_carries_the_crowd_and_the_loop_only_on_a_console_that_has_them():
    log = F.Log()
    log.reset(1, {"key": "one", "boxes": []}, T.build({"date": "2025-01-28", "window": ["18:00", "21:00"]}, []))
    assert not {"crowd", "loop"} & set(log.answer(V1, 0)["v2"])
    c, wall = crowd()
    c.tap("weather", "v1", "a")
    loop = {"day": 2, "days": 3, "date": "2025-01-28", "label": "Winter peak", "next_s": None}
    log.show(c.state(), loop)
    v2 = log.answer(V1, 0)["v2"]
    assert v2["crowd"]["left"] == 19 and v2["crowd"]["last"]["kind"] == "weather" and v2["loop"] == loop
    assert "v1" not in json.dumps(v2) and '"a"' not in json.dumps(v2)                   # no viewer and no address leaves
    log.show(None, None)
    assert not {"crowd", "loop"} & set(log.answer(V1, 0)["v2"])
