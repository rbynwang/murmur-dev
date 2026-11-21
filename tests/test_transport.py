"""The transport client against the local bus, in process: joins, sends, claims, acks, replays, refusals, leases, rejoins, a name taken again and
again, grants and the inbox poller."""
from __future__ import annotations

import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from starlette import testclient

from demo.runner.bus import Run, make_bus
from demo.runner.grants import Controllers
from murmur import config
from murmur.protocol.inbox import InboxPoller
from murmur.protocol.transport import TownIdentityConflict, TownSession

RUN = "run-1"
REFUSED = testclient.httpx.HTTPStatusError      # what the test client's own httpx raises for a 4xx: httpx2's where that is installed, else httpx's


@pytest.fixture
def bus():
    runs = {RUN: Run(RUN, tokens={"community": "t-c", "home-01": "t-h1", "home-02": "t-h2"})}      # the bus's own 30 s lease: a slow machine hands nothing out twice
    client = TestClient(make_bus(runs))
    yield runs[RUN], client
    client.close()


def session(client, name, token):
    return TownSession("http://testserver", RUN, name, token, http=client)


def accepted(run: Run) -> list[str]:
    """The ids of the messages the bus took, in the order it took them."""
    return [e["message_id"] for e in run.record if e["event"] == "accepted"]


def test_send_claim_ack_round_trip(bus):
    run, client = bus
    a, b = session(client, "home-01", "t-h1"), session(client, "community", "t-c")
    assert a.send("community", "beckn.on_discover", {"offer": 1}, "m-1") == {"message_id": "m-1", "accepted": True, "replay": False}
    assert b.notify() is True
    m = b.claim()
    assert {k: m[k] for k in ("message_id", "from", "to", "kind", "body")} == {"message_id": "m-1", "from": "home-01", "to": "community", "kind": "beckn.on_discover",
                                                                             "body": {"offer": 1}}
    assert b.ack(m["message_id"], m["fence"], "processed", {"note": "ok"}) == {"ok": True}
    assert b.claim() is None and b.notify() is False
    assert [(e["event"], e.get("status"), e.get("note")) for e in run.record] == [("accepted", None, None), ("ack", "processed", {"note": "ok"})]


def test_a_retry_of_the_same_body_is_a_replay_taken_once_and_the_same_id_from_another_sender_is_refused(bus):
    run, client = bus
    a, other = session(client, "home-01", "t-h1"), session(client, "home-02", "t-h2")
    a.send("community", "beckn.on_status", {"kw": 2}, "m-2")
    assert a.send("community", "beckn.on_status", {"kw": 2}, "m-2") == {"message_id": "m-2", "accepted": True, "replay": True} and a.replays == 1
    assert other.send("community", "beckn.on_status", {"kw": 2}, "m-2") == {"message_id": "m-2", "duplicate": True} and other.dropped == 1   # the same body, not its message
    assert a.send("community", "beckn.cancel", {"kw": 2}, "m-2") == {"message_id": "m-2", "duplicate": True}      # another kind is another message
    assert accepted(run) == ["m-2"] and session(client, "community", "t-c").claim()["from"] == "home-01"


def test_a_body_made_again_goes_as_the_first_one_while_that_is_in_its_time_and_a_changed_one_is_refused(bus):
    _, client = bus
    a = session(client, "home-01", "t-h1")
    first = {"context": {"timestamp": "2025-01-28T10:00:00Z", "sentWall": time.time(), "messageId": "x"}, "message": {"v": 1}}
    a.send("community", "beckn.update", first, "m-3")
    remade = {"context": {"timestamp": "2025-01-28T10:00:05Z", "sentWall": time.time(), "messageId": "y"}, "message": {"v": 1}}
    assert a.send("community", "beckn.update", remade, "m-3")["replay"] is True          # the first body went again: the remade one would have been refused
    changed = {**remade, "message": {"v": 2}}
    assert a.send("community", "beckn.update", changed, "m-3") == {"message_id": "m-3", "duplicate": True} and a.dropped == 1
    stale = {**first, "context": {**first["context"], "sentWall": time.time() - 901}}   # past the 900 s a message without a ttl of its own is read for
    a.send("community", "beckn.update", stale, "m-6")
    assert a.send("community", "beckn.update", remade, "m-6") == {"message_id": "m-6", "duplicate": True}       # so the body made again goes, and the bus keeps the first


def test_a_lease_that_runs_out_hands_the_message_out_again_and_the_old_fence_is_stale(bus):
    run, client = bus
    run.lease_s = 0.1
    a, b = session(client, "home-01", "t-h1"), session(client, "community", "t-c")
    a.send("community", "beckn.confirm", {"x": 1}, "m-4")
    first = b.claim()
    time.sleep(0.15)                                                # past the 0.1 s lease
    second = b.claim()
    assert second["message_id"] == "m-4" and second["fence"] != first["fence"]
    assert b.ack("m-4", first["fence"], "processed") == {"stale_fence": True}
    assert b.ack("m-4", second["fence"], "processed") == {"ok": True} and b.claim() is None


def test_a_replaced_session_joins_again_by_itself_and_its_message_goes(bus):
    run, client = bus
    a, rival = session(client, "home-01", "t-h1"), session(client, "home-01", "t-h1")
    a.join()
    old = a.session
    rival.join()                                                    # takes the name's session
    assert a.send("community", "beckn.on_status", {"kw": 1}, "m-5")["accepted"] and a.session != old and len(a.rejoins) == 1
    assert accepted(run) == ["m-5"]


def test_a_name_taken_a_third_time_within_two_minutes_pauses_its_session_instead_of_taking_it_back(bus):
    run, client = bus
    a, rival = session(client, "home-01", "t-h1"), session(client, "home-01", "t-h1")
    a.join()
    for i in range(2):                                              # twice the rival takes the name, and twice a joins again by itself
        rival.join()
        a.send("community", "beckn.on_status", {"i": i}, f"m-2{i}")
    rival.join()
    with pytest.raises(TownIdentityConflict, match="another process keeps taking"):
        a.send("community", "beckn.on_status", {"i": 2}, "m-22")
    with pytest.raises(TownIdentityConflict, match="paused"):
        a.claim()                                                   # paused: it calls the bus no more, so the rival keeps the name
    assert (a.conflicts, rival.claim(), len(rival.rejoins)) == (1, None, 0) and accepted(run) == ["m-20", "m-21"]


def test_a_wrong_or_missing_token_or_an_unknown_name_is_refused(bus):
    _, client = bus
    for name, token in (("home-01", "nope"), ("home-01", ""), ("home-09", "t-h1")):
        with pytest.raises(REFUSED) as refused:
            session(client, name, token).join()
        assert (refused.value.response.status_code, refused.value.response.json()) == (403, {"detail": "unknown name or token"})


def test_a_grant_join_proves_the_session_key(bus, tmp_path, monkeypatch):
    run, client = bus
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)            # the participant's configuration folder, for this test alone
    controllers = Controllers(tmp_path / "controllers")
    run.controllers = controllers.pinned(["home-02"])
    held = controllers.grant("home-02", RUN)
    path = tmp_path / "secrets" / "town_grants.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"home-02": held}))
    assert session(client, "home-02", "").join()["session"]
    other = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex()
    path.write_text(json.dumps({"home-02": {**held, "session_private": other}}))
    with pytest.raises(REFUSED) as refused:
        session(client, "home-02", "").join()
    assert refused.value.response.status_code == 403 and "the session proof does not match" in refused.value.response.json()["detail"]


def test_the_inbox_poller_hands_every_message_over_once_with_two_claimers_and_leaves_one_its_handler_fails_on_unacked(bus):
    run, client = bus
    a, b = session(client, "home-01", "t-h1"), session(client, "community", "t-c")
    for i in range(5):
        a.send("community", "beckn.on_status", {"i": i}, f"m-{10 + i}")
    got, errors = [], []

    def handle(msg):
        got.append(msg["body"]["i"])
        if msg["body"]["i"] == 2:
            raise ValueError("this one can't be read")
        b.ack(msg["message_id"], msg["fence"], "processed")
    poller = InboxPoller(b, handle, claimers=2, on_error=lambda where, exc: errors.append(where), alive=lambda: len(got) <= 5)   # a bus that hands out twice fails here, not hangs
    assert poller.drain()[1] is False and sorted(got) == [0, 1, 2, 3, 4] and (poller.stats()["handled"], errors) == (4, ["handle"])
    assert sorted(e["message_id"] for e in run.record if e["event"] == "ack") == ["m-10", "m-11", "m-13", "m-14"]   # m-12 stays leased: handed out again after its lease
    poller.pool.shutdown()
