#!/usr/bin/env python3
"""Build a fully offline RU/BY administrative atlas and per-region OSM road DBs.

Runs on a build computer / GitHub Actions, never on the owner's 1 GiB VPS.
Source admin polygons: Natural Earth Admin-1; source roads: Geofabrik OSM PBF.
All output artifacts are public OSM/Natural Earth derived data (no GPS history).
"""
import argparse
import gzip
import hashlib
import json
import math
import re
import sqlite3
import time
from pathlib import Path
from shapely.geometry import shape, LineString
from shapely.prepared import prep
from shapely.strtree import STRtree
import road_limits
import road_context

ID_RE = re.compile(r"^(RU|BY)-[A-Z0-9]{1,12}$")

def digest(path):
    h = hashlib.sha256()
    with open(path,"rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def road_content_hash(path):
    """Independent of SQLite page layout, analyzer statistics, and build time."""
    h=hashlib.sha256()
    with sqlite3.connect(path) as db:
        for row in db.execute("""
            SELECT r.osm_id,r.highway,r.general_kmh,r.forward_kmh,
                r.backward_kmh,r.oneway,s.a_lat,s.a_lon,s.b_lat,s.b_lon
            FROM segments s JOIN roads r ON r.id=s.road_id
            ORDER BY r.osm_id,s.id
        """):
            h.update(json.dumps(row,separators=(",",":")).encode("ascii"))
            h.update(b"\\n")
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "road_signs" in tables:
            for row in db.execute("SELECT r.osm_id,s.forward,s.backward FROM road_signs s "
                                  "JOIN roads r ON r.id=s.road_id ORDER BY r.osm_id"):
                h.update(json.dumps(row,separators=(",",":")).encode("ascii"))
                h.update(b"\n")
        if "road_point_signs" in tables:
            for row in db.execute("SELECT * FROM road_point_signs ORDER BY node_id"):
                h.update(json.dumps(row,separators=(",",":")).encode("ascii"))
                h.update(b"\n")
        for table,order in (("network","way_id,ordinal"),("places","osm_key"),("settlements","osm_key")):
            if table in tables:
                for row in db.execute("SELECT * FROM "+table+" ORDER BY "+order):
                    h.update(json.dumps(row[1:],ensure_ascii=False,separators=(",",":")).encode("utf8"))
                    h.update(b"\n")
    return h.hexdigest()

def compact_coords(coords):
    if isinstance(coords,(tuple,list)):
        if coords and isinstance(coords[0],(int,float)):
            return [round(float(coords[0]),5),round(float(coords[1]),5)]
        return [compact_coords(x) for x in coords]
    raise ValueError("Bad GeoJSON coordinates")

def collect_regions(raw):
    src=json.loads(Path(raw).read_text(encoding="utf8"))
    regions={}
    for feat in src["features"]:
        props=feat.get("properties") or {}
        country=props.get("iso_a2","")
        id_=props.get("iso_3166_2","")
        if country not in ("RU","BY") or not isinstance(id_,str) or not ID_RE.fullmatch(id_):
            continue
        if id_ in regions:
            raise ValueError("Duplicate "+id_)
        geom=shape(feat["geometry"])
        if not geom.is_valid:
            geom=geom.buffer(0)
        if geom.is_empty:
            continue
        # Detailed source polygon for segment intersection and adjacency; simplify
        # only the copy shipped to the head unit, at ~100 m angular tolerance.
        display=geom.simplify(.0005,preserve_topology=True)
        # Natural Earth Admin-1 has occasionally mistranslated Russian region names.
        # ISO 3166-2 identifiers take priority over ambiguous provider labels.
        label_overrides={"RU-ALT":"Алтайский край"}
        record={"id":id_,"name":label_overrides.get(id_) or props.get("name_ru") or props.get("name") or id_,
                "countryCode":country,"bounds":[round(x,5) for x in geom.bounds],
                "geometry":{"type":display.geom_type,
                    "coordinates":compact_coords(display.__geo_interface__["coordinates"])},
                "neighbors":[]}
        for key in ("source_admin_iso","boundarySource","territorialStatus"):
            if key in props:record[key]=props[key]
        regions[id_]={"geom":geom,"prepared":prep(geom),"data":record}
    if not any(v["data"]["countryCode"]=="BY" for v in regions.values()) or not any(
            v["data"]["countryCode"]=="RU" for v in regions.values()):
        raise ValueError("Missing RU/BY admin boundaries in input")
    ids=sorted(regions)
    for i,aid in enumerate(ids):
        a=regions[aid]; ab=a["geom"].bounds
        for bid in ids[i+1:]:
            b=regions[bid]; bb=b["geom"].bounds
            if (ab[0]>bb[2]+.003 or bb[0]>ab[2]+.003 or
                    ab[1]>bb[3]+.003 or bb[1]>ab[3]+.003):
                continue
            if a["geom"].boundary.distance(b["geom"].boundary)<.003:
                a["data"]["neighbors"].append(bid)
                b["data"]["neighbors"].append(aid)
    return regions

def build(raw_geojson,source_pbf,out,countries=("BY",),region_ids=(),source_bundle=""):
    try:
        import osmium
    except ImportError as exc:
        raise RuntimeError("Install osmium on build machine") from exc
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    records=collect_regions(raw_geojson)
    active={key:value for key,value in records.items()
            if value["data"]["countryCode"] in countries and (not region_ids or key in region_ids)}
    if region_ids and set(region_ids)-set(active):
        raise ValueError("Unknown regional IDs: "+str(set(region_ids)-set(active)))
    active_ids=list(active)
    region_geoms=[active[k]["geom"] for k in active_ids]
    region_tree=STRtree(region_geoms)
    outputs={}
    for id_ in active:
        path=root/(id_+".sqlite3")
        if path.exists():
            path.unlink()
        db=sqlite3.connect(path)
        road_limits.initialize(db)
        road_context.initialize(db)
        db.execute("CREATE TABLE road_signs(road_id INTEGER PRIMARY KEY,forward INTEGER NOT NULL,backward INTEGER NOT NULL)")
        db.execute("CREATE TABLE road_point_signs(node_id INTEGER PRIMARY KEY,way_id INTEGER NOT NULL,forward INTEGER NOT NULL,backward INTEGER NOT NULL)")
        db.execute("BEGIN")
        outputs[id_]={"path":path,"db":db,"ways":0,"segments":0,"network":0,"places":0,"pointOwners":{}}
    class Importer(osmium.SimpleHandler):
        point_signs={}
        def area(self,area):
            tags={v.k:v.v for v in area.tags}
            if tags.get("place") not in road_context.PLACES or not (tags.get("name:ru") or tags.get("name")):return
            # Area-only settlements have no label node. Keep a real point inside
            # the polygon; the renderer coalesces duplicate node/area labels.
            try:
                from shapely import wkb
                geom=wkb.loads(bytes.fromhex(osmium.geom.WKBFactory().create_multipolygon(area)))
                point=geom.representative_point()
            except (ValueError,RuntimeError):return
            for index in region_tree.query(point):
                id_=active_ids[int(index)]
                if active[id_]["prepared"].covers(point):
                    outputs[id_]["places"]+=road_context.insert_place(outputs[id_]["db"],("w" if area.from_way() else "r")+str(area.orig_id()),point.y,point.x,tags)
            for index in region_tree.query(geom):
                id_=active_ids[int(index)]
                if active[id_]["prepared"].intersects(geom):road_context.insert_boundary(outputs[id_]["db"],("w" if area.from_way() else "r")+str(area.orig_id()),tags,geom)
        def node(self,node):
            tags={v.k:v.v for v in node.tags}
            if any(key.startswith("traffic_sign") for key in tags):
                signs=road_limits.point_signs(tags)
                if any(signs):self.point_signs[node.id]=signs
            if tags.get("place") not in road_context.PLACES: return
            from shapely.geometry import Point
            point=Point(node.location.lon,node.location.lat)
            for index in region_tree.query(point):
                id_=active_ids[int(index)]
                if active[id_]["prepared"].covers(point):
                    outputs[id_]["places"]+=road_context.insert_place(outputs[id_]["db"],"n"+str(node.id),node.location.lat,node.location.lon,tags)
        def way(self,way):
            tags={v.k:v.v for v in way.tags}
            if not road_context.drivable(tags):
                return
            try:
                nodes=[(n.ref,n.lat,n.lon) for n in way.nodes]
                points=[(lat,lon) for _,lat,lon in nodes]
            except (ValueError,RuntimeError):
                return
            if len(points)<2:
                return
            # Exact admin polygon intersection catches ways crossing a border
            # with both endpoints outside the region.
            line=LineString([(lon,lat) for lat,lon in points])
            if line.is_empty:
                return
            signed_nodes={ref for ref,_,_ in nodes if ref in self.point_signs}
            for region_index in region_tree.query(line):
                id_=active_ids[int(region_index)]
                r=active[id_]
                if not r["prepared"].intersects(line):
                    continue
                db=outputs[id_]["db"]
                owners=outputs[id_]["pointOwners"]
                for node_id in signed_nodes:
                    if owners.setdefault(node_id,way.id)!=way.id:owners[node_id]=0
                outputs[id_]["network"]+=road_context.insert_way(db,way.id,tags,nodes)
                count=road_limits.insert_way(db,r["data"]["countryCode"],way.id,tags,points,section=True)
                if count:
                    outputs[id_]["ways"]+=1
                    outputs[id_]["segments"]+=count
    try:
        importer=Importer()
        importer.apply_file(str(source_pbf),locations=True,idx="sparse_file_array,"+str(root/"locations.idx"))
        # Do not include wall clock time in SQLite content: unchanged roads
        # should produce the same checksums across future published snapshots.
        at="0"
        for id_,item in outputs.items():
            db=item["db"]
            db.execute("INSERT INTO metadata VALUES('network_version','1')")
            db.execute("INSERT INTO metadata VALUES('road_rules_version','1')")
            db.executemany("INSERT INTO road_point_signs VALUES(?,?,?,?)",
                           ((node,way,*importer.point_signs[node]) for node,way in item["pointOwners"].items() if way))
            signs=db.execute("SELECT COUNT(*) FROM road_signs").fetchone()[0]
            point_signs=db.execute("SELECT COUNT(*) FROM road_point_signs").fetchone()[0]
            db.execute("INSERT INTO metadata VALUES('region_id',?)",(id_,))
            db.execute("INSERT INTO metadata VALUES('generated_at',?)",(at,))
            db.commit()
            db.execute("ANALYZE");db.commit()
            if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                raise RuntimeError("SQLite integrity failure "+id_)
            db.close()
            path=item["path"]
            if item["network"]==0:
                path.unlink()
                continue
            metadata={"file":path.name,"bytes":path.stat().st_size,
                "sha256":digest(path),"contentSha256":road_content_hash(path),
                "ways":item["ways"],"segments":item["segments"],
                "networkVersion":1,"networkSegments":item["network"],"places":item["places"],
                "roadRulesVersion":1,"signWays":signs,"signPoints":point_signs}
            if source_bundle:
                if not re.fullmatch(r"ru-[a-z-]+-regions\.zip",source_bundle):
                    raise ValueError("Bad regional source bundle name")
                metadata["sourceBundle"]=source_bundle
            records[id_]["data"]["db"]=metadata
    finally:
        for item in outputs.values():
            try:item["db"].close()
            except Exception:pass
    catalog={"schema":1,"source":"osm-geofabrik-natural-earth",
             "attribution":"© OpenStreetMap contributors",
             "builtAt":int(time.time()),
             "regions":[records[key]["data"] for key in sorted(records)]}
    raw=json.dumps(catalog,ensure_ascii=False,separators=(",",":")).encode("utf8")
    (root/"roads_catalog.json").write_bytes(raw)
    with gzip.open(root/"roads_catalog.json.gz","wb",compresslevel=8) as out_f:
        out_f.write(raw)
    print(json.dumps({"count":len(catalog["regions"]),"built":[
        {"id":id_,"bytes":x["path"].stat().st_size,"segments":x["segments"]}
        for id_,x in outputs.items() if x["path"].exists()]},ensure_ascii=False))
    return catalog

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--admin1",required=True)
    cli.add_argument("--pbf",required=True)
    cli.add_argument("--out",required=True)
    cli.add_argument("--countries",default="BY")
    cli.add_argument("--region-ids",default="",help="Comma-separated subset; useful for individual Russian districts")
    cli.add_argument("--source-bundle",default="",help="Name of Geofabrik regional district ZIP in Google Drive")
    a=cli.parse_args()
    selected=tuple(x.strip() for x in a.countries.split(",") if x.strip())
    if not selected or set(selected)-{"RU","BY"}:
        cli.error("countries must be RU/BY")
    build(a.admin1,a.pbf,a.out,selected,tuple(x.strip() for x in a.region_ids.split(',') if x.strip()),a.source_bundle)

if __name__=="__main__":
    main()
