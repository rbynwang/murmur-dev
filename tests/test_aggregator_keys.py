"""The aggregator's key for a community enrolled without one: the first message that verifies under the key it was signed with pins
that key, a message whose signature fails pins nothing (so a forgery sent first cannot lock the real community out), and once a key
is pinned a message signed with any other key is refused."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from murmur.agents.aggregator import REPORT, Aggregator
from murmur.agents.community import community
from murmur.protocol import envelope, signing

ROW = community.row("SITE_PV_01", "2025-01-28 18:00", 240.0, 41.67, 0.15634, "follows the aggregator's request")
BAD = "rejected: bad signature"


def report(key, row: dict = ROW) -> dict:
    return envelope.make("report", sender="site-pv-01", receiver="aggregator", transaction_id="report:SITE_PV_01:2025-01-28", key=key,
                         sender_role="bpp", message={"report": row})


def unenrolled(agent_config) -> Aggregator:
    agent_config(agent_name="aggregator", aggregator_requests=[],
                 aggregator_communities={"site-pv-01": {"id": "SITE_PV_01", "limit_out_kw": 1350.0, "public_key": None}})
    return Aggregator()


def test_a_forged_first_message_pins_nothing_and_the_real_site_is_heard_after_it(agent_config):
    a, real = unenrolled(agent_config), Ed25519PrivateKey.generate()
    forged = {**report(real), "signer": signing.public_hex(Ed25519PrivateKey.generate())}     # claims a key that did not sign it
    assert a.take(REPORT, "site-pv-01", forged) == BAD and a.pins == {}
    assert a.take(REPORT, "site-pv-01", report(real)) == "report row noted"
    assert a.pins == {"site-pv-01": signing.public_hex(real)}


def test_once_a_key_is_pinned_a_message_signed_with_another_key_is_refused(agent_config):
    a, real = unenrolled(agent_config), Ed25519PrivateKey.generate()
    assert a.take(REPORT, "site-pv-01", report(real)) == "report row noted"
    later = {**ROW, "timestamp": "2025-01-28 18:15"}
    assert a.take(REPORT, "site-pv-01", report(Ed25519PrivateKey.generate(), later)) == BAD
    assert a.take(REPORT, "site-pv-01", report(real, later)) == "report row noted"
    assert a.pins == {"site-pv-01": signing.public_hex(real)}
