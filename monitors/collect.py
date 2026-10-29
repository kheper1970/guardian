#!/usr/bin/env python3
"""Guardian risk-feed collector.

Polls authoritative public feeds and writes normalised JSON snapshots plus a
human-readable report. Designed to run from cron; safe to re-run.
"""
import json
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
REPORTS = BASE / "reports"
DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

UA = {"User-Agent": "GuardianRiskMonitor/1.0 (research; contact via host admin)"}


def fetch(url, timeout=20, as_json=True):
    req = urllib.request.Request(url, headers=UA)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if as_json else raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(8)
                continue
            raise
    raise last


def collect_quakes():
    """USGS significant + M4.5+ events in the last 24h."""
    out = []
    for feed in ("4.5_day.geojson", "significant_day.geojson"):
        try:
            d = fetch(
                "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/" + feed
            )
            for f in d.get("features", []):
                p = f["properties"]
                out.append({
                    "mag": p.get("mag"),
                    "place": p.get("place"),
                    "time": p.get("time"),
                    "tsunami": bool(p.get("tsunami")),
                    "url": p.get("url"),
                    "type": f.get("properties", {}).get("type", "earthquake"),
                })
        except Exception as exc:
            out.append({"error": f"usgs {feed}: {exc}"})
    seen, dedup = set(), []
    for q in out:
        key = q.get("url") or str(q)
        if key not in seen:
            seen.add(key)
            dedup.append(q)
    return dedup


def collect_spaceweather():
    """NOAA SWPC: current Kp series (tail) + latest alerts."""
    result = {}
    try:
        kp = fetch(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
        )
        result["kp_latest"] = kp[-1] if len(kp) else None
        result["kp_max_24h"] = max(
            (row["Kp"] for row in kp[-8:]), default=None
        )
    except Exception as exc:
        result["kp_error"] = str(exc)
    try:
        alerts = fetch("https://services.swpc.noaa.gov/products/alerts.json")
        result["alerts_recent"] = [
            {"id": a.get("product_id"), "issued": a.get("issue_datetime"),
             "message": (a.get("message") or "")[:400]}
            for a in alerts[-5:]
        ]
    except Exception as exc:
        result["alerts_error"] = str(exc)
    return result


def collect_neo():
    """NASA NEO feed: close approaches today (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = ("https://api.nasa.gov/neo/rest/v1/feed?"
           f"start_date={today}&end_date={today}&api_key=DEMO_KEY")
    d = fetch(url)
    events = []
    for _date, neos in (d.get("near_earth_objects") or {}).items():
        for n in neos:
            cad = (n.get("close_approach_data") or [{}])[0]
            est = n["estimated_diameter"]["meters"]
            events.append({
                "name": n.get("name"),
                "diameter_min_m": round(est["estimated_diameter_min"]),
                "diameter_max_m": round(est["estimated_diameter_max"]),
                "hazardous": n.get("is_potentially_hazardous_asteroid"),
                "miss_km": float(cad.get("miss_distance", {}).get("kilometers", 0)),
                "velocity_kph": float(
                    cad.get("relative_velocity", {}).get("kilometers_per_hour", 0)
                ),
            })
    events.sort(key=lambda e: e["miss_km"])
    return {"count": d.get("element_count"), "events": events}


def collect_who():
    """WHO news RSS - crude XML title/link extraction."""
    import re
    raw = fetch("https://www.who.int/rss-feeds/news-english.xml",
                as_json=False)
    items = re.findall(r"<item>(.*?)</item>", raw, re.S)
    out = []
    for item in items[:10]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        out.append({
            "title": (t.group(1).strip() if t else "")[:200],
            "link": (l.group(1).strip() if l else "")[:300],
        })
    return out


def collect_gdacs():
    """GDACS multi-hazard alerts; keep only orange/red severity."""
    import re
    raw = fetch("https://www.gdacs.org/xml/rss.xml", as_json=False)
    items = re.findall(r"<item>(.*?)</item>", raw, re.S)
    out = []
    for item in items:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        title = (t.group(1) if t else "").strip()
        if not (title.startswith("Orange") or title.startswith("Red")):
            continue
        d = re.search(r"<description>(.*?)</description>", item, re.S)
        pd = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        pub = ""
        if pd:
            try:
                from email.utils import parsedate_to_datetime
                pub = parsedate_to_datetime(pd.group(1).strip()).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
        out.append({
            "severity": title.split()[0],
            "title": title[:250],
            "description": (d.group(1).strip() if d else "")[:400],
            "pubdate": pub,
        })
    return out


def collect_volcano():
    """USGS volcano observatories: elevated volcanoes."""
    out = {"elevated": []}
    try:
        data = fetch("https://volcanoes.usgs.gov/hans-public/api/volcano/getElevatedVolcanoes")
        for v in (data or []):
            out["elevated"].append({
                "volcano": v.get("volcano_name"),
                "observatory": v.get("obs_abbr"),
                "color": v.get("color_code"),
                "alert": v.get("alert_level"),
                "sent_utc": v.get("sent_utc"),
            })
    except Exception as e:
        out["error"] = str(e)
    return out


def collect_tsunami():
    """NOAA NTWC tsunami products; flag warning/advisory/watch (not info)."""
    import re
    raw = fetch("https://www.tsunami.gov/events/xml/PAAQAtom.xml", as_json=False)
    feed_title = re.search(r"<title>(.*?)</title>", raw, re.S)
    entries = re.findall(r"<entry>(.*?)</entry>", raw, re.S)
    out = []
    for e in entries:
        t = re.search(r"<title>(.*?)</title>", e, re.S)
        u = re.search(r"<updated>(.*?)</updated>", e, re.S)
        title = (t.group(1).strip() if t else "")
        m = re.search(r"<strong>Category:</strong>\s*([A-Za-z ]+)", e)
        category = (m.group(1).strip() if m else "")
        out.append({
            "event": title[:150],
            "updated": (u.group(1).strip() if u else ""),
            "category": category,
        })
    return {
        "latest_product": (feed_title.group(1).strip() if feed_title else ""),
        "entries": out[:10],
        "threatening": [e for e in out
                        if any(w in (e["category"] + e["event"]).lower()
                               for w in ("warning", "advisory", "watch"))],
    }


def collect_reliefweb():
    """ReliefWeb (OCHA) latest disasters RSS feed."""
    import xml.etree.ElementTree as ET
    raw = fetch("https://reliefweb.int/disasters/rss.xml", as_json=False)
    root = ET.fromstring(raw)
    out = []
    for item in root.iter("item"):
        t = item.find("title")
        d = item.find("pubDate")
        l = item.find("link")
        out.append({"title": t.text.strip() if t is not None else "", "pubDate": d.text.strip() if d is not None else "", "link": l.text.strip() if l is not None else ""})
    return {"disasters": out[:15]}


def collect_eonet():
    """NASA EONet v3: open natural events, tracked categories."""
    tracked_cats = ("Wildfires", "Severe Storms", "Volcanoes")
    out = []
    try:
        d = fetch("https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100&days=20")
        events = d.get("events", [])
        for e in events:
            cats = [c.get("title") for c in e.get("categories", [])]
            geo = e.get("geometry") or []
            if any(c in tracked_cats for c in cats):
                out.append({
                    "title": (e.get("title") or "")[:150],
                    "categories": cats,
                    "date": geo[-1].get("date") if geo else None,
                    "link": e.get("link"),
                })
        return {"open_total": len(events), "tracked": out[:30]}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def collect_gnews(query, region="US"):
    """Google News RSS search; recent headlines for a topic."""
    import re
    import urllib.parse
    loc = {"US": "hl=en-US&gl=US&ceid=US:en",
           "AU": "hl=en-AU&gl=AU&ceid=AU:en"}.get(region, "hl=en-US&gl=US&ceid=US:en")
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query) + "&" + loc)
    raw = fetch(url, as_json=False)
    items = re.findall(r"<item>(.*?)</item>", raw, re.S)
    out = []
    for item in items[:8]:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        p = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        out.append({
            "title": (t.group(1).strip() if t else "")[:220],
            "pubDate": (p.group(1).strip() if p else "")[:40],
        })
    return out


def collect_australia():
    """AU feeds: ABC News, NSW RFS incidents, AU quakes, GNews, health."""
    import re
    out = {}

    def rss_items(raw, limit=10):
        items = re.findall(r"<item>(.*?)</item>", raw, re.S)
        rows = []
        for item in items[:limit]:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
            p = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
            rows.append({"title": (t.group(1).strip() if t else "")[:220],
                         "pubDate": (p.group(1).strip() if p else "")[:40]})
        return rows

    try:
        out["abc_news"] = rss_items(
            fetch("https://www.abc.net.au/news/feed/51120/rss.xml", as_json=False))
    except Exception as exc:
        out["abc_news"] = {"error": str(exc)}

    try:
        raw = fetch("https://www.rfs.nsw.gov.au/feeds/majorIncidents.xml",
                    as_json=False)
        items = re.findall(r"<item>(.*?)</item>", raw, re.S)
        incidents = []
        for item in items[:20]:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
            cat = re.search(r"<category>(.*?)</category>", item, re.S)
            incidents.append({
                "title": (t.group(1).strip() if t else "")[:200],
                "category": (cat.group(1).strip() if cat else "")[:60],
            })
        out["nsw_rfs_incidents"] = incidents
    except Exception as exc:
        out["nsw_rfs_incidents"] = {"error": str(exc)}

    try:
        d = fetch(
            "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
            "&minlatitude=-44&maxlatitude=-10&minlongitude=112&maxlongitude=154"
            "&limit=15&orderby=time")
        quakes = []
        for f in d.get("features", []):
            p = f["properties"]
            quakes.append({
                "mag": p.get("mag"),
                "place": p.get("place"),
                "time": p.get("time"),
                "url": p.get("url"),
            })
        out["au_quakes"] = quakes
    except Exception as exc:
        out["au_quakes"] = {"error": str(exc)}

    try:
        out["au_emergency_news"] = collect_gnews(
            "Australia emergency OR evacuation OR \"state of emergency\" "
            "OR cyclone OR bushfire OR flood warning when:2d", region="AU")
    except Exception as exc:
        out["au_emergency_news"] = {"error": str(exc)}

    try:
        out["au_security_news"] = collect_gnews(
            "Australia defence OR military OR ADF OR security when:2d",
            region="AU")
    except Exception as exc:
        out["au_security_news"] = {"error": str(exc)}

    try:
        raw = fetch("https://www.health.gov.au/news", as_json=False)
        # Capture heading attributes too so screen-reader-only chrome
        # (class="visually-hidden" / "au-sronly") can be filtered by class,
        # not by fragile keyword lists.
        titles = re.findall(r"<h[23]\b([^>]*)>(?:<[^>]+>)*([^<]{10,140})", raw)
        junk = {"News", "About us", "Contact us", "Resources",
                "Programs & initiatives", "Topics", "Search"}
        seen, uniq = set(), []
        for attrs, t in titles:
            a = attrs.lower()
            if ("sronly" in a or "visually-hidden" in a
                    or "visuallyhidden" in a):
                continue
            t = t.strip()
            if t and t not in seen and t not in junk:
                seen.add(t)
                uniq.append({"title": t})
        out["au_health_news"] = uniq[:10]
    except Exception as exc:
        out["au_health_news"] = {"error": str(exc)}

    return out


def collect_nhc():
    """NHC tropical cyclone activity: Atlantic + E/C Pacific RSS.
    Returns active storms with latest advisory titles/links/dates."""
    import re
    out = []
    for basin, url in (("atlantic", "https://www.nhc.noaa.gov/index-at.xml"),
                       ("east_pacific", "https://www.nhc.noaa.gov/index-ep.xml"),
                       ("central_pacific", "https://www.nhc.noaa.gov/index-cp.xml")):
        try:
            raw = fetch(url, as_json=False)
            items = re.findall(r"<item>(.*?)</item>", raw, re.S)
            storms = {}
            for item in items:
                t = re.search(r"<title>(.*?)</title>", item, re.S)
                l = re.search(r"<link>(.*?)</link>", item, re.S)
                d = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
                title = (t.group(1).strip() if t else "").replace("\n", " ")
                # e.g. "Hurricane Vance Public Advisory Number 13"
                m = re.match(r"(Tropical (?:Storm|Depression)|Hurricane|Potential Tropical Cyclone)\s+([A-Za-z\-]+)\s+(.*)", title)
                if not m:
                    continue
                kind, name, rest = m.groups()
                if name not in storms:
                    storms[name] = {"storm": name, "type": kind.title(),
                                    "basin": basin, "advisories": []}
                storms[name]["advisories"].append({
                    "title": title[:200],
                    "link": (l.group(1).strip() if l else "")[:300],
                    "pubDate": (d.group(1).strip() if d else "")[:40],
                })
            out.extend(storms.values())
        except Exception as exc:
            out.append({"basin": basin, "error": str(exc)})
    return out


def collect_iaea():
    """IAEA official news feed - authoritative nuclear/radiological source."""
    import re
    raw = fetch("https://www.iaea.org/feeds/news", as_json=False)
    items = re.findall(r"<item>(.*?)</item>", raw, re.S)
    out = []
    for item in items[:12]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        p = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        out.append({
            "title": (t.group(1).strip() if t else "")[:250],
            "link": (l.group(1).strip() if l else "")[:300],
            "pubDate": (p.group(1).strip() if p else "")[:40],
        })
    return out


def collect_gdelt(query, timespan="3d", maxrecords=8):
    """GDELT DOC 2.0 API - global news article search, no key required.
    Rate-limited: retries with backoff on 429/non-JSON responses."""
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
           + urllib.parse.quote(query)
           + "&mode=artlist&maxrecords=" + str(maxrecords)
           + "&format=json&timespan=" + timespan)
    d = None
    for attempt in range(4):
        if attempt:
            time.sleep(20 * attempt)  # 20s, 40s, 60s backoff
        try:
            d = fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                continue
            raise
        except json.JSONDecodeError:
            d = None  # non-JSON body (rate-limit page) -> retry
        if isinstance(d, dict) and "articles" in d:
            break
        d = None  # non-JSON (rate-limit text page) -> retry
    if d is None:
        return {"error": "GDELT rate-limited or non-JSON after retries"}
    arts = d.get("articles") or []
    return [
        {
            "title": (a.get("title") or "")[:250],
            "domain": a.get("domain"),
            "seendate": a.get("seendate"),
            "url": (a.get("url") or "")[:300],
        }
        for a in arts
    ]


def collect_famine():
    """GDELT famine/food-insecurity coverage (FAO/IPC/FEWS feeds unavailable)."""
    return collect_gdelt(
        'famine OR "food insecurity" OR "food crisis"', timespan="3d")


def collect_conflict():
    """GDELT armed-conflict coverage (ACLED requires registration)."""
    return collect_gdelt(
        '"armed conflict" OR "military offensive" OR "airstrike" '
        'OR "massacre" OR "war crimes"', timespan="3d")


def prune_snapshots(keep_days=30):
    """Keep all snapshots within keep_days; beyond that keep 1/day (earliest)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y%m%d")
    by_day = {}
    for path in sorted(DATA.glob("snapshot_*.json")):
        date = path.name[9:17]  # YYYYMMDD
        by_day.setdefault(date, []).append(path)
    removed = 0
    for date, paths in by_day.items():
        if date < cutoff and len(paths) > 1:
            for path in paths[1:]:
                path.unlink()
                removed += 1
    if removed:
        print(f"pruned {removed} snapshots (>{keep_days}d old, kept 1/day)")


def main():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    snapshot = {"collected_utc": now.isoformat()}

    for name, fn in (("earthquakes", collect_quakes),
                    ("space_weather", collect_spaceweather),
                    ("neo", collect_neo),
                    ("who_news", collect_who),
                    ("gdacs", collect_gdacs),
                    ("tsunami", collect_tsunami),
                    ("volcano", collect_volcano),
                    ("reliefweb", collect_reliefweb),
                    ("nhc_storms", collect_nhc),
                    ("eonet", collect_eonet),
                    ("nuclear_news", lambda: collect_gnews("IAEA radiological emergency OR nuclear incident OR nuclear accident")),
                    ("famine_news", lambda: collect_gnews("famine OR food insecurity emergency")),
                    ("australia", collect_australia),
                    ("iaea", collect_iaea),
                    ("famine_gdelt", lambda: (time.sleep(6), collect_famine())[1]),
                    ("conflict_gdelt", lambda: (time.sleep(6), collect_conflict())[1])):
        try:
            snapshot[name] = fn()
        except Exception as exc:
            snapshot[name] = {"error": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc()[-500:]}
        time.sleep(1)

    out_path = DATA / f"snapshot_{stamp}.json"
    tmp_path = DATA / f"snapshot_{stamp}.json.tmp"
    tmp_path.write_text(json.dumps(snapshot, indent=1))
    tmp_path.replace(out_path)  # atomic rename; readers never see partial file
    print(f"snapshot -> {out_path.name}")
    prune_snapshots()
    return 0


if __name__ == "__main__":
    sys.exit(main())
