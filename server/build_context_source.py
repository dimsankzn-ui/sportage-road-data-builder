"""Build one complete regional source, used by the daily agent's CI worker."""
import argparse,json,urllib.request
from pathlib import Path
from build_drive_atlas import build
from ru_federal_districts import FEDERAL_DISTRICTS
from extend_ru_admin_boundaries import extend

from road_sources import SOURCES

def main():
    p=argparse.ArgumentParser();p.add_argument('source',choices=SOURCES);p.add_argument('--out',default='context-output');a=p.parse_args()
    root=Path(a.out);root.mkdir(parents=True,exist_ok=True)
    import subprocess
    def download(url,path):
        subprocess.run(['curl','-fLsS','--retry','3','--max-time','5400',url,'-o',str(path)],check=True)
    download('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson',root/'natural.geojson')
    download('https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/UKR/ADM1/geoBoundaries-UKR-ADM1.geojson',root/'extra.geojson')
    subprocess.run(['python3','server/extend_ru_admin_boundaries.py','--natural-earth',str(root/'natural.geojson'),'--geo-boundaries-ukr',str(root/'extra.geojson'),'--output',str(root/'admin.geojson')],check=True)
    src=SOURCES[a.source]
    download(src['state'],root/'source-state.txt')
    from road_publications import parse_publication
    seq,stamp=parse_publication((root/'source-state.txt').read_bytes())
    download(src['url'],root/'source.osm.pbf')
    catalog=build(root/'admin.geojson',root/'source.osm.pbf',root,('BY',) if a.source=='belarus' else ('RU',),src['ids'])
    catalog['publications']={a.source:{'sequence':seq,'publishedAt':stamp}}
    for r in catalog['regions']:
        if 'db' in r:
            r['db']['packageName']='map-'+r['id']+'-'+r['db']['contentSha256'][:20]+'.zip'
            r['db']['sourceKey']=a.source
    (root/'roads_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf8')
if __name__=='__main__':main()
