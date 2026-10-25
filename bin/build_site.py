#!/usr/bin/env python3
"""Build the human-friendly Guardian site.

1. Converts daily briefing markdown into styled HTML (browsers render
   raw .md as plain text; this wraps it in a proper page).
2. Generates a daily statistics infographic (PNG) from the latest
   snapshot using matplotlib.
3. Updates an index page linking everything, with social-media
   (OpenGraph/Twitter) meta tags so shared links look good.

Run by publish.sh before git commit. Stdlib + markdown + matplotlib only.
"""
import base64
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/aiops/dev/guardian")
PUB = Path("/home/aiops/dev/guardian-publish")
SITE = "https://kheper1970.github.io/guardian/"

CSS = """
:root { --accent:#c0392b; --bg:#fafafa; --card:#ffffff; --ink:#222; --muted:#666; }
* { box-sizing:border-box; }
body { font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  margin:0; background:var(--bg); color:var(--ink); line-height:1.55; }
.wrap { max-width:900px; margin:0 auto; padding:1.5rem; }
header.site { background:#1c2833; color:#fff; padding:1.5rem 0 1.2rem; }
header.site .wrap { padding-top:0; padding-bottom:0; }
header.site h1 { margin:0 0 .2rem; font-size:1.6rem; letter-spacing:.5px; }
header.site p { margin:.2rem 0; color:#aab7c4; font-size:.95rem; }
header.site a { color:#ffd166; text-decoration:none; }
.alert-banner { background:#c0392b; color:#fff; padding:.55rem 1.5rem;
  font-weight:600; letter-spacing:.4px; }
.alert-banner a { color:#fff; }
main { display:block; }
.card { background:var(--card); border:1px solid #e3e3e3; border-radius:10px;
  padding:1.2rem 1.4rem; margin:1.2rem 0; box-shadow:0 1px 3px rgba(0,0,0,.05); }
h1,h2,h3 { line-height:1.25; }
h2 { border-bottom:2px solid var(--accent); padding-bottom:.3rem; margin-top:1.6rem; }
ul { padding-left:1.2rem; }
li { margin:.25rem 0; }
a { color:#1a5276; }
code,pre { background:#f0f2f4; border-radius:4px; }
code { padding:.1rem .3rem; }
pre { padding:.8rem; overflow-x:auto; }
table { border-collapse:collapse; width:100%; margin:.8rem 0; }
th,td { border:1px solid #ddd; padding:.45rem .6rem; text-align:left; }
th { background:#f4f6f7; }
img { max-width:100%; }
footer { color:var(--muted); font-size:.85rem; margin:2rem 0 3rem; }
.badge { display:inline-block; background:#f4d03f; color:#5b4a00; border-radius:12px;
  padding:.1rem .6rem; font-size:.8rem; font-weight:700; margin-left:.4rem; }
.statgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.8rem; }
.stat { background:#fdfefe; border:1px solid #e3e3e3; border-radius:8px; padding:.8rem; text-align:center; }
.stat .n { font-size:1.7rem; font-weight:800; color:#1c2833; }
.stat .l { font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
.hero { background:linear-gradient(135deg,#1c2833,#2c3e50); color:#fff;
  border-radius:10px; padding:1.4rem; margin:1.2rem 0; }
.hero h2 { border:none; margin:.1rem 0 .4rem; color:#fff; }
.hero p { margin:.2rem 0; color:#d5dbdb; }
nav.crumbs { font-size:.9rem; color:var(--muted); margin:.6rem 0; }
nav.crumbs a { color:#1a5276; text-decoration:none; }
@media (max-width:600px){ header.site h1{font-size:1.25rem} }
"""

def page(title, body_html, desc, alert=False, extra_head=""):
    banner = ('<div class="alert-banner">ACTIVE ALERT IN EFFECT '
              '&mdash; see briefing for details</div>') if alert else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE}index.html">
<meta property="og:image" content="{SITE}img/infographic_latest.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{SITE}img/infographic_latest.png">
<link rel="alternate" type="application/atom+xml" title="Guardian briefing feed" href="{SITE}feed.xml">
<style>{CSS}</style>
{extra_head}
</head>
<body>
{banner}
<header class="site"><div class="wrap">
<h1>&#9673; GUARDIAN &mdash; Global Risk Monitor</h1>
<p>Automated multi-source digest of public hazard feeds. <b>Not an official warning channel</b> &mdash;
for emergencies use <a href="https://www.bom.gov.au">BOM</a> (AU),
<a href="https://ptwc.weather.gov">PTWC</a>, <a href="https://earthquake.usgs.gov">USGS</a>,
or your national emergency agency.</p>
</div></header>
<main><div class="wrap">
{body_html}
</div></main>
<footer><div class="wrap">
Generated automatically by the Guardian pipeline (open source in this repo).
Every figure traces to a public feed; sources cited inline.
Raw data: <a href="latest_snapshot.json">latest snapshot (JSON)</a> &middot;
<a href="{SITE}feed.xml">Atom feed</a>.
</div></footer>
</body>
</html>"""

# ---------------------------------------------------------------- infographic

INK = "#1c2833"
RED = "#c0392b"
AMBER = "#f4d03f"
TEAL = "#16a085"
BLUE = "#2980b9"
MUTED = "#7f8c8d"

def _daily_history(days=7):
    """One snapshot per day (the latest) -> quake count, max mag, kp max."""
    hist = {}
    for f in sorted(glob.glob(str(BASE / "data" / "snapshot_*.json"))):
        try:
            d = json.load(open(f))
            day = d.get("collected_utc", "")[:10]
            if not day:
                continue
            eqs = [q for q in d.get("earthquakes", []) if "error" not in q
                   and isinstance(q.get("mag"), (int, float))]
            rec = {
                "count": len(eqs),
                "maxmag": max((q["mag"] for q in eqs), default=0),
                "kp": (d.get("space_weather") or {}).get("kp_max_24h"),
            }
            old = hist.get(day)
            if old is None or (rec["kp"] or 0) >= (old["kp"] or 0):
                hist[day] = rec
        except Exception:
            continue
    days_list = sorted(hist)[-days:]
    return days_list, [hist[d] for d in days_list]


def make_infographic(snapshot, bom, out_png):
    """Daily statistics infographic, 1600x900 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    datestr = snapshot.get("collected_utc", "")[:10]
    gen_time = snapshot.get("collected_utc", "")[11:16]

    eqs = [q for q in snapshot.get("earthquakes", [])
           if "error" not in q and isinstance(q.get("mag"), (int, float))]
    maxmag = max((q["mag"] for q in eqs), default=0)
    sw = snapshot.get("space_weather") or {}
    kp_max = sw.get("kp_max_24h")
    neo = snapshot.get("neo") or {}
    gdacs = snapshot.get("gdacs") or []
    volcano = snapshot.get("volcano") or {}
    elevated = volcano.get("elevated") or []
    tsunami = snapshot.get("tsunami") or {}
    eonet = snapshot.get("eonet") or {}
    tracked = eonet.get("tracked") or []
    nhc = snapshot.get("nhc_storms") or []

    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor="white")
    fig.patch.set_facecolor("white")

    # ---- header band
    fig.text(0.04, 0.955, "GUARDIAN", fontsize=30, fontweight="bold",
             color=INK, ha="left", va="center")
    fig.text(0.175, 0.955, "GLOBAL RISK SNAPSHOT", fontsize=19,
             color=RED, fontweight="bold", ha="left", va="center")
    fig.text(0.96, 0.955, f"{datestr}  ·  {gen_time} UTC",
             fontsize=13, color=MUTED, ha="right", va="center")
    fig.text(0.04, 0.905,
             "Automated digest of public hazard feeds - USGS, NOAA, NASA, GDACS, ReliefWeb, WHO, BOM, NHC",
             fontsize=11.5, color=MUTED, ha="left", va="center")

    # ---- stats band
    stats = [
        (f"{len(eqs)}", "QUAKES M4.5+ / 24H", BLUE),
        (f"M{maxmag:.1f}" if maxmag else "-", "LARGEST QUAKE 24H", RED),
        (f"{kp_max}" if kp_max is not None else "-", "KP MAX 24H (G3=7)", "#8e44ad"),
        (f"{neo.get('count', '-')}", "NEOs PASSING TODAY", "#6c3483"),
        (f"{len(gdacs)}", "GDACS ORANGE/RED", "#e67e22"),
        (f"{len(elevated)}", "VOLCANOES ELEVATED", "#d35400"),
    ]
    band = fig.add_axes([0.04, 0.78, 0.92, 0.10])
    band.set_xlim(0, 6); band.set_ylim(0, 1); band.axis("off")
    for i, (num, lab, col) in enumerate(stats):
        x = i + 0.5
        band.add_patch(FancyBboxPatch((x - 0.44, 0.05), 0.88, 0.9,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            fc="white", ec=col, lw=2.2))
        band.text(x, 0.56, num, fontsize=25, fontweight="bold",
                  color=col, ha="center", va="center")
        band.text(x, 0.22, lab, fontsize=8.6, color=MUTED,
                  ha="center", va="center")

    # ---- left: 7-day quake trend
    ax_trend = fig.add_axes([0.055, 0.50, 0.40, 0.20])
    days_list, recs = _daily_history(7)
    if days_list:
        labels = [d[5:] for d in days_list]
        counts = [r["count"] for r in recs]
        mags = [r["maxmag"] for r in recs]
        colors = [RED if m >= 6.5 else ("#e67e22" if m >= 6.0 else BLUE)
                  for m in mags]
        bars = ax_trend.bar(labels, counts, color=colors, width=0.62,
                            edgecolor="none")
        for b, c, m in zip(bars, counts, mags):
            ax_trend.text(b.get_x() + b.get_width() / 2, c + 0.5,
                          f"{c}\nM{m:.1f}" if m else f"{c}",
                          ha="center", va="bottom", fontsize=8, color=INK)
        ax_trend.set_ylim(0, max(counts) * 1.30 if counts else 1)
        ax_trend.set_title("Earthquakes M4.5+ per day (last 7 days) - bar label shows daily max magnitude",
                           fontsize=10, color=INK, pad=6)
        ax_trend.tick_params(labelsize=9, colors=MUTED)
        for s in ("top", "right"):
            ax_trend.spines[s].set_visible(False)
        ax_trend.spines["left"].set_color("#dddddd")
        ax_trend.spines["bottom"].set_color("#dddddd")
        ax_trend.set_yticks([])
    else:
        ax_trend.axis("off")

    # ---- right: hazard mix donut
    ax_donut = fig.add_axes([0.53, 0.47, 0.20, 0.26])
    ax_donut.axis("off")
    ax_donut.set_title("NASA EONet open events by category",
                       fontsize=10, color=INK)
    cat_counts = {}
    for ev in tracked:
        for c in (ev.get("categories") or ["Other"]):
            cat_counts[c] = cat_counts.get(c, 0) + 1
    if cat_counts:
        items = sorted(cat_counts.items(), key=lambda kv: -kv[1])
        vals = [v for _, v in items]
        labs = [f"{k} ({v})" for k, v in items]
        palette = {"Wildfires": "#e67e22", "Severe Storms": BLUE,
                   "Volcanoes": RED, "Sea and Lake Ice": TEAL}
        cols = [palette.get(k, "#95a5a6") for k, _ in items]
        wedges, _ = ax_donut.pie(vals, colors=cols, startangle=90,
            wedgeprops=dict(width=0.42, edgecolor="white"))
        ax_donut.legend(wedges, labs, loc="center", fontsize=8.5,
                        frameon=False)

    # ---- right: active storms / tsunami status
    ax_storm = fig.add_axes([0.76, 0.47, 0.20, 0.26])
    ax_storm.axis("off")
    ax_storm.set_title("Tropical cyclones and tsunami", fontsize=10, color=INK)
    lines = []
    for s in nhc[:3]:
        lines.append((f"{s.get('type','?')} {s.get('storm','?')}", BLUE))
    if not nhc:
        lines.append(("No NHC Atlantic or Pacific storms active", TEAL))
    threat = tsunami.get("threatening")
    lines.append(("TSUNAMI THREAT: " + ("YES" if threat else "none in effect"),
                  RED if threat else TEAL))
    y = 0.72
    for text, col in lines:
        ax_storm.text(0.0, y, "-", fontsize=13, color=col,
                      ha="left", va="center", transform=ax_storm.transAxes)
        ax_storm.text(0.08, y, text, fontsize=10.5, color=INK,
                      ha="left", va="center", transform=ax_storm.transAxes)
        y -= 0.28

    # ---- bottom-left: significant alerts text panel
    ax_alerts = fig.add_axes([0.055, 0.09, 0.55, 0.30])
    ax_alerts.axis("off")
    ax_alerts.set_title("Significant signals today", fontsize=11,
                        color=INK, loc="left")
    alerts = []
    for g in gdacs[:4]:
        t = re.sub(r"\s+", " ", g.get("title", ""))[:88]
        alerts.append((f"[{g.get('severity','?').upper()}] {t}",
                       RED if g.get("severity") == "red" else "#e67e22"))
    for v in elevated[:3]:
        alerts.append((f"Volcano {v.get('title','?')} - alert {v.get('alert','?')}",
                       "#d35400"))
    big = sorted([q for q in eqs if q["mag"] >= 6.0],
                 key=lambda q: -q["mag"])[:3]
    for q in big:
        when = datetime.fromtimestamp(q["time"] / 1000,
              tz=timezone.utc).strftime("%H:%M") if q.get("time") else ""
        alerts.append((f"M{q['mag']:.1f} {q.get('place','')} ({when} UTC){' - TSUNAMI FLAG' if q.get('tsunami') else ''}", BLUE))
    if not alerts:
        alerts.append(("No significant alerts in the latest cycle.", TEAL))
    y = 0.88
    for text, col in alerts[:6]:
        ax_alerts.text(0.0, y, ">", fontsize=11, color=col,
                       ha="left", va="top", transform=ax_alerts.transAxes)
        ax_alerts.text(0.035, y, text, fontsize=9.8, color=INK,
                       ha="left", va="top", transform=ax_alerts.transAxes)
        y -= 0.145

    # ---- bottom-right: Australia panel
    ax_au = fig.add_axes([0.645, 0.09, 0.31, 0.30])
    ax_au.axis("off")
    ax_au.set_title("Australia watch", fontsize=11, color=INK, loc="left")
    au = snapshot.get("australia") or {}
    bom_n = bom.get("count") if isinstance(bom, dict) else None
    rfs = au.get("nsw_rfs_incidents") or []
    auq = au.get("au_quakes") or []
    au_lines = [
        (f"BOM warnings current: {bom_n if bom_n is not None else '-'}", "#d35400"),
        (f"NSW RFS bushfire incidents: {len(rfs) if isinstance(rfs, list) else rfs}", "#e67e22"),
        (f"Regional quakes M3+ (AU box, 24h): {len(auq) if isinstance(auq, list) else auq}", BLUE),
    ]
    y = 0.88
    for text, col in au_lines:
        ax_au.text(0.0, y, "-", fontsize=12, color=col, ha="left",
                   va="top", transform=ax_au.transAxes)
        ax_au.text(0.05, y, text, fontsize=10.3, color=INK, ha="left",
                   va="top", transform=ax_au.transAxes)
        y -= 0.22
    # top BOM warning headlines
    if isinstance(bom, dict):
        sev_order = {"extreme": 0, "high": 1, "medium": 2}
        wl = sorted(bom.get("warnings") or [],
                    key=lambda w: sev_order.get(w.get("severity", "medium"), 3))
        for w in wl[:2]:
            head = re.sub(r"\s+", " ", w.get("headline", ""))[:110]
            ax_au.text(0.0, y, "-", fontsize=10, color=MUTED, ha="left",
                       va="top", transform=ax_au.transAxes)
            ax_au.text(0.05, y, head, fontsize=8.2, color="#555555", ha="left",
                       va="top", transform=ax_au.transAxes)
            y -= 0.20

    # ---- footer
    fig.text(0.04, 0.028,
             "NOT an official warning channel - for emergencies follow BOM / PTWC / USGS / your national agency. "
             "All data from public feeds; methodology and sources at kheper1970.github.io/guardian",
             fontsize=9, color=MUTED, ha="left", va="center")

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)
    return out_png

# ---------------------------------------------------------------- main build

def latest_snapshot():
    files = sorted(glob.glob(str(BASE / "data" / "snapshot_*.json")))
    if not files:
        return None, None
    snap_f = files[-1]
    snap = json.load(open(snap_f))
    bom = None
    bom_f = BASE / "data" / "bom_warnings_latest.json"
    if bom_f.exists():
        try:
            bom = json.load(open(bom_f))
        except Exception:
            bom = None
    return snap, bom


def build_briefing_pages():
    """Convert every briefing .md to styled .html next to it."""
    import markdown
    n = 0
    for md in sorted(glob.glob(str(PUB / "briefing" / "briefing_*.md"))):
        day = re.search(r"briefing_(\d{4}-\d{2}-\d{2})", md).group(1)
        raw = open(md).read()
        alert = bool((BASE / "reports" / "ALERT").exists())
        html_body = markdown.markdown(raw, extensions=["tables", "fenced_code"])
        title = f"Guardian briefing - {day}"
        out = PUB / "briefing" / f"briefing_{day}.html"
        out.write_text(page(title, html_body, SHORT_DESC, alert=alert))
        n += 1
    return n


SHORT_DESC = ("Automated daily global risk briefing: earthquakes, space weather, "
              "near-Earth objects, volcanoes, cyclones and more from public feeds.")


def build_index(snap, bom, briefings):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    latest_day = sorted(briefings)[-1] if briefings else today
    alert = bool((BASE / "reports" / "ALERT").exists())
    alert_flag = '<span class="badge">ALERT ACTIVE</span>' if alert else ""

    # stat cards from snapshot
    cards = []
    if snap:
        eqs = [q for q in snap.get("earthquakes", [])
               if "error" not in q and isinstance(q.get("mag"), (int, float))]
        maxmag = max((q["mag"] for q in eqs), default=0)
        sw = snap.get("space_weather") or {}
        neo = snap.get("neo") or {}
        gdacs = snap.get("gdacs") or []
        volcano = snap.get("volcano") or {}
        cards = [
            (len(eqs), "quakes M4.5+ / 24h"),
            (f"M{maxmag:.1f}", "largest quake"),
            (sw.get("kp_max_24h"), "Kp max 24h"),
            (neo.get("count"), "NEOs today"),
            (len(gdacs), "GDACS orange/red"),
            (len(volcano.get("elevated") or []), "volcanoes elevated"),
        ]
    stat_html = '<div class="statgrid">' + "".join(
        f'<div class="stat"><div class="n">{v}</div><div class="l">{l}</div></div>'
        for v, l in cards) + "</div>"

    brief_list = "".join(
        f'<li><a href="briefing/briefing_{d}.html">Briefing {d}</a> '
        f'(<a href="briefing/briefing_{d}.md">raw .md</a>)</li>'
        for d in sorted(briefings, reverse=True))

    body = f"""
<h1>Guardian daily briefing - {latest_day} {alert_flag}</h1>
<div class="hero">
<h2>Today at a glance</h2>
<p>Consolidated from public civil-protection feeds. Updated hourly; the infographic
refreshes with every publish.</p>
</div>
<div class="card"><h2 style="margin-top:0">Latest snapshot statistics</h2>
{stat_html}
<p style="color:#666666;font-size:.9rem">Snapshot taken {snap.get('collected_utc', '?') if snap else '?'} UTC.
Open the <a href="briefing/briefing_{latest_day}.html">full briefing</a> for details and sources.</p>
</div>
<div class="card"><h2 style="margin-top:0">Daily infographic</h2>
<p><img src="img/infographic_latest.png" alt="Guardian daily statistics infographic for {latest_day}"></p>
<p style="color:#666666;font-size:.9rem">Also available as <a href="img/infographic_{latest_day}.png">archived daily PNG</a>
- right-click any image to share it.</p>
</div>
<div class="card"><h2 style="margin-top:0">Briefing archive</h2>
<ul>{brief_list}</ul>
</div>
<div class="card"><h2 style="margin-top:0">Sources and methodology</h2>
<p>All data comes from public authoritative feeds - USGS, NOAA SWPC and NTWC, NASA NEO and EONet,
GDACS, ReliefWeb, WHO, BOM, NHC - cited inline in every briefing. Full methodology and
source code in the <a href="https://github.com/kheper1970/guardian">GitHub repository</a>.</p>
<p><b>This is not an official warning channel.</b> For anything time-critical, follow
your national agency (BOM/JATWC in Australia, PTWC, USGS, GDACS).</p>
</div>
"""
    (PUB / "index.html").write_text(
        page("Guardian - Global Risk Monitor", body, SHORT_DESC, alert=alert))
    return latest_day


def main():
    snap, bom = latest_snapshot()
    if snap is None:
        print("build_site: no snapshot found; skipping")
        return 0
    briefings = sorted(re.search(r"briefing_(\d{4}-\d{2}-\d{2})", p).group(1)
                       for p in glob.glob(str(PUB / "briefing" / "briefing_*.md")))
    n_html = build_briefing_pages()
    day = snap.get("collected_utc", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    png = make_infographic(snap, bom, PUB / "img" / "infographic_latest.png")
    try:
        import shutil
        shutil.copy(png, PUB / "img" / f"infographic_{day}.png")
    except Exception:
        pass
    build_index(snap, bom, briefings)
    print(f"build_site: {n_html} briefing pages, infographic {png.name}, index updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
