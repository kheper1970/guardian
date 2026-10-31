#!/usr/bin/env python3
"""Turn the latest Guardian snapshot into a human-readable briefing.

Alert thresholds are deliberately conservative: this is an early-warning
digest, not a panic machine. Sources are cited inline.
"""
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
REPORTS = BASE / "reports"

# Alert thresholds (documented, adjustable)
QUAKE_ALERT_MAG = 6.5
KP_STORM_ALERT = 7.0
NEO_MISS_ALERT_KM = 1_000_000
GDACS_BANNER_MAX_AGE_H = 48  # reds older than this stay in body, drop from banner


def fmt_quake(q):
    mag = q.get("mag")
    ts = q.get("time")
    when = ""
    if ts:
        when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    return f"M{mag} {q.get('place')} ({when}){' TSUNAMI FLAG' if q.get('tsunami') else ''}"


def assess(snapshot):
    lines, alerts = [], []

    lines.append(f"# Guardian daily briefing — {snapshot['collected_utc'][:10]}")
    lines.append("")
    lines.append("Generated automatically from public feeds "
                 "(USGS, NOAA, NASA, WHO, GDACS, ReliefWeb, EONet, Google News). "
                 "All times UTC.")
    lines.append("")

    eqs = [q for q in snapshot.get("earthquakes", []) if "error" not in q]
    eq_errs = [q for q in snapshot.get("earthquakes", []) if "error" in q]
    lines.append("## Earthquakes (M4.5+, last 24h)")
    lines.append(f"Count: {len(eqs)}")
    big = [q for q in eqs if (q.get("mag") or 0) >= QUAKE_ALERT_MAG]
    for q in sorted(eqs, key=lambda x: -(x.get("mag") or 0))[:8]:
        lines.append(f"- {fmt_quake(q)}")
    if len(eqs) > 8:
        lines.append(f"- ...and {len(eqs)-8} more")
    if big:
        alerts.append(f"QUAKE M>={QUAKE_ALERT_MAG}: " + "; ".join(fmt_quake(q) for q in big))
    if eq_errs:
        lines.append(f"- (feed errors: {len(eq_errs)})")
    lines.append("")

    sw = snapshot.get("space_weather", {})
    lines.append("## Space weather")
    kp_latest = (sw.get("kp_latest") or {}).get("Kp")
    kp_max = sw.get("kp_max_24h")
    lines.append(f"- Kp now: {kp_latest}; max last 24h: {kp_max} "
                 f"(storm threshold G3 = Kp {KP_STORM_ALERT})")
    if kp_max is not None and kp_max >= KP_STORM_ALERT:
        alerts.append(f"GEOMAGNETIC STORM: Kp reached {kp_max} in last 24h")
    # SWPC alerts: newest first, dedup by message code (continuation serials),
    # and show the meaningful ALERT/WATCH line rather than the boilerplate header.
    swpc_sorted = sorted(sw.get("alerts_recent") or [],
                         key=lambda a: str(a.get("issued") or ""), reverse=True)
    seen_codes = set()
    for a in swpc_sorted:
        code = a.get("id")
        if code in seen_codes:
            continue
        seen_codes.add(code)
        if len(seen_codes) > 3:
            break
        msg = (a.get("message") or "").splitlines()
        headline = ""
        for l in msg:
            ls = l.strip()
            if ls and ls.upper().startswith(("ALERT", "WATCH", "WARNING", "SUMMARY", "CANCEL", "EXTENDED")):
                headline = ls
                break
        if not headline:
            for l in msg:
                ls = l.strip()
                if ls and not ls.lower().startswith(("space weather message code", "serial number", "issue time")):
                    headline = ls
                    break
        lines.append(f"- SWPC alert {code} ({a.get('issued','')[:16]}): {headline[:120]}")
    lines.append("")

    neo = snapshot.get("neo", {})
    lines.append("## Near-Earth objects passing today")
    lines.append(f"Count: {neo.get('count')}")
    for e in (neo.get("events") or [])[:5]:
        note = " [POTENTIALLY HAZARDOUS]" if e.get("hazardous") else ""
        lines.append(
            f"- {e['name']}: {e['diameter_min_m']}-{e['diameter_max_m']} m, "
            f"miss {e['miss_km']/1e6:.1f}M km{note}"
        )
    for e in (neo.get("events") or []):
        if e.get("hazardous") and e.get("miss_km", 9e99) < NEO_MISS_ALERT_KM:
            alerts.append(
                f"NEO CLOSE APPROACH: {e['name']} hazardous, miss "
                f"{e['miss_km']/1e6:.2f}M km"
            )
    lines.append("")

    # --- GDACS multi-hazard ---
    gdacs = snapshot.get("gdacs", [])
    lines.append("## GDACS significant alerts (orange/red)")
    if gdacs:
        for g in gdacs[:10]:
            when = g.get("pubdate", "")
            stamp = f" ({when[:16].replace('T', ' ')} UTC)" if when else ""
            lines.append(f"- [{g['severity'].upper()}]{stamp} {g['title']}")
    else:
        lines.append("None. No orange/red multi-hazard alerts active.")
    lines.append("")
    now_utc = datetime.now(timezone.utc)
    for g in gdacs:
        if g["severity"].lower() != "red":
            continue
        pub = g.get("pubdate", "")
        fresh = True  # fail-loud: if age unknown, keep the banner alert
        if pub:
            try:
                pub_dt = datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                fresh = (now_utc - pub_dt).total_seconds() <= GDACS_BANNER_MAX_AGE_H * 3600
            except Exception:
                pass
        if fresh:
            alerts.append(f"GDACS RED: {g['title'][:150]}")
    lines.append("")

    # --- Tsunami ---
    tsu = snapshot.get("tsunami", {})
    lines.append("## Tsunami (NOAA NTWC)")
    lines.append(f"- Latest product: {tsu.get('latest_product', 'n/a')}")
    if tsu.get("threatening"):
        for e in tsu["threatening"]:
            lines.append(f"- **{e['category']}: {e['event']}** (updated {e['updated']})")
            alerts.append(f"TSUNAMI {e['category']}: {e['event']}")
    else:
        lines.append("- No warning/advisory/watch in effect.")
    lines.append("")

    # --- Volcanoes (USGS) ---
    volc = snapshot.get("volcano", {})
    lines.append("## Volcanoes (USGS observatories)")
    elevated = volc.get("elevated", [])
    if elevated:
        for v in elevated:
            lines.append(f"- {v['volcano']} [{v['color']}/{v['alert']}] ({v['observatory']})")
            if str(v["color"]).upper() in ("ORANGE", "RED"):
                alerts.append(f"VOLCANO {v['color']}: {v['volcano']} ({v['observatory']})")
    else:
        lines.append("- No US volcanoes at elevated alert.")
    lines.append("")

    # --- Volcanoes (GVP weekly, global) ---
    gvp = snapshot.get("gvp_weekly", {})
    if gvp.get("error"):
        lines.append(f"- GVP weekly report unavailable: {gvp['error']}")
    else:
        lines.append(f"## Volcanoes (Smithsonian GVP weekly, week of {gvp.get('report_week', 'n/a')})")
        volcs = gvp.get("volcanoes", [])
        if volcs:
            lines.append(f"- {gvp.get('count', len(volcs))} volcanoes reported active; "
                         f"{gvp.get('new_activity_count', 0)} with new activity")
            for v in volcs:
                flag = " **[NEW ACTIVITY]**" if "new" in v.get("status", "").lower() else ""
                lines.append(f"- {v['volcano']} - {v['status']}{flag}")
                if v.get("status", "").lower().startswith("new"):
                    alerts.append(f"VOLCANO-NEW {v['volcano']}: new eruptive activity (GVP weekly)")
        else:
            lines.append("- No volcanoes parsed from GVP weekly report.")
    lines.append("")

    # --- EONet (NASA global events) ---
    eonet = snapshot.get("eonet", {})
    lines.append("## NASA EONet open events (wildfires, storms, volcanoes)")
    if eonet.get("error"):
        lines.append(f"- feed error: {eonet['error']}")
    else:
        lines.append(f"- Open events total: {eonet.get('open_total')}; "
                     f"tracked categories: {len(eonet.get('tracked', []))}")
        for e in (eonet.get("tracked") or [])[:12]:
            lines.append(f"- [{', '.join(e.get('categories', []))}] {e['title']} "
                         f"(last update {str(e.get('date'))[:10]})")
    lines.append("")

    # --- NHC tropical cyclones ---
    nhc = snapshot.get("nhc_storms", [])
    lines.append("## Tropical cyclones (NHC Atlantic + E/C Pacific)")
    storms = [s for s in nhc if "storm" in s]
    errs = [s for s in nhc if "error" in s]
    if storms:
        for s in storms:
            advs = s.get("advisories", [])
            latest = advs[0] if advs else {}
            lines.append(f"- **{s.get('type')} {s.get('storm')}** ({s.get('basin')}): "
                         f"latest: {latest.get('title','')} "
                         f"({latest.get('pubDate','')[:16]})")
            for a in advs[:4]:
                lines.append(f"  - {a['title']} {a['link']}")
            low = (latest.get("title") or "").lower()
            if s.get("type") == "Hurricane":
                alerts.append(f"NHC HURRICANE ACTIVE: {s.get('storm')} "
                              f"({s.get('basin')}) - {latest.get('title','')[:120]}")
            if "watch" in low or "warning" in low:
                alerts.append(f"NHC WATCH/WARNING: {s.get('storm')} - {latest.get('title','')[:120]}")
    else:
        lines.append("- No active NHC-tracked storms.")
    for e in errs:
        lines.append(f"- feed error ({e.get('basin')}): {e['error']}")
    lines.append("")

    # --- Nuclear / radiological watch ---
    lines.append("## Nuclear & radiological watch (Google News: IAEA/incident keywords)")
    nuc = snapshot.get("nuclear_news", [])
    if isinstance(nuc, dict) and nuc.get("error"):
        lines.append(f"- feed error: {nuc['error']}")
    else:
        for n in (nuc or [])[:6]:
            lines.append(f"- {n.get('title')} ({n.get('pubDate','')[:16]})")
            low = n.get("title", "").lower()
            prep_words = ("workshop", "exercise", "training", "preparedness",
                          "convene", "drill", "simulation", "anniversary",
                          "capacity building", "plan", "course",
                          "marks", "strengthen", "support")
            if (("radiological release" in low or "nuclear accident" in low
                    or "ines level" in low or "cannot rule out" in low)
                    and not any(w in low for w in prep_words)):
                alerts.append(f"NUCLEAR KEYWORD HIT: {n.get('title')[:150]}")
    lines.append("")

    # --- Food security watch ---
    lines.append("## Food security watch (Google News: famine keywords)")
    fam = snapshot.get("famine_news", [])
    if isinstance(fam, dict) and fam.get("error"):
        lines.append(f"- feed error: {fam['error']}")
    else:
        for n in (fam or [])[:6]:
            lines.append(f"- {n.get('title')} ({n.get('pubDate','')[:16]})")
            low = n.get("title", "").lower()
            if "famine" in low and ("declared" in low or "phase 5" in low):
                alerts.append(f"FAMINE KEYWORD HIT: {n.get('title')[:150]}")
    lines.append("")

    # --- Humanitarian watch: famine & conflict (UN News + ReliefWeb) ---
    hw = snapshot.get("humanitarian_watch", {})
    if isinstance(hw, dict):
        lines.append("## Famine watch (UN News + ReliefWeb keywords)")
        if hw.get("errors"):
            lines.append(f"- feed errors: {'; '.join(hw['errors'])[:200]}")
        fam2 = hw.get("famine", [])
        if not fam2:
            lines.append("- no famine/food-crisis keyword items in feeds")
        for n in fam2[:8]:
            lines.append(f"- [{n.get('source')}] {n.get('title')} "
                         f"({n.get('pubDate', '')[:16]})")
            low = (n.get("title") or "").lower()
            strong_fam = (
                ("famine" in low and any(w in low for w in (
                    "declared", "phase 5", "risk of famine",
                    "imminent", "catastroph")))
                or "ipc phase 5" in low)
            if strong_fam:
                lines.append(f"  **FAMINE SIGNAL: {n.get('title')[:150]}**")
                alerts.append(f"FAMINE SIGNAL: {n.get('title')[:150]}")
        lines.append("")

        lines.append("## Armed conflict watch (UN News + ReliefWeb keywords)")
        con = hw.get("conflict", [])
        if not con:
            lines.append("- no armed-conflict keyword items in feeds")
        for n in con[:8]:
            lines.append(f"- [{n.get('source')}] {n.get('title')} "
                         f"({n.get('pubDate', '')[:16]})")
            low = (n.get("title") or "").lower()
            if any(w in low for w in ("massacre", "genocide", "airstrike",
                                      "air strike", "military offensive")):
                lines.append(f"  **CONFLICT SIGNAL: {n.get('title')[:150]}**")
                alerts.append(f"CONFLICT SIGNAL: {n.get('title')[:150]}")
        lines.append("")

    # --- Australia watch ---
    lines.append("## Australia watch (ABC News, NSW RFS, USGS AU quakes, GNews AU, health.gov.au)")
    au = snapshot.get("australia", {})
    if isinstance(au, dict):
        abc = au.get("abc_news", [])
        if isinstance(abc, dict) and abc.get("error"):
            lines.append(f"- ABC feed error: {abc['error']}")
        else:
            for n in (abc or [])[:5]:
                lines.append(f"- {n.get('title')} ({n.get('pubDate','')[:16]})")
        rfs = au.get("nsw_rfs_incidents", [])
        if isinstance(rfs, dict) and rfs.get("error"):
            lines.append(f"- NSW RFS feed error: {rfs['error']}")
        else:
            warn = [i for i in (rfs or [])
                    if "warning" in (i.get("category") or "").lower()]
            lines.append(f"- NSW RFS current incidents: {len(rfs or [])} "
                          f"({len(warn)} at Warning level)")
            for i in warn[:5]:
                lines.append(f"  - [{i.get('category')}] {i.get('title')}")
                alerts.append(f"NSW RFS WARNING: {i.get('title')[:150]}")

        qks = au.get("au_quakes", [])
        if isinstance(qks, dict) and qks.get("error"):
            lines.append(f"- AU quake feed error: {qks['error']}")
        else:
            mags = [q.get("mag") for q in (qks or []) if q.get("mag")]
            lines.append(f"- AU-region quakes (24h): {len(qks or [])}, "
                          f"max M{max(mags):.1f}" if mags else
                          f"- AU-region quakes (24h): {len(qks or [])}")
            for q in (qks or [])[:3]:
                lines.append(f"  - M{q.get('mag')} {q.get('place')}")
                if (q.get("mag") or 0) >= 5.0:
                    alerts.append(f"AU QUAKE M{q.get('mag')}: {q.get('place')}")

        emg = au.get("au_emergency_news", [])
        if isinstance(emg, dict) and emg.get("error"):
            lines.append(f"- AU emergency feed error: {emg['error']}")
        else:
            lines.append("- AU emergency headlines:")
            for n in (emg or [])[:5]:
                lines.append(f"  - {n.get('title')} ({n.get('pubDate','')[:16]})")
                low = (n.get('title') or '').lower()
                # Strong signals alone are enough; weak topic words need
                # active-event language. Advocacy/preparedness stories never
                # trigger (reduce false-positive public alerts).
                strong = ("evacuat" in low or "state of emergency" in low
                          or "emergency warning" in low or "landfall" in low
                          or "out of control" in low)
                strong = strong or "evacuat" in low
                weak_topic = ("cyclone" in low or "bushfire" in low
                              or "flood" in low or "storm" in low)
                active_marker = any(w in low for w in (
                    "hits", "strikes", "threaten", "bears down", "category",
                    "destructive", "landfall", "out of control", "evacuat",
                    "warning issued", "alert issued"))
                advocacy = any(w in low for w in (
                    "predict", "forecast", "season", "prepare", "safety push",
                    "campaign", "urges", "push for", "didn't know", "anniversary",
                    "inquiry", "study", "research", "survey", "program", "drill",
                    "exercise", "lesson", "memorial", "how to", "tips", "explainer"))
                trigger = (strong or (weak_topic and active_marker)) and not advocacy
                if trigger:
                    alerts.append(f"AU EMERGENCY KEYWORD HIT: {n.get('title')[:150]}")
        sec = au.get("au_security_news", [])
        if isinstance(sec, dict) and sec.get("error"):
            lines.append(f"- AU security feed error: {sec['error']}")
        else:
            for n in (sec or [])[:4]:
                lines.append(f"  - {n.get('title')} ({n.get('pubDate','')[:16]})")
        hn = au.get("au_health_news", [])
        if isinstance(hn, dict) and hn.get("error"):
            lines.append(f"- health.gov.au error: {hn['error']}")
        else:
            lines.append("- health.gov.au:")
            for n in (hn or [])[:5]:
                lines.append(f"  - {n.get('title')}")
    lines.append("")

    # --- BOM Australia warnings ---
    lines.append("## BOM warnings (Bureau of Meteorology Australia)")
    bom = snapshot.get("bom", {})
    if isinstance(bom, dict) and bom.get("error"):
        lines.append(f"- BOM feed error: {bom['error']}")
    elif isinstance(bom, dict):
        warns = bom.get("warnings", [])
        sev_high = [w for w in warns if w.get("severity") == "high"]
        sev_med = [w for w in warns if w.get("severity") == "medium"]
        lines.append(f"- Products scanned: {bom.get('count', len(warns))}, "
                     f"high: {len(sev_high)}, medium: {len(sev_med)}, "
                     f"errors: {bom.get('errors', 0)}")
        for w in sev_high[:8]:
            lines.append(f"  - HIGH [{w.get('id')}] {w.get('title')} ({w.get('issued','')})")
            alerts.append(f"BOM HIGH: [{w.get('id')}] {w.get('title', '')[:150]}")
        for w in sev_med[:8]:
            lines.append(f"  - MED [{w.get('id')}] {w.get('title')}")
    lines.append("")

    lines.append("## WHO news (health emergencies, outbreaks)")
    for item in snapshot.get("who_news", [])[:8]:
        lines.append(f"- {item.get('title')}")
    lines.append("")

    lines.append("## ReliefWeb disasters (OCHA)")
    for d in snapshot.get("reliefweb", {}).get("disasters", [])[:8]:
        lines.append(f"- {d['pubDate']}: {d['title']}")
    lines.append("")

    lines.append("## Alerts")
    if alerts:
        for a in alerts:
            lines.append(f"**{a}**")
    else:
        lines.append("None above thresholds. Normal background conditions.")
    lines.append("")
    return lines, alerts


def main():
    snaps = sorted(glob.glob(str(DATA / "snapshot_*.json")))
    if not snaps:
        print("no snapshots found", file=sys.stderr)
        return 1
    snapshot = None
    for p in reversed(snaps):
        try:
            snapshot = json.loads(Path(p).read_text())
            if p != snaps[-1]:
                print(f"WARNING: newest snapshot unreadable; fell back to {Path(p).name}", file=sys.stderr)
            break
        except json.JSONDecodeError:
            continue
    if snapshot is None:
        print("no readable snapshot found", file=sys.stderr)
        return 1
    lines, alerts = assess(snapshot)

    day = snapshot["collected_utc"][:10]
    out = REPORTS / f"briefing_{day}.md"
    out.write_text("\n".join(lines))

    alert_flag = REPORTS / "ALERT"
    if alerts:
        alert_flag.write_text("\n".join(alerts) + "\n")
        print("ALERT:", "; ".join(alerts))
    elif alert_flag.exists():
        alert_flag.unlink()

    print(f"briefing -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
