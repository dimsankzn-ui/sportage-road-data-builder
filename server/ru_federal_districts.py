"""Authoritative build planning for Natural Earth RU admin1 ISO-3166-2 IDs.

These federal-district groups partition exactly the 83 currently recognized
Russian IDs in the bundled Natural Earth atlas. This is *not* an assertion
about the completeness of Natural Earth's disputed/changed boundaries.
"""
FEDERAL_DISTRICTS = {
    "central-fed-district": "RU-BEL RU-BRY RU-IVA RU-KLU RU-KOS RU-KRS RU-LIP RU-MOS RU-MOW RU-ORL RU-RYA RU-SMO RU-TAM RU-TUL RU-TVE RU-VLA RU-VOR RU-YAR".split(),
    "northwestern-fed-district": "RU-ARK RU-KO RU-KR RU-LEN RU-MUR RU-NEN RU-NGR RU-PSK RU-SPE RU-VLG RU-KGD".split(),
    "south-fed-district": "RU-AD RU-AST RU-KDA RU-KL RU-ROS RU-VGG".split(),
    "north-caucasus-fed-district": "RU-CE RU-DA RU-IN RU-KB RU-KC RU-SE RU-STA".split(),
    "volga-fed-district": "RU-BA RU-CU RU-KIR RU-ME RU-MO RU-NIZ RU-ORE RU-PER RU-PNZ RU-SAM RU-SAR RU-TA RU-UD RU-ULY".split(),
    "ural-fed-district": "RU-CHE RU-KGN RU-KHM RU-SVE RU-TYU RU-YAN".split(),
    "siberian-fed-district": "RU-AL RU-ALT RU-BU RU-IRK RU-KEM RU-KK RU-KYA RU-NVS RU-OMS RU-TOM RU-TY".split(),
    "far-eastern-fed-district": "RU-AMU RU-CHU RU-KAM RU-KHA RU-MAG RU-PRI RU-SA RU-SAK RU-YEV RU-ZAB".split(),
}

def verify(known):
    seen={}
    for district, ids in FEDERAL_DISTRICTS.items():
        for code in ids:
            if code in seen:
                raise ValueError(f"Duplicate {code}: {seen[code]}, {district}")
            seen[code]=district
    missing=set(known)-set(seen)
    unknown=set(seen)-set(known)
    if missing or unknown:
        raise ValueError(f"Natural Earth coverage mismatch: missing={sorted(missing)} extra={sorted(unknown)}")
    return seen

def plan(district):
    if district not in FEDERAL_DISTRICTS:
        raise ValueError("Unrecognized Geofabrik federal district")
    return FEDERAL_DISTRICTS[district]

if __name__=="__main__":
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district",required=True,choices=FEDERAL_DISTRICTS.keys())
    parser.add_argument("--atlas",help="Optional roads_catalog.json to verify complete coverage")
    a=parser.parse_args()
    if a.atlas:
        data=json.loads(Path(a.atlas).read_text("utf8"))
        verify({r["id"] for r in data["regions"] if r.get("countryCode")=="RU"})
    print(",".join(plan(a.district)))
