# Sportage road data builder

Builds road topology, explicit numeric speed limits and all named settlements from openly published OpenStreetMap extracts. Covers 96 geographic RU/BY regional zones. Geographic coverage of disputed territories implies no position on sovereignty.

This repository contains only the public geographic processor. It contains no Android application, GPS journeys, Google credentials, server credentials, personal documents or private repository history.

Standard GitHub Linux runners build changed sources on owner-server dispatch. Each region is an independent short-lived artifact. The owner's separate server validates SHA-256, SQLite integrity, region identity and row counts before publishing immutable regional packages to private Google Drive. The catalog changes only after every required package is available. No Google credentials enter this repository or its workflow.

Sources and attribution:
- © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), database [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
- [Geofabrik official extracts](https://download.geofabrik.de/) and daily replication states.
- [Natural Earth Admin-1](https://www.naturalearthdata.com/), public domain.
- Additional geographic boundaries: geoBoundaries gbOpen/OSM, 2017 source boundaries, provenance retained in catalogs.

Regional data artifacts are OSM-derived databases under ODbL. They are temporary build results; no private Google Drive files are exposed.
