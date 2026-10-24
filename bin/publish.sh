#!/bin/bash
# Guardian publisher: sync latest content into the public repo, refresh Atom feed,
# commit+push only if changed. Idempotent; safe to run hourly.
set -u
SRC=/home/aiops/dev/guardian
PUB=/home/aiops/dev/guardian-publish
cd "$PUB" || exit 1

# 1. Sync content
cp "$SRC"/reports/briefing_*.md briefing/ 2>/dev/null
cp "$SRC"/research/*.md research/ 2>/dev/null
cp "$SRC"/research/incidents/*.md research/incidents/ 2>/dev/null
cp "$SRC"/monitors/collect.py "$SRC"/monitors/report.py monitors/ 2>/dev/null
latest=$(ls -t "$SRC"/data/snapshot_*.json 2>/dev/null | head -1)
[ -n "$latest" ] && cp "$latest" data/latest_snapshot.json

# 2. Regenerate Atom feed from daily briefings
python3 - << 'PY'
import glob, hashlib, os
from datetime import datetime, timezone

files = sorted(glob.glob("briefing/briefing_*.md"))
base = "https://kheper1970.github.io/guardian/"
# Stable <updated>: only bumps when the briefing set changes (avoids hourly noise commits)
import glob as _g, hashlib as _h
digest = _h.sha1("".join(open(f).read() for f in files[-14:]).encode()).hexdigest()[:10]
stamp_file = ".feed_stamp"
prev = open(stamp_file).read().strip() if os.path.exists(stamp_file) else ""
if prev == digest:
    # content unchanged: reuse existing feed (exit early; git will see no diff)
    import sys
    if os.path.exists("feed.xml"):
        sys.exit(0)
entries = []
for f in files[-14:]:
    day = os.path.basename(f)[9:19]
    body = open(f).read()
    h = hashlib.sha1(body.encode()).hexdigest()[:10]
    when = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    entries.append((when, h, f, day))
updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
open(stamp_file, "w").write(digest)
xml = ['<?xml version="1.0" encoding="utf-8"?>',
       '<feed xmlns="http://www.w3.org/2005/Atom">',
       '  <title>Guardian Global Risk Briefing</title>',
       f'  <id>{base}</id>',
       f'  <updated>{updated}</updated>',
       f'  <link href="{base}"/>',
       '  <author><name>Kheper Guardian</name></author>',
       '  <subtitle>Automated multi-source digest of public hazard feeds. Not an official warning channel.</subtitle>']
for when, h, f, day in reversed(entries):
    iso = when.strftime("%Y-%m-%dT00:00:00Z")
    xml += ['  <entry>',
            f'    <title>Briefing {day}</title>',
            f'    <id>{base}briefing/{day}</id>',
            f'    <updated>{iso}</updated>',
            f'    <link href="https://github.com/kheper1970/guardian/blob/main/briefing/briefing_{day}.md"/>',
            '  </entry>']
xml.append('</feed>')
open("feed.xml", "w").write("\n".join(xml) + "\n")
PY

# 3. Commit only if changed
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "Automated update $(date -u +%Y-%m-%dT%H:%MZ)" || exit 0
  git push -q origin main
  echo "$(date -u +%FT%TZ) published" >> "$SRC/data/publish.log"
else
  echo "$(date -u +%FT%TZ) no changes" >> "$SRC/data/publish.log"
fi
