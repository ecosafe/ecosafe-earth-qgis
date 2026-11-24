# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def convert_archive(task, archive_path, layer_id, output_path):
    from osgeo import gdal

    output = Path(output_path)
    with TemporaryDirectory(dir=output.parent) as directory, ZipFile(archive_path) as archive:
        source = Path(directory) / "recorte.geojson"
        staged = Path(directory) / "base.gpkg"
        if layer_id == "snci-pa":
            source.write_bytes(archive.read("snci-pa.geojson"))
        else:
            car = layer_id == "car-pa"
            prefix = "car-pa-semas/" if car else f"dados-locais/{layer_id}/originais/"
            members = [name for name in archive.namelist()
                       if name.startswith(prefix) and name.endswith(".json")
                       and not name.endswith("/index.json")]
            if not members:
                raise ValueError("A base escolhida não foi encontrada nesse ZIP.")
            with source.open("w", encoding="utf-8") as stream:
                stream.write('{"type":"FeatureCollection","features":[')
                separator = ""
                seen_ids = set()
                for position, name in enumerate(members):
                    if task.isCanceled():
                        return None
                    data = json.loads(archive.read(name))
                    features = data["features"] if car else [data]
                    for feature in features:
                        if car:
                            feature_id = feature["id"]
                            if feature_id in seen_ids:
                                continue
                            seen_ids.add(feature_id)
                        stream.write(separator)
                        json.dump(feature, stream, ensure_ascii=False, separators=(",", ":"))
                        separator = ","
                    task.setProgress(50 * (position + 1) / len(members))
                stream.write("]}")

        def progress(fraction, message, data):
            task.setProgress(50 + 50 * fraction)
            return int(not task.isCanceled())

        options = gdal.VectorTranslateOptions(
            format="GPKG", layerName=layer_id.replace("-", "_"),
            reproject=False, dstSRS=None if layer_id == "snci-pa" else "EPSG:4674",
            callback=progress,
        )
        result = gdal.VectorTranslate(str(staged), str(source), options=options)
        if task.isCanceled():
            return None
        if result is None:
            raise RuntimeError("O GDAL não conseguiu converter a base para GeoPackage.")
        result = None
        staged.replace(output)
        return str(output)
