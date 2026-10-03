"""Which session a Cycle A run decides, and the dead-man check that follows
every finished Cycle A (docs/06). GitHub starts the 17:00 ET cron hours late
and the fetch can wait out Yahoo's evening gap, so a cycle — or its manual
re-run after a timeout — may land after midnight ET. No network.
"""

from __future__ import annotations

import datetime as dt
import sys
from zoneinfo import ZoneInfo

import pytest

import calendar_util
import config
import cycle_a
import deadman
from conftest import write_json

ET = ZoneInfo("America/New_York")
MON, TUE, FRI = "2026-09-28", "2026-09-29", "2026-09-25"


def et(day: str, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hh, mm), tzinfo=ET)


@pytest.mark.parametrize("now, session", [
    (et(MON, 17, 0), MON),          # the cron on time
    (et(MON, 16, 50), MON),         # 45 minutes after the close
    (et(MON, 16, 30), FRI),         # closing prints still settling: the previous session
    (et(MON, 20, 49), MON),         # GitHub's usual three hours late
    (et(TUE, 0, 40), MON),          # a timeout or re-run after midnight
    (et(TUE, 9, 0), MON),           # before Alpaca's 09:28 cutoff
    (et("2026-09-26", 12, 0), FRI),  # Saturday
    (et("2026-11-27", 13, 50), "2026-11-27"),  # half-day, 13:00 close
    (et("2026-11-27", 13, 30), "2026-11-25"),  # Thanksgiving in between
])
def test_decision_session(now, session):
    assert calendar_util.decision_session(now) == session


@pytest.fixture
def cycle(monkeypatch, tmp_path, alerts):
    """Run cycle_a.main() at a given ET time against a scratch ledger and a
    controls file with the kill switch on: the cycle resolves its session,
    writes a 'killed' record for it and stops before any fetch."""
    ledger, live = tmp_path / "ledger", tmp_path / "live"
    write_json(live / "controls.json", {"kill": True, "pause_entries": False,
                                        "excluded_symbols": [], "gross_cap": None})
    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(config, "LIVE_START", "2026-09-01")
    monkeypatch.setattr(cycle_a, "LIVE", live)
    monkeypatch.setattr(cycle_a, "alert", alerts)
    monkeypatch.setattr(sys, "argv", ["cycle_a.py"])

    def run(now):
        monkeypatch.setattr(calendar_util, "now_et", lambda: now)
        assert cycle_a.main() == 0
        return sorted(p.name for p in (ledger / "cycles").glob("*.json")) \
            if (ledger / "cycles").exists() else []
    return run


def test_a_cycle_after_midnight_still_decides_the_evening_session(cycle):
    assert cycle(et(TUE, 0, 40)) == [f"{MON}-A.json"]


def test_a_cycle_after_the_submit_cutoff_records_nothing(cycle, alerts):
    assert cycle(et(TUE, 9, 30)) == [] and alerts == []


def test_a_cycle_must_leave_itself_time_before_the_cutoff(cycle, alerts):
    # 09:28 cutoff less the 30-minute runtime margin: 08:58 is the last start
    assert cycle(et(TUE, 9, 0)) == [] and alerts == []
    assert cycle(et(TUE, 8, 50)) == [f"{MON}-A.json"]


@pytest.mark.parametrize("now, wait", [
    (et(MON, 20, 10), str(config.FETCH_WAIT_MAX_MIN)),   # the usual late evening
    (et(TUE, 8, 30), "28"),                              # cut short to 08:58
])
def test_the_fetch_stops_at_asof_and_its_wait_fits_before_the_cutoff(
        monkeypatch, tmp_path, alerts, now, wait):
    ledger, live = tmp_path / "ledger", tmp_path / "live"
    write_json(live / "controls.json", {"kill": False, "pause_entries": False,
                                        "excluded_symbols": [], "gross_cap": None})
    seen = {}

    def run_pipeline(script, env):
        seen.update(env)
        return 1   # stop the cycle right after the fetch: fetch_failed

    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(config, "LIVE_START", "2026-09-01")
    monkeypatch.setattr(cycle_a, "LIVE", live)
    monkeypatch.setattr(cycle_a, "alert", alerts)
    monkeypatch.setattr(cycle_a, "run_pipeline", run_pipeline)
    monkeypatch.setattr(calendar_util, "now_et", lambda: now)
    monkeypatch.setattr(sys, "argv", ["cycle_a.py"])
    assert cycle_a.main() == 0
    assert seen["FETCH_EXPECT_LAST"] == MON and seen["FETCH_END"] == TUE
    assert seen["FETCH_WAIT_MAX_MIN"] == wait
    assert (ledger / "cycles" / f"{MON}-A.json").exists()


def test_an_early_slot_resolves_to_the_recorded_previous_session(cycle, alerts):
    assert cycle(et(MON, 17, 0)) == [f"{MON}-A.json"]
    assert cycle(et(TUE, 16, 15)) == [f"{MON}-A.json"]   # nothing new, no second record


# ---- the dead-man after every finished Cycle A --------------------------------------

@pytest.fixture
def after_cycle_a(monkeypatch, tmp_path, alerts):
    ledger = tmp_path / "ledger"
    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(deadman, "alert", alerts)
    monkeypatch.setenv("RUN_URL", "https://github.com/o/r/actions/runs/1")

    def run(now, in_flight=None):
        monkeypatch.setattr(deadman, "now_et", lambda: now)
        monkeypatch.setattr(deadman, "run_in_flight", lambda workflow: in_flight)
        monkeypatch.setattr(sys, "argv", ["deadman.py", "--after-cycle-a"])
        assert deadman.main() == 0
    return run, ledger


def test_a_finished_cycle_without_a_record_files_a_dated_p1(after_cycle_a, alerts):
    run, _ = after_cycle_a
    run(et(TUE, 0, 45))                     # a timed-out run ends after midnight
    assert alerts.levels() == ["P1"]
    assert alerts[0][1] == f"DEAD-MAN: no Cycle A record for {MON}"
    assert "actions/runs/1" in alerts[0][2]


def test_a_finished_cycle_with_its_record_is_quiet(after_cycle_a, alerts):
    run, ledger = after_cycle_a
    write_json(ledger / "cycles" / f"{MON}-A.json", {"status": "data_gate_tripped"})
    run(et(MON, 22, 30))
    assert alerts == []


def test_a_cancelled_queued_run_defers_to_the_one_still_running(after_cycle_a, alerts):
    run, _ = after_cycle_a
    run(et(MON, 21, 0), in_flight="https://github.com/o/r/actions/runs/2")
    assert alerts == []


def test_a_run_older_than_its_job_timeout_is_stuck_not_late(monkeypatch):
    now = dt.datetime(2026, 9, 29, 2, 0, tzinfo=dt.timezone.utc)
    runs = [{"status": "in_progress", "event": "schedule", "html_url": "stuck",
             "created_at": "2026-09-28T19:00:00Z", "run_started_at": "2026-09-28T19:01:00Z"}]
    monkeypatch.setattr(deadman, "_repo", lambda: "o/r")
    monkeypatch.setattr(deadman, "_token", lambda: "t")
    monkeypatch.setattr(deadman, "_api", lambda method, path: {"workflow_runs": runs})
    assert deadman.run_in_flight("live-cycle-a.yml", now) is None      # 7 h > 4.5 h
    # a run queued behind it for an hour is alive; one started 45 min ago too
    runs.append({"status": "queued", "event": "schedule", "html_url": "waiting",
                 "created_at": "2026-09-29T01:00:00Z", "run_started_at": None})
    assert deadman.run_in_flight("live-cycle-a.yml", now) == "waiting"
    runs[1] = {"status": "in_progress", "event": "workflow_dispatch", "html_url": "fresh",
               "created_at": "2026-09-28T19:30:00Z", "run_started_at": "2026-09-29T01:15:00Z"}
    assert deadman.run_in_flight("live-cycle-a.yml", now) == "fresh"
    # but a submit job lives 20 minutes: 45 minutes in progress is stuck
    assert deadman.run_in_flight("live-submit.yml", now) is None
