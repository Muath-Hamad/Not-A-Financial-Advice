"""The live fetch waits out Yahoo's evening gap (pipeline/fetch_data.py).

After the post-market closes at 20:00 ET, Yahoo serves daily history without
the session's bar for every name that trades after hours, for a while; the
benchmark keeps its bar. Cycle A, started late by GitHub, used to hand the
data gate that stale universe (coverage 0.6%, 2026-09-28 to 2026-10-02).
Fake clock, fake refetch: no network.
"""

from __future__ import annotations

import pytest

import fetch_data

ASOF, PREV, OLD = "2026-10-02", "2026-10-01", "2026-09-02"
POLL, BUDGET = 600, 180 * 60


def manifest(n_lagging: int, n_current: int = 0, n_stale: int = 0, bench_last: str = ASOF):
    """A manifest in fetch order: halted names first (worst case for probes),
    then names one bar short, then names already at ASOF."""
    m = {"IXIC": {"status": "ok", "last": bench_last}}
    m.update({f"OLD{i}": {"status": "ok", "last": OLD} for i in range(n_stale)})
    m.update({f"LAG{i}": {"status": "ok", "last": PREV} for i in range(n_lagging)})
    m.update({f"CUR{i}": {"status": "ok", "last": ASOF} for i in range(n_current)})
    m["DEAD"] = {"status": "failed", "rows": 0}
    return m


class Yahoo:
    """Serves the ASOF bar from `arrives_at` seconds on (never if None); a
    halted name (OLD*) never gets one. Records every refetch."""

    def __init__(self, man: dict, arrives_at: float | None):
        self.man, self.arrives_at, self.t, self.calls = man, arrives_at, 0.0, []

    def sleep(self, s: float) -> None:
        self.t += s

    def clock(self) -> float:
        return self.t

    def refetch(self, code: str) -> bool:
        self.calls.append(code)
        if self.arrives_at is not None and self.t >= self.arrives_at \
                and not code.startswith("OLD"):
            self.man[code]["last"] = ASOF
        return self.man[code]["last"] == ASOF

    def wait(self, budget: float = BUDGET) -> dict:
        return fetch_data.wait_for_session(self.man, ASOF, 0.95, budget, POLL, self.refetch,
                                           sleep=self.sleep, clock=self.clock)


def test_a_normal_evening_does_not_wait():
    man = manifest(n_lagging=1, n_current=99)   # one name halted today: 99% coverage
    y = Yahoo(man, arrives_at=None)
    log = y.wait()
    assert log["rounds"] == [] and y.t == 0 and y.calls == []
    assert log["coverage_after"] == 0.99 and "gave_up" not in log


def test_waits_out_the_gap_then_stops_once_names_stop_arriving():
    man = manifest(n_lagging=300, n_current=2, n_stale=2)
    y = Yahoo(man, arrives_at=50 * 60)          # the bars return ~50 minutes in
    log = y.wait()
    rounds = log["rounds"]
    # rounds at 10..40 min re-poll five probes only and find nothing
    assert [r["polled"] for r in rounds[:4]] == [5, 5, 5, 5]
    assert all(r["caught_up"] == 0 for r in rounds[:4])
    # at 50 min a probe shows the bar, so every laggard is refetched
    assert rounds[4]["caught_up"] == 300 and rounds[4]["coverage"] >= 0.95
    # one more round finds only the halted names, which never arrive: stop
    assert len(rounds) == 6 and rounds[5]["caught_up"] == 0
    assert log["coverage_after"] == round(302 / 304, 4) and log["lagging_after"] == 2
    assert "gave_up" not in log and y.t == 60 * 60


def test_probes_skip_names_stale_for_weeks():
    man = manifest(n_lagging=40, n_stale=10)    # halted names come first in fetch order
    y = Yahoo(man, arrives_at=0)
    y.wait()
    assert y.calls[:5] == [f"LAG{i}" for i in range(5)]


def test_gives_up_at_the_budget_and_leaves_the_verdict_to_the_gate():
    man = manifest(n_lagging=300, n_current=2)
    y = Yahoo(man, arrives_at=None)
    log = y.wait()
    assert log["gave_up"] is True and len(log["rounds"]) == BUDGET // POLL
    assert y.t <= BUDGET and log["coverage_after"] < 0.95
    assert len(y.calls) == 5 * len(log["rounds"])   # probes only: Yahoo is spared


def test_a_zero_budget_never_sleeps():
    man = manifest(n_lagging=300, n_current=2)
    y = Yahoo(man, arrives_at=0)
    log = y.wait(budget=0)
    assert log["gave_up"] is True and log["rounds"] == [] and y.t == 0


def test_a_lagging_benchmark_is_waited_for_even_at_full_coverage():
    man = manifest(n_lagging=0, n_current=100, bench_last=PREV)
    y = Yahoo(man, arrives_at=20 * 60)
    log = y.wait()
    assert man["IXIC"]["last"] == ASOF and log["lagging_after"] == 0
    assert y.calls[0] == "IXIC"


def test_coverage_matches_the_data_gate_measure():
    man = manifest(n_lagging=1, n_current=3, bench_last=PREV)
    # the benchmark and failed names are outside the measure: 3 of 4 names
    assert fetch_data.session_coverage(man, ASOF) == pytest.approx(0.75)


def test_main_rewrites_the_late_names_and_logs_the_wait(tmp_path, monkeypatch):
    """The whole script on a three-name universe: AAA and BBB miss tonight's bar
    until 20 minutes in; CCC misses it too and every refetch of CCC fails, so
    its first fetch must stand rather than turn into a 'failed' entry."""
    import gzip
    import json

    import pandas as pd

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "universe_screened.json").write_text(json.dumps({"universe": [
        {"code": c, "name": c, "sector": "Tech"} for c in ("AAA", "BBB", "CCC")]}))
    raw = tmp_path / "data" / "raw_live"
    t = {"now": 0.0}
    fetched = []

    def fetch_one(symbol):
        fetched.append(symbol)
        if symbol == "CCC" and fetched.count("CCC") > 1:
            return None, None, "yfinance: boom"
        late = symbol != "^IXIC" and t["now"] < 20 * 60
        idx = pd.bdate_range(end=PREV if late else ASOF, periods=150, name="Date")
        return pd.DataFrame({"Close": 10.0}, index=idx), "yfinance", None

    monkeypatch.setattr(fetch_data, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_data, "RAW_DIR", raw)
    monkeypatch.setattr(fetch_data, "EXPECT_LAST", ASOF)
    monkeypatch.setattr(fetch_data, "WAIT_MAX_S", 60 * 60)
    monkeypatch.setattr(fetch_data, "WAIT_POLL_S", 600)
    monkeypatch.setattr(fetch_data, "fetch_one", fetch_one)
    monkeypatch.setattr(fetch_data.time, "monotonic", lambda: t["now"])
    monkeypatch.setattr(fetch_data.time, "sleep",
                        lambda s: t.__setitem__("now", t["now"] + s))

    assert fetch_data.main() == 0
    man = json.loads((raw / "_manifest.json").read_text())
    assert man["AAA"]["last"] == man["BBB"]["last"] == ASOF
    assert man["CCC"]["status"] == "ok" and man["CCC"]["last"] < ASOF   # kept, not "failed"
    with gzip.open(raw / "AAA.csv.gz", "rt") as f:
        assert f.read().rstrip().splitlines()[-1].startswith(ASOF)
    wait = json.loads((raw / "_fetch_wait.json").read_text())
    assert wait["coverage_before"] == 0 and wait["coverage_after"] == round(2 / 3, 4)
    assert wait["rounds"][0]["caught_up"] == 0 and wait["rounds"][1]["caught_up"] == 2
