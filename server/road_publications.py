"""Monitor only *published* OSM source versions; never fetch roads here.

A lightweight conditional state.txt check is unavoidable without a publisher webhook.
Runs only on the off-VPS data builder or GitHub Actions. It never touches a private server, TEYES, or Google Drive. No PBF/OSC downloads occur.
"""
import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://download.geofabrik.de/"
DISTRICTS = (
    "central-fed-district", "crimean-fed-district", "far-eastern-fed-district",
    "north-caucasus-fed-district", "northwestern-fed-district",
    "siberian-fed-district", "south-fed-district", "ural-fed-district",
    "volga-fed-district",
)
FEEDS = {"BY": BASE + "europe/belarus-updates/state.txt"}
FEEDS.update({f"RU-{slug}": BASE+f"russia/{slug}-updates/state.txt"
              for slug in DISTRICTS})
SEQ = re.compile(r"(?m)^sequenceNumber=(\d+)\s*$")
TIMESTAMP = re.compile(r"(?m)^timestamp=([^\r\n]+)$")
MAX_STATE = 4096

def parse_publication(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if not isinstance(data, str) or len(data) > MAX_STATE:
        raise ValueError("Invalid publication state")
    number = SEQ.search(data)
    timestamp = TIMESTAMP.search(data)
    if not number or not timestamp:
        raise ValueError("Missing replication sequence/timestamp")
    # Geofabrik/Osmosis escapes colons as \: in state.txt
    stamp = timestamp.group(1).replace("\\:", ":")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp):
        raise ValueError("Invalid replication timestamp")
    return int(number.group(1)), stamp

def fetch_state(url, etag=None, last_modified=None, opener=None):
    if url not in FEEDS.values():
        raise ValueError("Untrusted publication feed")
    headers = {"User-Agent": "SportageOS-owner-road-publication/1.0"}
    if etag and "\n" not in etag and "\r" not in etag:
        headers["If-None-Match"] = etag
    if last_modified and "\n" not in last_modified and "\r" not in last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    try:
        with (opener or urllib.request.urlopen)(request, timeout=12) as response:
            if response.status == 304:
                return None
            if response.status != 200:
                raise OSError(f"Unexpected HTTP {response.status}")
            body = response.read(MAX_STATE+1)
            seq, stamp = parse_publication(body)
            return {"sequence": seq, "publishedAt": stamp,
                    "etag": response.headers.get("ETag"),
                    "lastModified": response.headers.get("Last-Modified")}
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None
        raise

def atomic_json(path, data):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=dest.parent,
                                     prefix="."+dest.name+".", delete=False) as f:
        tmp = Path(f.name)
        json.dump(data, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

def check_once(state_file, fetch=fetch_state, feeds=None, clock=None):
    """Compare sequence numbers, record new releases, not download map data.

    First check establishes baseline; newer revisions create pending events.
    A failed check never advances revision or silently marks changes applied.
    """
    now = int(clock() if clock else time.time())
    target = Path(state_file)
    state = json.loads(target.read_text("utf-8")) if target.exists() else {
        "feeds": {}, "pending": []}
    current = state.setdefault("feeds", {})
    pending = state.setdefault("pending", [])
    events,errors = [],{}
    for key,url in (feeds or FEEDS).items():
        previous = current.get(key, {})
        try:
            fresh = fetch(url, previous.get("etag"), previous.get("lastModified"))
            if fresh is None:
                current.setdefault(key, {})["lastCheckedAt"] = now
                continue
            old = previous.get("sequence")
            seq = fresh["sequence"]
            if old is not None and seq > old:
                event = {"feed": key,"fromSequence": old,"toSequence": seq,
                         "publishedAt": fresh["publishedAt"],"detectedAt": now}
                # Debounce repeated checks and never lose an unprocessed release:
                # coalesce by feed, preserving oldest unprocessed revision.
                item = next((v for v in pending if v["feed"] == key), None)
                if item:
                    item["toSequence"] = seq
                    item["publishedAt"] = fresh["publishedAt"]
                else:
                    pending.append(event.copy())
                events.append(event)
            if old is None or seq >= old:
                current[key] = {**fresh,"lastCheckedAt": now}
            else:
                # Reject rollback or outdated CDN cache responses.
                current[key]["lastCheckedAt"] = now
        except (OSError, ValueError, UnicodeError, TimeoutError) as exc:
            errors[key] = type(exc).__name__
    atomic_json(state_file, state)
    return {"published": events, "errors": errors, "pending": len(pending),
            "checkedFeeds": len(feeds or FEEDS)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True,
                        help="Small JSON checkpoint on builder, not on driving device")
    parser.add_argument("--once", action="store_true", required=True,
                        help="A single check, invoked by a system timer (e.g. every 12h)")
    args = parser.parse_args()
    print(json.dumps(check_once(args.state),ensure_ascii=False))

if __name__ == "__main__":
    main()
