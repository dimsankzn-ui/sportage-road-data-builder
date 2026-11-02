"""Self-hosted OSM speed limits for RU/BY. Runtime uses only SQLite (no Overpass).
Build on an operator workstation with "pip install osmium"; upload SQLite to VPS.
Road geometries © OpenStreetMap contributors, ODbL.
"""
import argparse
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

ROADS = frozenset(("motorway","trunk","primary","secondary","tertiary","unclassified",
    "residential","living_street","service","motorway_link","trunk_link",
    "primary_link","secondary_link","tertiary_link"))
UNSUPPORTED = frozenset(("maxspeed:conditional","maxspeed:lanes","maxspeed:variable",
    "maxspeed:forward:conditional","maxspeed:backward:conditional",
    "maxspeed:forward:lanes","maxspeed:backward:lanes",
    "maxspeed:forward:variable","maxspeed:backward:variable"))
LIMIT_RE = re.compile(r"^(\d{1,3})(?:\s*(km/h|kmh|kph|mph))?$", re.I)
MAX_JSON_BYTES = 245000   # Existing Android CaptureTransport response limit: 262144 bytes.

def numeric_limit(raw):
    match = LIMIT_RE.fullmatch(raw.strip()) if isinstance(raw, str) else None
    if not match:
        return 0
    value = int(match.group(1))
    if (match.group(2) or "").lower() == "mph":
        value = round(value * 1.609344)
    return value if 5 <= value <= 160 else 0

def limits_from_tags(tags):
    """Explicit numeric OSM limits only; never derive a speed from road class."""
    if tags.get("highway") not in ROADS or any(tag in tags for tag in UNSUPPORTED):
        return None
    general = numeric_limit(tags.get("maxspeed", ""))
    forward = numeric_limit(tags.get("maxspeed:forward", ""))
    backward = numeric_limit(tags.get("maxspeed:backward", ""))
    if "maxspeed" in tags and not general:
        return None
    if ("maxspeed:forward" in tags and not forward or
            "maxspeed:backward" in tags and not backward):
        return None
    if not (general or forward or backward):
        return None
    oneway = (-1 if tags.get("oneway") == "-1" else
              1 if tags.get("oneway") in ("yes", "1", "true")
              or tags.get("junction") == "roundabout" else 0)
    return general, forward, backward, oneway

def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS roads(
            id INTEGER PRIMARY KEY, country TEXT NOT NULL,
            osm_id INTEGER NOT NULL, highway TEXT NOT NULL,
            general_kmh INTEGER NOT NULL, forward_kmh INTEGER NOT NULL,
            backward_kmh INTEGER NOT NULL, oneway INTEGER NOT NULL,
            UNIQUE(country,osm_id)
        );
        CREATE TABLE IF NOT EXISTS segments(
            id INTEGER PRIMARY KEY, road_id INTEGER NOT NULL,
            a_lat REAL NOT NULL,a_lon REAL NOT NULL,b_lat REAL NOT NULL,b_lon REAL NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS segment_index USING rtree(
            id,min_lon,max_lon,min_lat,max_lat
        );
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    """)

def insert_way(db, country, osm_id, tags, coords):
    """Insert a tagged OSM way, split into indexed two-point segments."""
    if country not in ("RU", "BY"):
        raise ValueError("Invalid country")
    limits = limits_from_tags(tags)
    if limits is None or len(coords) < 2:
        return 0
    points = [(float(lat), float(lon)) for lat,lon in coords]
    if any(not (math.isfinite(a) and math.isfinite(b)
                and -90 <= a <= 90 and -180 <= b <= 180) for a,b in points):
        return 0
    cursor = db.execute("INSERT OR IGNORE INTO roads(country,osm_id,highway,general_kmh,"
        "forward_kmh,backward_kmh,oneway) VALUES(?,?,?,?,?,?,?)",
        (country,osm_id,tags["highway"],*limits))
    if cursor.rowcount == 0:
        return 0
    road_id = cursor.lastrowid
    count = 0
    for (alat,alon),(blat,blon) in zip(points,points[1:]):
        if (alat,alon) == (blat,blon):
            continue
        sid = db.execute("INSERT INTO segments(road_id,a_lat,a_lon,b_lat,b_lon)"
            " VALUES(?,?,?,?,?)",(road_id,alat,alon,blat,blon)).lastrowid
        db.execute("INSERT INTO segment_index VALUES(?,?,?,?,?)",
            (sid,min(alon,blon),max(alon,blon),min(alat,blat),max(alat,blat)))
        count += 1
    if not count:
        db.execute("DELETE FROM roads WHERE id=?", (road_id,))
    return count

def distance_m(lat, lon, alat, alon, blat, blon):
    scale = math.cos(math.radians(lat)) * 111195
    ax,ay = (alon-lon)*scale,(alat-lat)*111195
    bx,by = (blon-lon)*scale,(blat-lat)*111195
    dx,dy = bx-ax,by-ay
    denom = dx*dx+dy*dy
    t = 0 if denom == 0 else min(1,max(0,-(ax*dx+ay*dy)/denom))
    return math.hypot(ax+t*dx,ay+t*dy)
