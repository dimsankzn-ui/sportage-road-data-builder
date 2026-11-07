"""Self-hosted OSM speed limits for RU/BY. Runtime uses only SQLite (no Overpass).
Build on an operator workstation with "pip install osmium"; upload SQLite to VPS.
Road geometries © OpenStreetMap contributors, ODbL.
"""
import math
import re
import sqlite3

ROADS = frozenset(("motorway","trunk","primary","secondary","tertiary","unclassified",
    "residential","living_street","service","motorway_link","trunk_link",
    "primary_link","secondary_link","tertiary_link"))
UNSUPPORTED = frozenset(("maxspeed:conditional","maxspeed:lanes","maxspeed:variable",
    "maxspeed:forward:conditional","maxspeed:backward:conditional",
    "maxspeed:forward:lanes","maxspeed:backward:lanes",
    "maxspeed:forward:variable","maxspeed:backward:variable"))
LIMIT_RE = re.compile(r"^(\d{1,3})(?:\s*(km/h|kmh|kph|mph))?$", re.I)

def numeric_limit(raw):
    match = LIMIT_RE.fullmatch(raw.strip()) if isinstance(raw, str) else None
    if not match:
        return 0
    value = int(match.group(1))
    if (match.group(2) or "").lower() == "mph":
        value = round(value * 1.609344)
    return value if 5 <= value <= 160 else 0

RUSSIAN_ZONES = {"RU:urban": 60, "RU:rural": 90, "RU:motorway": 110, "RU:living_street": 20}

def limits_from_tags(tags, country=None):
    """Use numeric tags and explicitly mapped road zones, never place polygons."""
    if tags.get("highway") not in ROADS or any(tag in tags for tag in UNSUPPORTED):
        return None
    raw = tags.get("maxspeed", "")
    general = numeric_limit(raw)
    if country == "RU" and not general:
        if raw:
            general = RUSSIAN_ZONES.get(raw, 0)
        else:
            zones = {tags[key] for key in ("maxspeed:type", "source:maxspeed", "zone:maxspeed", "zone:traffic")
                     if tags.get(key) in RUSSIAN_ZONES}
            if len(zones) == 1:
                general = RUSSIAN_ZONES[zones.pop()]
    forward = numeric_limit(tags.get("maxspeed:forward", ""))
    backward = numeric_limit(tags.get("maxspeed:backward", ""))
    if "maxspeed" in tags and not general:
        return None
    if country == "RU":
        forward = forward or RUSSIAN_ZONES.get(tags.get("maxspeed:forward"), 0)
        backward = backward or RUSSIAN_ZONES.get(tags.get("maxspeed:backward"), 0)
    if ("maxspeed:forward" in tags and not forward or
            "maxspeed:backward" in tags and not backward):
        return None
    if not (general or forward or backward):
        return None
    return general, forward, backward, oneway_direction(tags)

def oneway_direction(tags):
    return (-1 if tags.get("oneway") == "-1" else
              1 if tags.get("oneway") in ("yes", "1", "true")
              or tags.get("junction") == "roundabout" else 0)

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

def section_signs(tags):
    """Independent flags for each direction on a way. Only unconditional tags."""
    overtaking = [0, 0]
    if not any(key.startswith("overtaking") and
               ("conditional" in key or "lanes" in key) for key in tags):
        overtaking = [int(tags.get("overtaking:" + side, tags.get("overtaking")) == "no")
                      for side in ("forward", "backward")]

    def parking(side):
        keys = ("parking:" + side, "parking:both", "parking:lane:" + side, "parking:lane:both",
                "parking:condition:" + side, "parking:condition:both")
        if any(key.startswith(k + ":") and ("conditional" in key or ":time" in key)
               for key in tags for k in keys):
            return 0
        values = (tags.get(key) for key in tuple(key + ":restriction" for key in keys) + keys)
        return next(({"no_stopping": 2, "no_parking": 4}.get(value, 0) for value in values
                     if value is not None), 0)

    # The left and right of an OSM way are relative to its mapped direction.
    left, right = parking("left"), parking("right")
    priority = [64 * (tags.get("priority_road:" + direction, tags.get("priority_road")) == "designated"
                      and not any(k.startswith("priority_road") and "conditional" in k for k in tags))
                for direction in ("forward", "backward")]
    return overtaking[0] | left << 3 | right | priority[0], overtaking[1] | right << 3 | left | priority[1]

def point_signs(tags):
    direction = tags.get("traffic_sign:direction", tags.get("direction"))
    flags = {"RU:3.21": 128, "RU:2.4": 256, "RU:2.5": 512}
    return tuple(flags.get(tags.get("traffic_sign:" + side, tags.get("traffic_sign") if side == direction else ""), 0)
                 for side in ("forward", "backward"))

def insert_way(db, country, osm_id, tags, coords, *, section=False):
    """Insert a tagged OSM way, split into indexed two-point segments."""
    if country not in ("RU", "BY"):
        raise ValueError("Invalid country")
    limits = limits_from_tags(tags, country if section else None)
    signs = section_signs(tags) if section else (0, 0)
    if (limits is None and not any(signs)) or len(coords) < 2:
        return 0
    points = [(float(lat), float(lon)) for lat,lon in coords]
    if any(not (math.isfinite(a) and math.isfinite(b)
                and -90 <= a <= 90 and -180 <= b <= 180) for a,b in points):
        return 0
    cursor = db.execute("INSERT OR IGNORE INTO roads(country,osm_id,highway,general_kmh,"
        "forward_kmh,backward_kmh,oneway) VALUES(?,?,?,?,?,?,?)",
        (country,osm_id,tags["highway"],*(limits or (0, 0, 0, oneway_direction(tags)))))
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
    elif section and any(signs):
        db.execute("INSERT INTO road_signs VALUES(?,?,?)", (road_id, *signs))
    return count

def distance_m(lat, lon, alat, alon, blat, blon):
    scale = math.cos(math.radians(lat)) * 111195
    ax,ay = (alon-lon)*scale,(alat-lat)*111195
    bx,by = (blon-lon)*scale,(blat-lat)*111195
    dx,dy = bx-ax,by-ay
    denom = dx*dx+dy*dy
    t = 0 if denom == 0 else min(1,max(0,-(ax*dx+ay*dy)/denom))
    return math.hypot(ax+t*dx,ay+t*dy)
