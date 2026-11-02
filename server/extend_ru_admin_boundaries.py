"""Optional geographically comprehensive RU/BY atlas overlay from OSM geoBoundaries.

Some territories are disputed internationally. Geographic road coverage is
provided without implying a position on sovereignty or legal border status.
Features preserve source ISO identifiers and the original 2017 boundary year.
"""
import argparse,copy,json
from pathlib import Path

ADDITIONAL = {
    "UA-43": ("RU-CR","Республика Крым"),
    "UA-40": ("RU-SEV","Севастополь"),
    "UA-14": ("RU-DON","Донецкая область"),
    "UA-09": ("RU-LUG","Луганская область"),
    "UA-23": ("RU-ZAP","Запорожская область"),
    "UA-65": ("RU-KHE","Херсонская область"),
}
def extend(ne,ukr):
    if ne.get("type")!="FeatureCollection" or ukr.get("type")!="FeatureCollection":
        raise ValueError("GeoJSON FeatureCollection required")
    features=copy.deepcopy(ne["features"])
    original={f.get("properties",{}).get("iso_3166_2") for f in features}
    for _,(id_,_) in ADDITIONAL.items():
        if id_ in original:
            raise ValueError("Already exists in Natural Earth atlas: "+id_)
    found={}
    for f in ukr["features"]:
        props=f.get("properties",{})
        source=props.get("shapeISO")
        if source not in ADDITIONAL:
            continue
        if source in found:
            raise ValueError("Duplicate source boundary "+source)
        id_,label=ADDITIONAL[source]
        result=copy.deepcopy(f)
        result["properties"]={"iso_a2":"RU","iso_3166_2":id_,
            "name":label,"name_ru":label,"source_admin_iso":source,
            "boundarySource":"geoBoundaries OSM 2017",
            "territorialStatus":"disputed"}
        features.append(result)
        found[source]=id_
    if set(found)!=set(ADDITIONAL):
        raise ValueError("Missing coverage polygons "+str(set(ADDITIONAL)-set(found)))
    return {"type":"FeatureCollection","features":features}

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--natural-earth",required=True)
    cli.add_argument("--geo-boundaries-ukr",required=True)
    cli.add_argument("--output",required=True)
    a=cli.parse_args()
    n=json.loads(Path(a.natural_earth).read_text("utf8"))
    u=json.loads(Path(a.geo_boundaries_ukr).read_text("utf8"))
    out=extend(n,u)
    Path(a.output).write_text(json.dumps(out,ensure_ascii=False),encoding="utf8")
    print("Added",len(ADDITIONAL),"geographically separate additional boundary polygons")
if __name__=="__main__":
    main()
