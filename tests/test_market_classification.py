"""
Regression tests for market classification.

All of these are real values from the 2026-07 production snapshot that the
original bare-state-code tokens got wrong. "CO" matched "Max Conv", "IN"
matched Cincinnati and Huntington, "KY" matched Kyle (a Texas city). Between
them they misrouted $17,256 of media and 137 of Indiana's 182 GA4 conversions.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from transform import normalize_markets

MARKETS = yaml.safe_load((Path(__file__).parent.parent / "config" / "dashboard.yml").read_text())["markets"]


def c(value):
    return normalize_markets._classify(value, MARKETS)


# --- Google Ads campaign names -----------------------------------------------
@pytest.mark.parametrize("campaign,expected", [
    ("TX - Bastrop Pmax | 01.03 | Max Conv",        "texas"),     # "Max Conv" != Colorado
    ("CO - Denver (GW Village) Pmax | Max Conv",    "colorado"),
    ("KY - Elizabethtown Pmax | 01.02 | Max Conv",  "kentucky"),
    ("OH - Pickerington Pmax | tCPA 30",            "ohio"),
    ("MISS - Munster & Chesterton | Max Conv",      "indiana"),   # NW Indiana towns
    ("Wellspring - Columbus Pmax | 22.01 | tCPA 50","indiana"),   # Columbus, INDIANA
    ("Wellspring - Bloomington | tCPA 32 | AI max", "indiana"),
    ("OH - Columbus (East) Pickerington | tCPA 25", "ohio"),      # CPI's Columbus is Ohio
    ("CO - Colorado Springs | tCPA 40 | AI max",    "colorado"),
    ("TX - Austin South | tCPA 75 (restarted)",     "texas"),
])
def test_campaign_names(campaign, expected):
    assert c(campaign) == expected


# --- GA4 city names -----------------------------------------------------------
@pytest.mark.parametrize("city,expected", [
    ("San Marcos",       "texas"),          # was colorado, via "co"
    ("Kyle",             "texas"),          # was KENTUCKY, via "KY" (confirmed TX)
    ("Austin",           "texas"),
    ("Denver",           "colorado"),
    ("Colorado Springs", "colorado"),
    ("Louisville",       "kentucky"),
    ("Columbus",         "ohio"),
    ("indiana",          "indiana"),        # ga4_wellspring market_override value
    ("Bloomington",      "indiana"),
])
def test_ga4_cities(city, expected):
    assert c(city) == expected


@pytest.mark.parametrize("city", [
    "Cincinnati", "Huntington", "Princeton", "Elgin", "Mount Washington",
    "Fountain", "Aitkin", "Al Ain", "Alcoa", "Alvin", "Amelia Court House",
    "Altamonte Springs",
])
def test_out_of_market_cities_stay_unclassified(city):
    """Every one of these was being filed into a real market by a two-letter
    substring. Unclassified rows are dropped in aggregate, which is correct."""
    assert c(city) == "unclassified"


def test_no_market_uses_a_bare_two_letter_code():
    """Guardrail: a bare state code will always collide with ordinary words."""
    for m in MARKETS:
        for token in m["match"]:
            assert len(token.strip()) > 2, f"{m['id']} has unsafe token {token!r}"
