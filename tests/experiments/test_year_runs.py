"""The year runs: the recorded runs with and without the community agent, a recorded evening's signed messages, the rule that chose the 48
evenings (on synthetic prices, and with ENGIE's data on its own)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from experiments.engie.year_runs import __main__ as cli
from experiments.engie.year_runs import compare, evening


@pytest.fixture(scope="module")
def recording():
    return compare.load()


def test_the_recording_holds_the_48_evenings_and_576_runs(recording):
    assert len(recording["evenings"]) == 48 and len(recording["runs"]) == 576
    by = {}
    for r in recording["runs"]:
        by.setdefault((r["weather"], r["tier"], r["community_agent"]), set()).add(r["evening"])
        assert len(r["promised_kw"]) == len(r["true_kw"]) == len(r["metered_kw"]) == 6
    assert len(by) == 12 and all(v == {e["evening"] for e in recording["evenings"]} for v in by.values())


def test_with_and_without_the_community_agent(recording):
    tab = compare.table(recording)
    a, b = tab["engie_t1_with"], tab["engie_t1_without"]
    assert (a["mean_miss_by_the_truth_pct"], b["mean_miss_by_the_truth_pct"]) == (-2.7, -16.9)          # the true shortfall, with and without
    assert (a["evenings_kept_by_the_truth"], b["evenings_kept_by_the_truth"]) == (22, 0)
    assert (a["promised_kw"], a["delivered_by_the_truth_kw"], a["delivered_by_the_meter_kw"]) == (1480.5, 1468.4, 1622.8)
    assert (b["delivered_by_the_truth_kw"], b["delivered_by_the_meter_kw"], b["half_hours_short_by_the_truth"], b["half_hours"]) == (1469.6, 1624.1, 288, 288)
    assert (a["members_get_usd"], b["members_get_usd"], a["buyers_pay_usd"], b["buyers_pay_usd"]) == (5617, 5622, 8022, 8029)
    assert (a["worst_evening_by_the_truth_pct"], b["worst_evening_by_the_truth_pct"]) == (-12.1, -24.6)
    assert [tab[f"engie_t{t}_with"]["mean_miss_by_the_truth_pct"] for t in (2, 3)] == [-1.2, -4.0]
    assert [tab[f"real_t{t}_without"]["mean_miss_by_the_truth_pct"] for t in (1, 2, 3)] == [-16.8, -8.6, -39.7]
    assert "2.7% with the community agent and 16.9% without it" in compare.headline(tab)


def test_counting_on_a_made_up_case():
    runs = [{"promised_kw": [100] * 6, "true_kw": [90] * 6, "metered_kw": [110] * 6, "buyers_pay_usd": 10.0, "members_paid_usd": 7.0},
            {"promised_kw": [100] * 6, "true_kw": [120] * 3 + [90] * 3, "metered_kw": [100] * 6, "buyers_pay_usd": 20.0, "members_paid_usd": 9.0}]
    c = compare.counts(runs)
    assert (c["mean_miss_by_the_truth_pct"], c["worst_evening_by_the_truth_pct"]) == (-5.0, -10.0)       # the second evening meets its promise
    assert (c["evenings_kept_by_the_truth"], c["evenings_kept_by_the_meter"], c["half_hours_short_by_the_truth"]) == (1, 2, 9)
    assert (c["buyers_pay_usd"], c["members_get_usd"]) == (15, 8)


def test_the_year_sets_are_each_months_dearest_evening(tmp_path):
    assert cli.main(["compare", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "with_and_without.json").read_text())
    if not out["recorded_year_sets"]:
        pytest.skip("no year sets in demo/recordings")
    assert all(v == {"evenings": 12, "each_months_dearest_of_the_48": 12} for v in out["recorded_year_sets"].values())


def test_the_recorded_evening_answers_in_three_signed_messages(tmp_path):
    if not evening.RECORDED.exists():
        pytest.skip("no recorded evening in demo/recordings")
    rows = evening.exchanges(evening.load())
    assert [(r["participant"], r["kind"]) for r in rows] == [("coordinator", "community"), ("site-pv-01", "solar-and-battery plant"),
                                                            ("site-pv-02", "solar-and-battery plant"), ("site-dc-01", "data center")]
    v = evening.verdict(rows)
    assert v["request_kinds"] == ["community.request"] and v["answer_kinds"] == ["community.answer"]
    assert v["requests_signed_by_one_key"] and v["answers_signed_by_their_own_keys"] and v["reports_sent_and_kept"]
    assert [r["report"]["kept"] for r in rows] == [155, 156, 156, 156]
    assert cli.main(["evening", "--out", str(tmp_path)]) == 0 and (tmp_path / "evening_messages.json").exists()


def test_envelopes_are_read_from_terminal_lines():
    trace = {"steps": [
        {"id": "a", "sim_time": "t", "from": "aggregator", "to": "site-dc-01", "title": "", "terminal": [
            {"text": "envelope  message_id=x  from=aggregator  to=site-dc-01  kind=community.request"}, {"text": "context   transactionId=req-9"},
            {"text": "signer 0011aa…  sig 99…"}]},
        {"id": "b", "sim_time": "t", "from": "site-dc-01", "to": "aggregator", "title": "", "terminal": [
            {"text": "envelope  message_id=y  from=site-dc-01  to=aggregator  kind=community.answer"}, {"text": "context   transactionId=req-9"},
            {"text": "signer 77bb…  sig 98…"}]},
        {"id": "c", "sim_time": "t", "from": "site-dc-01", "to": "aggregator", "title": "The data center reports upward", "terminal": [
            {"text": "signed rows sent: 1,056, then"}, {"text": "kept by the aggregator's agent: 1,056  ·  flagged: 0"}]}]}
    rows = evening.exchanges(trace)
    assert rows[0]["request"]["signer"] == "0011aa" and rows[0]["answer"]["signer"] == "77bb" and rows[0]["report"]["sent"] == 1056
    assert evening.verdict(rows)["reports_sent_and_kept"]


def test_the_rule_on_made_up_prices():
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    from experiments.engie.year_runs import choose
    assert choose.clock_changes(2025, "America/Chicago") == {date(2025, 3, 9), date(2025, 11, 2)}
    assert {date(2025, 1, 20), date(2025, 5, 26), date(2025, 11, 27)} <= choose.holidays(2025) and date(2026, 7, 3) in choose.holidays(2026)
    days = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    prices = pd.Series([100.0 + (d.day * 7919 % 97) / 3 for d in days], index=[d.date() for d in days])     # distinct prices, no pattern by weekday
    picked = choose.choose(prices, 2025, "America/Chicago")
    skip = choose.holidays(2025) | choose.clock_changes(2025, "America/Chicago")
    assert len(picked) == 48
    for m in range(1, 13):
        x = [e for e in picked if int(e["evening"][5:7]) == m]
        ds = sorted(date.fromisoformat(e["evening"]) for e in x)
        assert [e["kind"] for e in x].count("dearest") == 2 and all((b - a).days >= 3 for a, b in zip(ds, ds[1:]))
        assert any(d.weekday() >= 5 for d in ds) and not set(ds) & skip and all(d.day > 7 for d in ds if m == 1)
        eligible = prices[[d for d in prices.index if d.month == m and d not in skip and not (m == 1 and d.day <= 7)]]
        assert max(e["price_18_21_usd_mwh"] for e in x if e["kind"] == "dearest") == round(eligible.max(), 1)
    assert choose.compare(picked, picked) == [] and choose.compare(picked, picked[1:])


@pytest.mark.engie_data
def test_the_rule_gives_the_recorded_48_evenings_on_engies_prices(tmp_path):
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    from experiments.engie import data
    try:
        data.release(data.data_dir(), data.MARK_2025)
    except data.DataMissing as e:                          # the data folder lacks the 2025 release whose prices the rule reads
        pytest.skip(str(e))
    assert cli.main(["choose", "--data-dir", str(data.data_dir()), "--out", str(tmp_path)]) == 0
    chosen = json.loads((tmp_path / "evenings_48.json").read_text())["evenings"]
    assert len(chosen) == 48 and chosen == compare.load()["evenings"]
