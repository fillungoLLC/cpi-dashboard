"""
Renderer.

Generates the static HTML dashboard from Jinja2 templates and the KPI bundle.

Pages (dummy/live identical):
  index.html                      overview
  markets/{id}.html               one per market (6)
  channels/{id}.html              one per channel (5)
  detail/{market}--{channel}.html intersections (20 with data)
  exceptions.html                 CPC heatmap + exception cards (v2)
  campaigns.html                  campaign media table (v2)

Chart specs are built in Python as compact dicts and inlined per page as
window.__CHARTS__; render/static/charts.js expands them into Chart.js configs.

v2 surfaces (campaigns, CPC heatmap, exceptions) are derived here from the raw
Google Ads frame + the KPI bundle, using month-over-month deltas within the run.
This keeps the tested transform layer untouched; promote into compute_kpis later
per docs/v2-build-plan.md if desired.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path(__file__).parent.parent / "output"

# Brand palette (matches cpi-brand.css tokens)
BLUE, BLUE2, STEEL, STEEL2, MID, LIGHT = (
    "#00477E", "#1a5a8e", "#8FA8C0", "#5a8ab0", "#C5D8EC", "#E8F0F7",
)
SERIES_COLORS = [BLUE, BLUE2, STEEL, STEEL2, MID, "#9db8d0"]


# =============================================================================
# Formatting
# =============================================================================
def _money(v, dp=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"${v:,.{dp}f}"


def _roi(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v * 100:,.0f}%"


def _pct(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v * 100:.0f}%"


def _int(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.0f}"


def _month_label(ym: str) -> str:
    try:
        return datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%B %Y")
    except Exception:
        return ym


# =============================================================================
# Public entry
# =============================================================================
def render_all(kpis: dict, attributed: pd.DataFrame, config: dict, quality,
               raw: dict | None = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for child in OUTPUT_DIR.iterdir():          # clear contents, keep the dir (may be a mount)
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["money0"] = lambda v: _money(v, 0)
    env.filters["money2"] = lambda v: _money(v, 2)
    env.filters["roi"] = _roi
    env.filters["pct"] = _pct

    meta = kpis["meta"]
    reporting_month = meta["reporting_period"]
    months = kpis["trends"]["months"]
    header = _header(meta, quality)
    trends_collapsed = (config.get("display", {}).get("trends", "collapsed") == "collapsed")
    qbanner = _quality_banner(quality)

    markets = config["markets"]
    channels = config["channels"]
    active_markets = [m for m in markets if m.get("status") != "tbd" and m["id"] in kpis["by_market"]]

    base_ctx = dict(config=config, meta=meta, header=header, quality_banner=qbanner,
                    trends_collapsed=trends_collapsed)

    # ---- overview ----
    _write(env, "overview.html", OUTPUT_DIR / "index.html", {
        **base_ctx, "rel": "",
        "page": {"title": "All Markets", "nav_active": "overview", "show_title": False, "breadcrumb": None},
        "cards": _topline_cards(kpis["overview"], config),
        "secondary": _secondary_cards(kpis["overview"], config),
        "composition": _composition(kpis, None),
        "market_rows": _market_rows(kpis, markets, "", reporting_month),
        "market_total": _total_row("Total", kpis["overview"], ["nps", "cpnp", "roi", "profit"]),
        "channel_rows": _channel_rows(kpis, channels, "", spend=True),
        "channel_total": _total_row("Total", kpis["overview"], ["nps", "cpnp", "roi", "spend"]),
        "charts": _overview_charts(kpis, active_markets, channels),
    })

    # ---- markets ----
    for mk in markets:
        mid = mk["id"]
        tbd = mk.get("status") == "tbd" or mid not in kpis["by_market"]
        metrics = kpis["by_market"].get(mid, {})
        ctx = {
            **base_ctx, "rel": "../",
            "page": {"title": mk["label"], "subtitle": _market_sub(mk), "nav_active": None, "show_title": True,
                     "breadcrumb": [{"label": "Overview", "href": "../index.html"}, {"label": mk["label"]}]},
            "tbd": tbd,
        }
        if not tbd:
            ctx.update({
                "cards": _topline_cards(metrics, config),
                "secondary": _secondary_cards(metrics, config),
                "composition": _composition(kpis, mid),
                "funnel_steps": _funnel(attributed, reporting_month, market=mid),
                "channel_rows": _channel_rows_for_market(kpis, channels, mid, "../"),
                "channel_total": _total_row("Total", metrics, ["nps", "cpnp", "roi", "spend"]),
                "charts": _market_charts(attributed, kpis, mid, channels, reporting_month),
            })
        else:
            ctx["charts"] = {}
        _write(env, "market.html", OUTPUT_DIR / "markets" / f"{mid}.html", ctx)

    # ---- channels ----
    for ch in channels:
        cid = ch["id"]
        metrics = kpis["by_channel"].get(cid, {})
        if not metrics:
            continue
        _write(env, "channel.html", OUTPUT_DIR / "channels" / f"{cid}.html", {
            **base_ctx, "rel": "../",
            "page": {"title": ch["label"], "subtitle": "All markets", "nav_active": None, "show_title": True,
                     "breadcrumb": [{"label": "Overview", "href": "../index.html"}, {"label": ch["label"]}]},
            "cards": _topline_cards(metrics, config),
            "secondary": _secondary_cards(metrics, config),
            "market_rows": _market_rows_for_channel(kpis, markets, cid, "../"),
            "market_total": _total_row("Total", metrics, ["nps", "cpnp", "roi", "spend"]),
            "charts": _channel_charts(attributed, kpis, cid, active_markets, reporting_month),
        })

    # ---- market x channel ----
    for mk in active_markets:
        for ch in channels:
            key = f"{mk['id']}|{ch['id']}"
            metrics = kpis["by_market_channel"].get(key)
            if not metrics:
                continue
            _write(env, "market_channel.html", OUTPUT_DIR / "detail" / f"{mk['id']}--{ch['id']}.html", {
                **base_ctx, "rel": "../",
                "page": {"title": f"{mk['label']} · {ch['label']}", "subtitle": None, "nav_active": None,
                         "show_title": True,
                         "breadcrumb": [{"label": "Overview", "href": "../index.html"},
                                        {"label": mk["label"], "href": f"../markets/{mk['id']}.html"},
                                        {"label": ch["label"]}]},
                "cards": _mc_cards(metrics),
                "funnel_steps": _funnel(attributed, reporting_month, market=mk["id"], channel=ch["id"]),
                "charts": _mc_charts(attributed, mk["id"], ch["id"]),
            })

    # ---- v2: exceptions + campaigns ----
    ads = raw.get("google_ads") if raw else None
    heatmap, campaigns = _campaign_intel(ads, config, months)
    exceptions = _exceptions(kpis, config, months, heatmap)

    _write(env, "exceptions.html", OUTPUT_DIR / "exceptions.html", {
        **base_ctx, "rel": "",
        "page": {"title": "Exceptions", "subtitle": f"What moved · {header['period_label']} vs prior month",
                 "nav_active": "exceptions", "show_title": True, "breadcrumb": None},
        "exceptions": exceptions, "heatmap": heatmap,
        "charts": {},
    })
    _write(env, "campaigns.html", OUTPUT_DIR / "campaigns.html", {
        **base_ctx, "rel": "",
        "page": {"title": "Campaigns", "subtitle": f"Media performance · {header['period_label']}",
                 "nav_active": "campaigns", "show_title": True, "breadcrumb": None},
        "campaigns": campaigns, "charts": {},
    })

    # ---- static + methodology ----
    shutil.copytree(STATIC_DIR, OUTPUT_DIR / "static", dirs_exist_ok=True)
    (OUTPUT_DIR / ".nojekyll").touch()
    _write_quality_json(quality, kpis)

    n = sum(1 for _ in OUTPUT_DIR.rglob("*.html"))
    log.info(f"render: wrote {n} HTML pages to {OUTPUT_DIR}")
    return OUTPUT_DIR


# =============================================================================
# Header / quality
# =============================================================================
def _header(meta, quality):
    now = datetime.now()
    label, cls, detail = _quality_status(quality)
    return {
        "period_label": _month_label(meta["reporting_period"]),
        "refreshed": now.strftime("%a %b %d, %Y").replace(" 0", " "),
        "generated": now.strftime("%a %b %d, %Y · %-I:%M%p CT") if hasattr(now, "strftime") else "",
        "quality_label": label, "quality_class": cls, "quality_detail": detail,
    }


def _quality_status(quality):
    try:
        if quality is not None and quality.has_errors():
            return "Quality: errors", "err", "One or more output checks failed. Figures may be unreliable; see run log."
    except Exception:
        pass
    try:
        if quality is not None and quality.has_warnings():
            return "Quality flag", "warn", "Passed with warnings. Some period-over-period movements exceeded soft bands; see run log."
    except Exception:
        pass
    return "Quality OK", "", "All ingestion, transform, and output checks passed."


def _quality_banner(quality):
    label, cls, detail = _quality_status(quality)
    if cls == "err":
        return {"class": "err", "text": "Quality check failed — figures on this page may be unreliable. See the run log."}
    if cls == "warn":
        return {"class": "warn", "text": "Rendered with a quality warning — some movements exceeded soft bands."}
    return None


# =============================================================================
# Cards
# =============================================================================
def _topline_cards(mtr, config):
    foot = {
        "roi": "(revenue − cost) / cost",
        "online_new_patients": "this period",
        "online_pct_of_self_referrals": "pending intake data",
        "self_referrals_pct_of_total": "pending intake data",
        "cost_per_online_new_patient": "media + agency fees",
    }
    info = {"roi": "ROI = (NPs × revenue − all-in cost) / all-in cost",
            "cost_per_online_new_patient": "All-in cost = media spend + agency fees"}
    cards = []
    for k in config["kpis"]["topline"]:
        kid = k["id"]
        v = mtr.get(kid)
        pending = kid in ("online_pct_of_self_referrals", "self_referrals_pct_of_total")
        if kid == "roi":
            val = _roi(v)
        elif kid == "cost_per_online_new_patient":
            val = _money(v)
        elif kid == "online_new_patients":
            val = _int(v)
        else:
            val = _pct(v)
        cards.append({"label": k["label"], "value": val, "foot": foot.get(kid, ""),
                      "hero": bool(k.get("hero")), "pending": pending, "info": info.get(kid)})
    return cards


def _mc_cards(mtr):
    return [
        {"label": "ROI", "value": _roi(mtr.get("roi")), "foot": "(revenue − cost) / cost", "hero": True,
         "info": "ROI = (NPs × revenue − all-in cost) / all-in cost"},
        {"label": "Online NPs", "value": _int(mtr.get("online_new_patients")), "foot": "this period"},
        {"label": "Cost per Online NP", "value": _money(mtr.get("cost_per_online_new_patient")),
         "foot": "media + agency fees"},
        {"label": "Marketing Profit", "value": _money(mtr.get("marketing_profitability")), "foot": "revenue − cost"},
        {"label": "Total Leads", "value": _int(mtr.get("total_leads")), "foot": "this period"},
        {"label": "Spend", "value": _money(mtr.get("media_spend")), "foot": "media only"},
    ]


def _secondary_cards(mtr, config):
    out = []
    for s in config["kpis"]["secondary"]:
        sid = s["id"]
        if sid == "marketing_profitability":
            out.append({"label": s["label"], "value": _money(mtr.get("marketing_profitability"))})
        elif sid == "total_leads":
            out.append({"label": s["label"], "value": _int(mtr.get("total_leads"))})
        elif sid == "blended_cpl":
            out.append({"label": s["label"], "value": _money(mtr.get("blended_cpl"), 2),
                        "compare": s.get("benchmark_label")})
    return out


# =============================================================================
# Tables
# =============================================================================
def _cells(mtr, keys):
    fmt = {"nps": lambda: _int(mtr.get("online_new_patients")),
           "cpnp": lambda: _money(mtr.get("cost_per_online_new_patient")),
           "roi": lambda: _roi(mtr.get("roi")),
           "profit": lambda: _money(mtr.get("marketing_profitability")),
           "spend": lambda: _money(mtr.get("media_spend")),
           "leads": lambda: _int(mtr.get("total_leads"))}
    return [fmt[k]() for k in keys]


def _total_row(name, mtr, keys):
    return {"name": name, "cells": _cells(mtr, keys)}


def _market_rows(kpis, markets, rel, reporting_month):
    rows = []
    for mk in markets:
        mid = mk["id"]
        tag = _brand_tag(mk)
        if mk.get("status") == "tbd" or mid not in kpis["by_market"]:
            rows.append({"name": mk["label"], "tag": tag or "Nuro", "tbd": True,
                         "cells": ["TBD", "TBD", "TBD", "TBD"], "href": f"{rel}markets/{mid}.html"})
            continue
        rows.append({"name": mk["label"], "tag": tag,
                     "cells": _cells(kpis["by_market"][mid], ["nps", "cpnp", "roi", "profit"]),
                     "href": f"{rel}markets/{mid}.html"})
    return rows


def _channel_rows(kpis, channels, rel, spend=True):
    rows = []
    for ch in channels:
        cid = ch["id"]
        if cid not in kpis["by_channel"]:
            continue
        rows.append({"name": ch["label"],
                     "cells": _cells(kpis["by_channel"][cid], ["nps", "cpnp", "roi", "spend"]),
                     "href": f"{rel}channels/{cid}.html"})
    return rows


def _channel_rows_for_market(kpis, channels, mid, rel):
    rows = []
    for ch in channels:
        key = f"{mid}|{ch['id']}"
        mtr = kpis["by_market_channel"].get(key)
        if not mtr:
            continue
        rows.append({"name": ch["label"], "cells": _cells(mtr, ["nps", "cpnp", "roi", "spend"]),
                     "href": f"{rel}detail/{mid}--{ch['id']}.html"})
    return rows


def _market_rows_for_channel(kpis, markets, cid, rel):
    rows = []
    for mk in markets:
        key = f"{mk['id']}|{cid}"
        mtr = kpis["by_market_channel"].get(key)
        if not mtr:
            continue
        rows.append({"name": mk["label"], "tag": _brand_tag(mk),
                     "cells": _cells(mtr, ["nps", "cpnp", "roi", "spend"]),
                     "href": f"{rel}detail/{mk['id']}--{cid}.html"})
    return rows


def _brand_tag(mk):
    b = mk.get("brand")
    if not b:
        return None
    return b.split()[0]  # "Wellspring Pain Solutions" -> "Wellspring"


def _market_sub(mk):
    bits = []
    if mk.get("brand"):
        bits.append(mk["brand"])
    if mk.get("notes"):
        bits.append(mk["notes"])
    return " · ".join(bits) if bits else None


# =============================================================================
# Funnel
# =============================================================================
def _funnel(attributed, month, market=None, channel=None):
    df = attributed[attributed["month"] == month]
    if market:
        df = df[df["market"] == market]
    if channel:
        df = df[df["channel"] == channel]
    spend = float(df["media_spend"].sum())
    clicks = float(df["clicks"].sum())
    sessions = float(df["sessions"].sum())
    leads = float(df["leads"].sum())
    nps = float(df["online_nps_attributed"].sum())
    cpc = spend / clicks if clicks else 0
    c2s = sessions / clicks if clicks else 0
    lrate = leads / sessions if sessions else 0
    l2np = nps / leads if leads else 0
    return [
        {"label": "Spend", "value": _money(spend), "note": "media only"},
        {"label": "Clicks", "value": _int(clicks), "note": f"{_money(cpc, 2)} CPC" if clicks else "—"},
        {"label": "Sessions", "value": _int(sessions), "note": f"{c2s*100:.0f}% click→session" if clicks else "organic + paid"},
        {"label": "Leads", "value": _int(leads), "note": f"{lrate*100:.1f}% lead rate" if sessions else "—"},
        {"label": "New Patients", "value": _int(round(nps)), "note": f"{l2np*100:.0f}% lead→NP" if leads else "—"},
    ]


# =============================================================================
# Charts (compact specs; charts.js expands to Chart.js configs)
# =============================================================================
def _ds(label, data, color, **kw):
    d = {"label": label, "data": data, "borderColor": color, "backgroundColor": color}
    d.update(kw)
    return d


def _line(labels, datasets, **opts):
    for d in datasets:
        d.setdefault("tension", 0.3)
        d.setdefault("borderWidth", 2)
        d.setdefault("pointRadius", 2)
        d.setdefault("fill", False)
    return {"type": "line", "data": {"labels": labels, "datasets": datasets}, "opts": opts}


def _bar(labels, datasets, **opts):
    return {"type": "bar", "data": {"labels": labels, "datasets": datasets}, "opts": opts}


def _market_color(i):
    return SERIES_COLORS[i % len(SERIES_COLORS)]


def _overview_charts(kpis, active_markets, channels):
    t = kpis["trends"]
    months = t["months"]
    mlabels = [_month_label(m).split()[0][:3] for m in months]

    market_ds = []
    for i, mk in enumerate(active_markets):
        series = t["nps_by_market_month"].get(mk["id"], {})
        market_ds.append(_ds(mk["label"], [series.get(m) for m in months], _market_color(i)))
    market_trend = _line(mlabels, market_ds, legend=True)

    roi_labels = [mk["label"] for mk in active_markets]
    roi_data = [round((kpis["by_market"][mk["id"]].get("roi") or 0) * 100) for mk in active_markets]
    roi_by_market = _bar(roi_labels, [_ds("ROI", roi_data, BLUE, borderRadius=2)],
                         indexAxis="y", legend=False, y_fmt="pct", tt_pct=True)

    ch_ds = []
    for i, ch in enumerate(channels):
        series = t["nps_by_channel_month"].get(ch["id"], {})
        ch_ds.append({"label": ch["label"], "data": [series.get(m) for m in months],
                      "backgroundColor": _market_color(i), "stack": "s"})
    np_by_channel = _bar(mlabels, ch_ds, stacked=True, legend=True)

    return {"marketTrend": market_trend, "roiByMarket": roi_by_market, "npByChannel": np_by_channel}


def _market_charts(attributed, kpis, mid, channels, month):
    df = attributed[attributed["market"] == mid]
    months = kpis["trends"]["months"]
    mlabels = [_month_label(m).split()[0][:3] for m in months]

    mix_ds = []
    for i, ch in enumerate(channels):
        cd = df[df["channel"] == ch["id"]].groupby("month")["online_nps_attributed"].sum()
        mix_ds.append({"label": ch["label"], "data": [round(float(cd.get(m, 0)), 1) for m in months],
                       "backgroundColor": _market_color(i), "stack": "s"})
    channel_mix = _bar(mlabels, mix_ds, stacked=True, legend=True)

    weeks = sorted(df["period"].unique())
    wlabels = [w.replace("2026-", "") for w in weeks]
    nps_w = df.groupby("period")["online_nps_attributed"].sum()
    leads_w = df.groupby("period")["leads"].sum()
    spend_w = df.groupby("period")["media_spend"].sum()
    weekly = _line(wlabels, [
        _ds("NPs", [round(float(nps_w.get(w, 0)), 1) for w in weeks], BLUE, yAxisID="y1", borderWidth=2.5),
        _ds("Leads", [int(leads_w.get(w, 0)) for w in weeks], STEEL, yAxisID="y1"),
        _ds("Spend ($)", [round(float(spend_w.get(w, 0))) for w in weeks], MID, yAxisID="y2", borderDash=[4, 4]),
    ], dual=True, legend=True, y_fmt="", y2_fmt="money")

    return {"channelMix": channel_mix, "weeklyTrend": weekly}


def _channel_charts(attributed, kpis, cid, active_markets, month):
    cpnp_labels = [mk["label"] for mk in active_markets]
    cpnp_data = []
    for mk in active_markets:
        mtr = kpis["by_market_channel"].get(f"{mk['id']}|{cid}", {})
        cpnp_data.append(round(mtr.get("cost_per_online_new_patient") or 0, 0))
    cpnp = _bar(cpnp_labels, [_ds("CPNP", cpnp_data, BLUE, borderRadius=2)],
               indexAxis="y", legend=False, y_fmt="money")

    df = attributed[attributed["channel"] == cid]
    weeks = sorted(df["period"].unique())
    wlabels = [w.replace("2026-", "") for w in weeks]
    ds = []
    for i, mk in enumerate(active_markets):
        md = df[df["market"] == mk["id"]].groupby("period")["online_nps_attributed"].sum()
        ds.append(_ds(mk["label"], [round(float(md.get(w, 0)), 1) for w in weeks], _market_color(i)))
    trend = _line(wlabels, ds, legend=True)

    return {"cpnpByMarket": cpnp, "weeklyTrendByMarket": trend}


def _mc_charts(attributed, mid, cid):
    df = attributed[(attributed["market"] == mid) & (attributed["channel"] == cid)]
    weeks = sorted(df["period"].unique())
    wlabels = [w.replace("2026-", "") for w in weeks]
    leads_w = df.groupby("period")["leads"].sum()
    spend_w = df.groupby("period")["media_spend"].sum()
    perf = _line(wlabels, [
        _ds("Leads", [int(leads_w.get(w, 0)) for w in weeks], BLUE, yAxisID="y1", borderWidth=2.5),
        _ds("Spend ($)", [round(float(spend_w.get(w, 0))) for w in weeks], MID, yAxisID="y2", borderDash=[4, 4]),
    ], dual=True, legend=True, y_fmt="", y2_fmt="money")
    return {"weeklyPerformance": perf}


# =============================================================================
# v2: campaign intel (heatmap + campaign table) and exceptions
# =============================================================================
def _market_of(name: str, config: dict):
    for mk in config["markets"]:          # config order respects Ohio-before-Colorado
        for tok in mk.get("match", []):
            if tok.lower() in name.lower():
                return mk["id"], mk["label"]
    return None, None


def _is_nonbrand(name: str) -> bool:
    n = name.lower()
    return ("non-brand" in n) or ("non brand" in n) or ("nonbrand" in n)


def _campaign_intel(ads, config, months):
    """Returns (heatmap dict, campaign rows). Heatmap: market x {Brand, Non-Brand}
    CPC for the reporting month with MoM delta vs prior month."""
    if ads is None or getattr(ads, "empty", True):
        return {"rows": [], "empty": True}, []

    df = ads.copy()
    name_col = "campaign.name" if "campaign.name" in df.columns else "campaign_name"
    df["month"] = df["date"].astype(str).str.slice(0, 7)
    df["mkt_id"], df["mkt_label"] = zip(*df[name_col].map(lambda n: _market_of(n, config)))
    df["ctype"] = df[name_col].map(lambda n: "Non-Brand" if _is_nonbrand(n) else "Brand")

    cur = months[-1] if months else None
    prev = months[-2] if len(months) >= 2 else None
    band = config.get("exceptions", {}).get("cpc_wow_band_pct", 15)

    def cpc(sub):
        clicks = sub["clicks"].sum()
        return (sub["cost"].sum() / clicks) if clicks else None

    # ---- heatmap ----
    rows = []
    for mk in config["markets"]:
        mid = mk["id"]
        sub_m = df[df["mkt_id"] == mid]
        if sub_m.empty:
            continue
        cells = []
        for ctype in ("Brand", "Non-Brand"):
            s = sub_m[sub_m["ctype"] == ctype]
            cur_cpc = cpc(s[s["month"] == cur]) if cur else None
            prev_cpc = cpc(s[s["month"] == prev]) if prev else None
            cells.append(_heat_cell(cur_cpc, prev_cpc, band))
        rows.append({"market": mk["label"], "cells": cells})
    heatmap = {"rows": rows, "empty": not rows, "band": band,
               "cur": _month_label(cur) if cur else "", "prev": _month_label(prev) if prev else ""}

    # ---- campaign table (reporting month) ----
    campaigns = []
    cur_df = df[df["month"] == cur] if cur else df
    for name, g in cur_df.groupby(name_col):
        clicks = float(g["clicks"].sum())
        spend = float(g["cost"].sum())
        leads = float(g["conversions"].sum())
        campaigns.append({
            "name": name, "market": g["mkt_label"].iloc[0] or "—",
            "type": "Non-Brand" if _is_nonbrand(name) else "Brand",
            "spend": _money(spend), "clicks": _int(clicks),
            "cpc": _money(spend / clicks, 2) if clicks else "—",
            "leads": _int(leads),
            "_spend": spend,
        })
    campaigns.sort(key=lambda c: c["_spend"], reverse=True)
    for c in campaigns:
        c.pop("_spend", None)
    return heatmap, campaigns


def _heat_cell(cur_cpc, prev_cpc, band):
    if cur_cpc is None:
        return {"cpc": "—", "wow": "", "cls": "heat-na"}
    if prev_cpc is None or prev_cpc == 0:
        return {"cpc": _money(cur_cpc, 2), "wow": "new", "cls": "heat-flat"}
    delta = (cur_cpc - prev_cpc) / prev_cpc * 100
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
    if delta <= -band:
        cls = "heat-down2"
    elif delta < 0:
        cls = "heat-down1"
    elif delta >= band:
        cls = "heat-up2"
    elif delta > 0:
        cls = "heat-up1"
    else:
        cls = "heat-flat"
    return {"cpc": _money(cur_cpc, 2), "wow": f"{arrow} {abs(delta):.0f}%", "cls": cls}


def _exceptions(kpis, config, months, heatmap):
    cfg = config.get("exceptions", {})
    ceiling = cfg.get("cpnp_ceiling", 600)
    np_drop = cfg.get("np_drop_pct", 20)
    band = cfg.get("cpc_wow_band_pct", 15)
    groups = []

    # CPNP over ceiling (by market)
    cpnp_hits = []
    for mid, mtr in kpis["by_market"].items():
        v = mtr.get("cost_per_online_new_patient")
        if v is not None and v > ceiling:
            label = next((m["label"] for m in config["markets"] if m["id"] == mid), mid)
            cpnp_hits.append({"what": label, "detail": f"Cost per online new patient above ${ceiling:,.0f} ceiling",
                              "metric": _money(v), "move": "over ceiling", "move_cls": "bad", "sev": "sev-alert"})
    groups.append({"title": f"CPNP over ${ceiling:,.0f} ceiling", "cards": cpnp_hits})

    # NP volume drops (market, MoM)
    drops = []
    cur, prev = (months[-1], months[-2]) if len(months) >= 2 else (None, None)
    if cur and prev:
        for mid, series in kpis["trends"]["nps_by_market_month"].items():
            c, p = series.get(cur), series.get(prev)
            if c is not None and p:
                d = (c - p) / p * 100
                if d <= -np_drop:
                    label = next((m["label"] for m in config["markets"] if m["id"] == mid), mid)
                    drops.append({"what": label, "detail": f"New patients down vs prior month ({int(p)} → {int(c)})",
                                  "metric": f"{d:.0f}%", "move": "MoM", "move_cls": "bad", "sev": "sev-alert"})
    groups.append({"title": f"New-patient volume down > {np_drop}% (MoM)", "cards": drops})

    # CPC moves beyond band (from heatmap)
    cpc_moves = []
    for r in heatmap.get("rows", []):
        for ctype, cell in zip(("Brand", "Non-Brand"), r["cells"]):
            if cell["cls"] in ("heat-up2", "heat-down2"):
                bad = cell["cls"] == "heat-up2"
                cpc_moves.append({"what": f"{r['market']} · {ctype}",
                                  "detail": f"CPC moved beyond ±{band}% vs prior month",
                                  "metric": cell["cpc"], "move": cell["wow"],
                                  "move_cls": "bad" if bad else "good",
                                  "sev": "sev-alert" if bad else "sev-watch"})
    groups.append({"title": f"CPC moved beyond ±{band}% (MoM)", "cards": cpc_moves})

    total = sum(len(g["cards"]) for g in groups)
    return {"groups": groups, "total": total}


def _write_quality_json(quality, kpis):
    meth = OUTPUT_DIR / "methodology"
    meth.mkdir(parents=True, exist_ok=True)
    try:
        report = quality.to_dict() if hasattr(quality, "to_dict") else {}
    except Exception:
        report = {}
    payload = {"reporting_period": kpis["meta"]["reporting_period"], "quality": report}
    (meth / "quality.json").write_text(json.dumps(payload, default=str, indent=2))


def _composition(kpis, market_id):
    # self_referral_composition is {} today (sheet lacks breakdown columns) -> pending
    comp = kpis.get("self_referral_composition") or {}
    if market_id:
        comp = comp.get(market_id, {}) if isinstance(comp, dict) else {}
    if not comp:
        return None
    return comp


def _write(env, template, out_path: Path, ctx: dict):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = env.get_template(template).render(**ctx)
    out_path.write_text(html, encoding="utf-8")
