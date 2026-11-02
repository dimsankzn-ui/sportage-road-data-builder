"""Full drivable OSM topology and named settlements, independent of maxspeed."""
import math

HIGHWAYS = frozenset('motorway trunk primary secondary tertiary unclassified residential living_street service motorway_link trunk_link primary_link secondary_link tertiary_link road track'.split())
PLACES = frozenset('city town village hamlet isolated_dwelling locality farm allotments'.split())

def initialize(db):
    db.executescript('''
    CREATE TABLE network(id INTEGER PRIMARY KEY,way_id INTEGER NOT NULL,ordinal INTEGER NOT NULL,
      a_node INTEGER NOT NULL,b_node INTEGER NOT NULL,a_lat REAL NOT NULL,a_lon REAL NOT NULL,
      b_lat REAL NOT NULL,b_lon REAL NOT NULL,meters REAL NOT NULL,highway TEXT NOT NULL,name TEXT NOT NULL,
      UNIQUE(way_id,ordinal));
    CREATE VIRTUAL TABLE network_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);
    CREATE TABLE places(id INTEGER PRIMARY KEY,osm_key TEXT UNIQUE NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL,
      name TEXT NOT NULL,kind TEXT NOT NULL);
    CREATE VIRTUAL TABLE place_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);
    ''')

def drivable(tags):
    return tags.get('highway') in HIGHWAYS and tags.get('area') != 'yes' and tags.get('motor_vehicle',tags.get('vehicle',tags.get('access',''))) not in ('no','private')

def insert_way(db,way_id,tags,nodes):
    if not drivable(tags): return 0
    count=0
    for ordinal,(a,b) in enumerate(zip(nodes,nodes[1:])):
        an,alat,alon=a; bn,blat,blon=b
        meters=math.hypot((blat-alat)*111195,(blon-alon)*111195*math.cos(math.radians((alat+blat)/2)))
        if meters<=0: continue
        sid=db.execute('INSERT INTO network(way_id,ordinal,a_node,b_node,a_lat,a_lon,b_lat,b_lon,meters,highway,name) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
          (way_id,ordinal,an,bn,alat,alon,blat,blon,meters,tags['highway'],tags.get('name:ru') or tags.get('name',''))).lastrowid
        db.execute('INSERT INTO network_index VALUES(?,?,?,?,?)',(sid,min(alon,blon),max(alon,blon),min(alat,blat),max(alat,blat)))
        count+=1
    return count

def insert_place(db,key,lat,lon,tags):
    name=tags.get('name:ru') or tags.get('name','')
    if tags.get('place') not in PLACES or not name: return 0
    cursor=db.execute('INSERT OR IGNORE INTO places(osm_key,lat,lon,name,kind) VALUES(?,?,?,?,?)',(key,lat,lon,name,tags['place']))
    if not cursor.rowcount: return 0
    db.execute('INSERT INTO place_index VALUES(?,?,?,?,?)',(cursor.lastrowid,lon,lon,lat,lat))
    return 1
