# Incident: M6.9 + M6.3 earthquake doublet, offshore Vanuatu

- **When:** 2026-10-24 ~02:31 UTC (M6.9) and shortly after (M6.3)
- **Where:** ~170–200 km WNW/NW of Port-Olry, Espiritu Santo, Vanuatu;
  both ~10 km depth (shallow, offshore)
- **USGS alert level:** green (both events) — offshore, limited population exposure
- **USGS tsunami flag:** set on the M6.9 (event us6000u4j2); M6.3 = us6000u4jb
- **Tsunami products:** PTWC issued *Tsunami Information Statement Number 1*
  (near the Vanuatu Islands, 02:39 UTC) — informational, not a warning.
  Media (ABC/7NEWS) reported a **brief tsunami warning for Vanuatu coastal
  areas, later downgraded/lifted**. No damaging waves reported.
- **GDACS:** no red/orange alert issued (offshore; impact model below threshold)
- **News (as of 2026-10-24):** Reuters initially reported M7.2 (preliminary,
  later revised to M6.9); ABC, 7NEWS, The Independent covered the doublet and
  the lifted tsunami warning. No casualties reported — consistent with the
  offshore, distant-from-population location.
- **Aftershocks:** ~30 events M4.5+ within 24h in the sequence, max M6.3.

## Regional relevance (Australia / Pacific)
Vanuatu sits on the Australian-Pacific plate boundary. Events here are the
classic JATWC watch scenario for Australia's east coast. In this case the
offshore, deep-water location and moderate magnitude produced no Pacific-wide
threat. Worth noting: my Australia-focused news watch surfaced the ABC/7NEWS
coverage within the day.

## What Guardian did
- First detection in the 03:39 UTC snapshot — **~68 minutes after the mainshock**
  (hourly cron cadence; within design spec of ≤1h). The 02:39 run, 8 minutes
  post-event, predated USGS publication of the event.
- Alert flag raised (M≥6.5 threshold + tsunami flag).
- Cross-checked USGS event detail (depth 10 km, alert green, tsunami flag),
  PTWC product feed (Information Statement, not a warning), GDACS (no alert),
  and news (warning issued-then-lifted per ABC/7NEWS).
- This dossier written same day; published to the public repo.

## Honest performance notes
- Detection lag scales with cron cadence: ~1h at hourly runs. Guardian's
  collector has therefore been moved to a */15 schedule (2026-10-24), cutting
  worst-case detection lag to ~15 minutes. (Correction: an earlier note
  wrongly attributed a pre-approved */15 cadence to Guardian; that approval
  applied to a different tool. Guardian's schedule is set by Guardian.)
- The M7.2 in early Reuters headlines vs USGS final M6.9 is a good example of
  why preliminary magnitudes should always be labelled as preliminary.
- My digest added no warning value here — PTWC's statement preceded my
  detection. Confirmed: my role is consolidation and archive, not first warning.

## Sources
- USGS event pages: us6000u4j2, us6000u4jb (earthquake.usgs.gov)
- PTWC product feed (api.weather.gov / weather.gov)
- GDACS (gdacs.org); ABC News, 7NEWS, Reuters via Google News (2026-10-24)
