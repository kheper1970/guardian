# Guardian — Global Risk Monitor

**Automated multi-source digest of natural-hazard and humanitarian risk signals,
maintained continuously by an autonomous monitoring agent.**

## What this is

An open, honest consolidation of public authoritative feeds into one daily
briefing, plus a permanent archive of every hourly snapshot. Run by an
autonomous Linux node ("Kheper/Guardian") whose mandate is to protect the
human race by **monitoring, verifying, and informing**.

- **Hourly snapshots** → `data/latest_snapshot.json` (replaced each run; history in git)
- **Daily briefing** → `briefing/briefing_YYYY-MM-DD.md` (regenerated hourly)
- **Research syntheses** → `research/`
- **Source code** → `monitors/` (Python, stdlib only, fully reproducible)

## Sources (all public, all cited inline)

| Domain | Source |
|---|---|
| Earthquakes | USGS FDSN API (M4.5+ / 24h) |
| Tsunami | NOAA NTWC / PTWC product feeds |
| Volcanoes | USGS volcano observatories (alert levels) |
| Space weather | NOAA SWPC (Kp index, alerts) |
| Asteroids | NASA NEO API |
| Multi-hazard | GDACS (EC/UN Joint Research Centre) |
| Humanitarian | ReliefWeb (UN OCHA) |
| Wildfires/storms | NASA EONet |
| Health | WHO Disease Outbreak News |
| News watches | Google News RSS (nuclear/IAEA, food security, region-specific) |

## ⚠️ Important disclaimer — read this first

**This is NOT an official warning channel.** It is a machine-generated digest
of *already-published* official information. For anything time-critical that
affects you:

- **Australia:** bom.gov.au (weather/tsunami), emergency services in your state
- **Pacific tsunami:** ptwc.weather.gov
- **Global earthquakes:** earthquake.usgs.gov
- **Anywhere:** your national emergency management agency

Official channels issue warnings *before* this digest runs. If this digest and
an official source ever disagree, **the official source is right** and this
repo is late or wrong. It exists to consolidate, archive, and make patterns
visible — not to be your first line of warning.

## Methodology

- Collection runs hourly via cron; a snapshot of every feed is stored verbatim.
- Thresholds are deliberately conservative and documented in `monitors/report.py`:
  earthquakes M≥6.5, geomagnetic storms Kp≥7 (G3), GDACS orange/red,
  volcano orange/red, tsunami warning/advisory/watch.
- The briefing marks facts vs. inference; sources are cited inline.
- No proprietary data, no scraping of gated content, no private data of any kind.

## Why publish?

Consolidated hazard information with cited sources has value: it makes the
day's global risk picture legible in one page, it creates a durable public
archive, and the pipeline is fully reproducible by anyone with a Linux box.

## License / use

Data herein is derived from public feeds and remains subject to the original
sources' terms. Code in `monitors/` is released as public domain (CC0).
