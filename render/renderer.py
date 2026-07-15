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

    # ---- v2: exceptions + campaigns (formatted from compute_kpis blocks) ----
    heatmap = _heatmap_view(kpis, config)
    exceptions = _exceptions_view(kpis, config)
    campaigns = _campaigns_view(kpis, config)
    vs_label = f"{heatmap['cur']} vs {heatmap['prev']}" if heatmap.get("prev") else heatmap.get("cur", "")

    _write(env, "exceptions.html", OUTPUT_DIR / "exceptions.html", {
        **base_ctx, "rel": "",
        "page": {"title": "Exceptions", "subtitle": f"What moved · {vs_label}",
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
    lrate = leads / sessions if sessions else 0
    l2np = nps / leads if leads else 0
    return [
        {"label": "Spend", "value": _money(spend), "note": "media only"},
        {"label": "Clicks", "value": _int(clicks), "note": f"{_money(cpc, 2)} CPC" if clicks else "—"},
        {"label": "Sessions", "value": _int(sessions), "note": "paid + organic"},
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
# v2 view builders — format compute_kpis numeric blocks into template shapes
# =============================================================================
def _mk_label(config, mid):
    for m in config["markets"]:
        if m["id"] == mid:
            return m["label"]
    return mid or "—"


def _heat_cell(c, band):
    if not c or c.get("cpc") is None:
        return {"cpc": "—", "wow": "", "cls": "heat-na"}
    cpc = c["cpc"]
    pct = c.get("pct")
    if pct is None:
        return {"cpc": _money(cpc, 2), "wow": "new", "cls": "heat-flat"}
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    if pct <= -band:
        cls = "heat-down2"
    elif pct < 0:
        cls = "heat-down1"
    elif pct >= band:
        cls = "heat-up2"
    elif pct > 0:
        cls = "heat-up1"
    else:
        cls = "heat-flat"
    return {"cpc": _money(cpc, 2), "wow": f"{arrow} {abs(pct):.0f}%", "cls": cls}


def _heatmap_view(kpis, config):
    hm = kpis.get("by_market_campaign_type") or {}
    band = config.get("exceptions", {}).get("cpc_wow_band_pct", 15)
    rows = []
    for m in config["markets"]:
        cell = hm.get(m["id"])
        if not cell:
            continue
        rows.append({"market": m["label"],
                     "cells": [_heat_cell(cell.get("branded"), band),
                               _heat_cell(cell.get("nonbranded"), band)]})
    meta = kpis.get("meta", {})
    return {"rows": rows, "empty": not rows, "band": band,
            "cur": _month_label(meta.get("reporting_period", "")),
            "prev": _month_label(meta["prior_period"]) if meta.get("prior_period") else ""}


def _campaigns_view(kpis, config):
    out = []
    for c in kpis.get("by_campaign", []):
        branded = c.get("branded")
        ctype = "Non-Brand" if branded is False else ("Brand" if branded else "—")
        out.append({
            "name": c["name"],
            "market": _mk_label(config, c["market"]) if c.get("market") else "—",
            "type": ctype,
            "spend": _money(c["spend"]),
            "clicks": _int(c["clicks"]),
            "cpc": _money(c["cpc"], 2) if c.get("cpc") is not None else "—",
            "leads": _int(c["leads"]),
        })
    return out


def _exceptions_view(kpis, config):
    exc = kpis.get("exceptions", {})
    ec = config.get("exceptions", {})
    ceiling = ec.get("cpnp_ceiling", 600)
    band = ec.get("cpc_wow_band_pct", 15)
    drop = ec.get("np_drop_pct", 20)
    groups = []

    cards = [{"what": _mk_label(config, e["market"]),
              "detail": f"Cost per online new patient above ${ceiling:,.0f} ceiling",
              "metric": _money(e["value"]), "move": "over ceiling",
              "move_cls": "bad", "sev": "sev-alert"}
             for e in exc.get("cpnp_over_ceiling", [])]
    groups.append({"title": f"CPNP over ${ceiling:,.0f} ceiling", "cards": cards})

    cards = [{"what": _mk_label(config, e["market"]),
              "detail": f"New patients down vs prior month ({int(e['prev'])} → {int(e['cur'])})",
              "metric": f"{e['pct']:.0f}%", "move": "MoM", "move_cls": "bad", "sev": "sev-alert"}
             for e in exc.get("np_drops", [])]
    groups.append({"title": f"New-patient volume down > {drop}% (MoM)", "cards": cards})

    cards = []
    for e in exc.get("cpc_moves", []):
        up = e["pct"] > 0
        cards.append({"what": f"{_mk_label(config, e['market'])} · {'Non-Brand' if e['type'] == 'nonbranded' else 'Brand'}",
                      "detail": f"CPC moved beyond ±{band}% vs prior month",
                      "metric": _money(e["cpc"], 2),
                      "move": f"{'▲' if up else '▼'} {abs(e['pct']):.0f}%",
                      "move_cls": "bad" if up else "good",
                      "sev": "sev-alert" if up else "sev-watch"})
    groups.append({"title": f"CPC moved beyond ±{band}% (MoM)", "cards": cards})

    return {"groups": groups, "total": exc.get("total", 0)}


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
