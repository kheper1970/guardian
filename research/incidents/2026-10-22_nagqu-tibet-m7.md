# Incident: M7.0 earthquake, Nagqu (Tibet), China

- **When:** 2026-10-22 14:33 UTC
- **Where:** 191 km ENE of Nagqu, Nagqu, China; depth 18 km (shallow — worse shaking)
- **USGS alert level:** ORANGE (significant casualties/damage estimated likely)
- **Tsunami:** none (inland)
- **Reported impact (news, as of 2026-10-23):** at least 16 killed, 65 injured
  (Reuters/Al Jazeera/Xinhua via Google News)
- **Aftershocks:** numerous M4.9-5.2 events tracked in the 24h feed
- **USGS event page:** https://earthquake.usgs.gov/earthquakes/eventpage/us6000u43g

## What Guardian did
- Detected automatically via USGS M4.5+/day feed at first collection run
  (2026-10-23 06:39 UTC snapshot; threshold M>=6.5 triggered an ALERT flag).
- Cross-checked USGS event detail API (depth, alert level, tsunami flag).
- Guardian has no direct role in response; its function is detection,
  verification, and early notification.

## Notes
- Response-phase help (rescue, medical) is outside my capability; the useful
  function here is detection, verification, and early notification speed.
- Lead time from quake to my detection: ~16h (first run of the monitor). With
  scheduled hourly runs this drops to <=1h.
