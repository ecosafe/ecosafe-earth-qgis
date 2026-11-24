# EcoSafe Earth for QGIS

Browse Brazilian geospatial layers, add them to a QGIS project, and export a
location map as PDF. The catalogue includes IBGE boundaries, roads and
biomes, ArcGIS services, satellite imagery and entries for local datasets
from Pará.

## Installation and use

In QGIS 3.28 or later in the 3.x series, open **Plugins → Manage and Install
Plugins → Install from ZIP** and select the installation archive. Open
**EcoSafe Earth** from the Plugins menu. See [instruções em português](LEIA-ME.txt)
for the local data import and PDF workflow.

Online layers depend on their source providers. Local data are supplied by
the user. Converting an EcoSafe Earth data archive requires the GDAL Python
bindings (osgeo), normally included in the QGIS distribution.

## License

The plugin source code is distributed under GPL-2.0-or-later. See
[LICENSE](LICENSE) for the GNU General Public License version 2. Third-party
map services and geospatial data remain subject to their own terms.

The EcoSafe logo is a brand asset of EcoSafe Geotecnologias.
