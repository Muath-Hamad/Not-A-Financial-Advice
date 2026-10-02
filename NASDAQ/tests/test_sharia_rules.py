"""The offline layers of the AAOIFI screen, and the committed universe itself."""

from __future__ import annotations

import json
from pathlib import Path

from sharia_screen import (apply_rule_layers, business_screen, instrument_screen,
                           load_overrides, override_screen, review_flags)

PKG = Path(__file__).resolve().parents[1]


def test_preferred_and_perpetual_lines_fail_the_instrument_screen():
    for name in ("Bruker Corporation 6.375% Mandatory Convertible Preferred Stock Series A",
                 "Super Micro Computer Inc. Depositary Shares representing a 1/20th Interest "
                 "in a Share of 7% Series A Mandatory Convertible Preferred Stock",
                 "Strategy Inc 10.00% Series A Perpetual Strife Preferred Stock"):
        assert instrument_screen({"name": name}), name


def test_non_share_instruments_fail():
    assert instrument_screen({"name": "Acme Acquisition Corp Warrants"})
    assert instrument_screen({"name": "Acme Acquisition Corp Units"})
    assert instrument_screen({"name": "Acme Corp Subscription Rights"})
    assert instrument_screen({"name": "Acme Corp 5.50% Notes due 2031"})


def test_common_shares_and_ads_pass():
    for name in ("Apple Inc. Common Stock",
                 "Arm Holdings plc American Depositary Shares",
                 "Alphabet Inc. Class C Capital Stock",
                 "United Therapeutics Corporation Common Stock",
                 "Rightmove plc Ordinary Shares"):
        assert instrument_screen({"name": name}) == [], name


def test_curated_exclusion_and_review_flags():
    overrides = {"exclude": {"SFD": "pork"}, "review": {"NFLX": "entertainment"}}
    assert override_screen({"code": "SFD"}, overrides) == ["pork"]
    assert override_screen({"code": "NFLX"}, overrides) == []
    assert review_flags({"code": "NFLX", "sector": "", "industry": ""}, overrides) == \
        ["entertainment"]
    # labels: chip makers file under "Broadcasting ... Equipment" and are not flagged
    assert review_flags({"code": "X", "sector": "Technology",
                         "industry": "Radio And Television Broadcasting And Communications "
                                     "Equipment"}, {}) == []
    assert review_flags({"code": "Y", "sector": "Consumer Discretionary",
                         "industry": "Hotels/Resorts"}, {})


def test_rule_layers_decide_pass():
    ok = {"code": "AAA", "name": "Aaa Inc. Common Stock", "business_pass": True,
          "ratios_pass": True}
    assert apply_rule_layers(dict(ok), {})["pass"] is True
    assert apply_rule_layers({**ok, "name": "Aaa Inc. Preferred Stock"}, {})["pass"] is False
    assert apply_rule_layers(dict(ok), {"exclude": {"AAA": "why"}})["pass"] is False
    assert apply_rule_layers({**ok, "ratios_pass": False}, {})["pass"] is False
    # a review flag informs the owner's policy; it does not fail the screen
    assert apply_rule_layers(dict(ok), {"review": {"AAA": "why"}})["pass"] is True


def test_business_screen_keeps_gaming_and_defense():
    assert business_screen({"sector": "Technology", "industry": "Video Games", "name": "x"}) == []
    assert business_screen({"sector": "Industrials", "industry": "Aerospace & Defense",
                            "name": "x"}) == []
    assert business_screen({"sector": "Finance", "industry": "Major Banks", "name": "x"})


def test_committed_universe_passes_every_offline_layer():
    screen = json.loads((PKG / "data" / "universe_screened.json").read_text())
    overrides = load_overrides()
    assert screen["passed"] == len(screen["universe"])
    for rec in screen["universe"]:
        assert not instrument_screen(rec), rec["code"]
        assert not override_screen(rec, overrides), rec["code"]
        assert rec.get("business_pass") and rec.get("ratios_pass"), rec["code"]
    codes = {r["code"] for r in screen["universe"]}
    assert not codes & {"BRKRP", "SMCIP", "MCHPP", "STRF", "STRC", "STRK", "SATA", "SFD"}
