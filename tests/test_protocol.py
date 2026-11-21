"""Signed envelopes, message ids and the rules for late and refused messages."""
from __future__ import annotations

import json
import re

import pytest

from murmur.protocol import envelope, ids, signing

NOW = 1_000_000.0                           # a fixed wall clock: 1970-01-12T13:46:40Z


@pytest.fixture
def key(tmp_path):
    return signing.load_or_create(tmp_path / "secrets" / "signing.key")


def test_a_key_is_made_once_and_read_back(tmp_path):
    path = tmp_path / "k" / "signing.key"
    a = signing.load_or_create(path)
    b = signing.load_or_create(path)
    assert signing.public_hex(a) == signing.public_hex(b)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in path.parent.iterdir()] == ["signing.key"]        # the file it was written to first is gone


def test_signature_verifies_and_any_change_breaks_it(key):
    body = signing.sign({"amount_kw": 12.5, "slots": [1, 2]}, key)
    pub = signing.public_hex(key)
    assert signing.verify(body, pub)
    assert not signing.verify({**body, "amount_kw": 12.6}, pub)
    assert not signing.verify({**body, "slots": [2, 1]}, pub)
    assert not signing.verify({**body, "signer": "00" * 32}, pub)
    assert not signing.verify({k: v for k, v in body.items() if k != "sig"}, pub)
    assert not signing.verify({**body, "sig": "not hex"}, pub)                # a broken signature is a refusal, not an error


def test_a_signature_is_checked_against_the_pinned_key_not_the_body(tmp_path, key):
    other, pinned = signing.load_or_create(tmp_path / "other.key"), signing.public_hex(key)
    forged = signing.sign({"amount_kw": 99}, other)
    claims = {"amount_kw": 99, "signer": pinned}                              # names the pinned signer, and another key signs it
    claims["sig"] = other.sign(signing.canonical(claims).encode()).hex()
    assert not signing.verify(forged, pinned) and not signing.verify(claims, pinned)
    assert signing.verify(forged, signing.public_hex(other))                  # each is a good signature, by the other key


def test_canonical_form_ignores_key_order_and_keeps_list_order():
    a = signing.canonical({"b": 1, "a": [2, {"d": 3, "c": 4}]})
    assert a == signing.canonical({"a": [2, {"c": 4, "d": 3}], "b": 1}) == '{"a":[2,{"c":4,"d":3}],"b":1}'
    assert signing.canonical({"é": [2, 1]}) == '{"é":[2,1]}'


def test_envelope_carries_context_and_verifies(key):
    body = envelope.make("on_discover", sender="home-01", receiver="community", transaction_id="t1", message={"offer": {"kw": 3}}, key=key)
    ctx = body["context"]
    assert (ctx["action"], ctx["bapId"], ctx["bppId"], ctx["transactionId"], ctx["ttl"]) == ("on_discover", "home-01", "community", "t1", "PT900S")
    assert (ctx["networkId"], ctx["domain"], ctx["version"]) == ("murmur.local/demo-deg", "beckn.one:deg:demand-flex:2.0.0", "2.0.0")
    assert envelope.check(body, signing.public_hex(key))
    assert not envelope.check({**body, "message": {"offer": {"kw": 30}}}, signing.public_hex(key))


def test_int_keys_are_signed_as_they_arrive(key):
    body = envelope.make("update", sender="community", receiver="home-01", transaction_id="t", message={"by_slot": {11: 1.0, 2: 3.0}}, key=key)
    arrived = json.loads(json.dumps(body))                                    # what the receiver reads off the bus
    assert list(body["message"]["by_slot"]) == list(arrived["message"]["by_slot"]) == ["11", "2"]
    assert envelope.check(arrived, signing.public_hex(key))


def test_an_envelope_made_again_with_its_own_id_and_time_is_the_same_byte_for_byte(key):
    def made() -> dict:
        return envelope.make("on_status", sender="community", receiver="home-01", transaction_id="t", message={"by_slot": {11: 1.0}}, key=key, sender_role="bpp",
                             message_id="m-1", wall=NOW, ttl_s=envelope.TTL_EVIDENCE_S)
    a = made()
    assert signing.canonical(a) == signing.canonical(made())
    ctx = a["context"]
    assert (ctx["bapId"], ctx["bppId"], ctx["messageId"], ctx["timestamp"], ctx["sentWall"], ctx["ttl"]) == \
        ("home-01", "community", "m-1", "1970-01-12T13:46:40Z", NOW, "PT86400S")
    assert (envelope.expired(a, NOW + 86400), envelope.expired(a, NOW + 86401)) == (None, 1.0)      # a statement of fact holds for a day


def test_ttl_and_expiry():
    assert [envelope.ttl_seconds(t) for t in ("PT900S", "PT15M", "PT1H30M", "P1D")] == [900, 900, 5400, 86400]
    assert [envelope.ttl_seconds(t, default=7) for t in ("bogus", "PT", "P", 900, None)] == [7, 7, 7, 7, 7]
    assert envelope.expired({"context": {"sentWall": NOW - 900, "ttl": "PT900S"}}, NOW) is None          # valid to its last second
    assert envelope.expired({"context": {"sentWall": NOW - 1000, "ttl": "PT900S"}}, NOW) == 100.0
    assert envelope.expired({"context": {"sentWall": NOW - 1000}}, NOW, default_ttl=60) == 940.0         # no ttl of its own: the receiver's
    assert envelope.expired({"context": {"sentWall": 0.0}}, NOW) is None                                 # undated: never expires


def test_refused_and_partly_answers_map_to_bus_statuses():
    assert envelope.ack_of(envelope.Refused("bad signature")) == ("rejected", {"note": "bad signature"})
    assert envelope.ack_of("done") == ("processed", {"note": "done"})
    assert envelope.ack_of(envelope.of_batch(["ok", envelope.Refused("no"), "ok"])) == ("processed", {"note": "ok; no; ok", "refused": 1})
    assert envelope.ack_of(envelope.of_batch([envelope.Refused("a"), envelope.Refused("b")])) == ("rejected", {"note": "a; b"})
    assert envelope.ack_of("x" * 300) == ("processed", {"note": "x" * 200})


def test_local_time_arithmetic():
    assert envelope.add_minutes("2025-01-28 23:45", 30) == "2025-01-29 00:15"
    assert envelope.add_minutes("2025-01-28 00:15", -30) == "2025-01-27 23:45"
    assert envelope.add_minutes("2024-02-28 23:00", 90) == "2024-02-29 00:30"


def test_sealed_ids_are_stable_per_key_and_unforgeable(tmp_path, key):
    a = ids.sealed(key, "play1", "home-01", "community", "beckn.on_status", "readings", "x")
    reloaded = signing.load_or_create(tmp_path / "secrets" / "signing.key")
    assert a == ids.sealed(reloaded, "play1", "home-01", "community", "beckn.on_status", "readings", "x")      # a retry after a restart names it again
    other = signing.load_or_create(tmp_path / "o.key")
    assert a != ids.sealed(other, "play1", "home-01", "community", "beckn.on_status", "readings", "x")
    assert a != ids.sealed(key, "play1", "home-01", "community", "beckn.on_status", "readings", "y")
    plain, tag = a.rsplit(":", 1)
    assert plain == "play1:home-01:community:on_status:readings:x" and re.fullmatch(r"[0-9a-f]{16}", tag)
    assert ids.sealed(None, "s", "a", "b", "beckn.k") == "s:a:b:k"


def test_an_answer_is_scoped_by_the_message_it_answers():
    ask = {"context": {"messageId": "m-1"}}
    assert ids.asked(ask) == ids.asked({"context": {"messageId": "m-1"}, "message": {"other": 1}})
    assert ids.asked(ask) != ids.asked({"context": {"messageId": "m-2"}})
    assert ids.asked({"message": {"a": 1}}) == ids.asked({"message": {"a": 1}}) != ids.asked({"message": {"a": 2}})      # no id: what it says


def test_a_batch_of_readings_is_named_by_its_slots_in_any_order():
    r = lambda c, s: {"message": {"performance": {"contract_id": c, "slot_id": s}}}       # noqa: E731
    assert ids.readings([r("c", 1), r("c", 2)]) == ids.readings([r("c", 2), r("c", 1)]) == ids.readings([r("c", "2"), r("c", "1")])
    assert ids.readings([r("c", 1)]) != ids.readings([r("c", 2)])
    assert ids.readings([r("c", 1)]) != ids.readings([r("d", 1)])
