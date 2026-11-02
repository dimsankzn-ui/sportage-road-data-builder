"""Official extracts watched by the daily publisher. No build dependencies."""
from ru_federal_districts import FEDERAL_DISTRICTS
SOURCES={k:{'url':f'https://download.geofabrik.de/russia/{k}-latest.osm.pbf','state':f'https://download.geofabrik.de/russia/{k}-updates/state.txt','ids':v} for k,v in FEDERAL_DISTRICTS.items()}
SOURCES.update({'belarus':{'url':'https://download.geofabrik.de/europe/belarus-latest.osm.pbf','state':'https://download.geofabrik.de/europe/belarus-updates/state.txt','ids':[]},
 'crimea':{'url':'https://download.geofabrik.de/russia/crimean-fed-district-latest.osm.pbf','state':'https://download.geofabrik.de/russia/crimean-fed-district-updates/state.txt','ids':['RU-CR','RU-SEV']},
 'east':{'url':'https://download.geofabrik.de/europe/ukraine-latest.osm.pbf','state':'https://download.geofabrik.de/europe/ukraine-updates/state.txt','ids':['RU-DON','RU-LUG','RU-ZAP','RU-KHE']}})
