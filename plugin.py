# SPDX-License-Identifier: GPL-2.0-or-later
import json
import math
from pathlib import Path
from pkgutil import get_data
from urllib.parse import quote

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCsException, QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsRectangle,
    QgsTask, QgsVectorLayer,
)

from .bases_locais import convert_archive
from .cartografia import EcoSafeCartografia

NAME = "EcoSafe Earth"
SITE = "https://ecosafegeotecnologias.com.br/earth"
WORLD_IMAGERY = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"


def read_catalog():
    data = json.loads(get_data(__package__, "catalogo.json"))
    satellite = {
        "id": "satelite", "name": "Satélite · Esri World Imagery",
        "group": "Mapa de fundo", "kind": "xyz", "coverage": "Mundo",
        "source": "Esri, Vantor, Earthstar Geographics e comunidade GIS",
        "year": "Varia conforme a cena", "url": WORLD_IMAGERY,
    }
    return {item["id"]: item for item in [satellite, *data["layers"]]}


def create_layer(entry, filename=None):
    uri = QgsDataSourceUri()
    name, kind = entry["name"], entry["kind"]
    if kind == "wms":
        for key, value in (
            ("url", entry["url"]), ("layers", entry["layer"]),
            ("styles", ""), ("format", "image/png"), ("crs", "EPSG:4326"),
        ):
            uri.setParam(key, value)
        return QgsRasterLayer(bytes(uri.encodedUri()).decode(), name, "wms")
    if kind == "xyz":
        for key, value in (
            ("type", "xyz"), ("url", entry["url"] + "/tile/{z}/{y}/{x}"),
            ("zmin", "0"), ("zmax", "18"),
        ):
            uri.setParam(key, value)
        return QgsRasterLayer(bytes(uri.encodedUri()).decode(), name, "wms")
    if kind == "arcgis":
        url = quote(entry["url"].rstrip("/") + "/" + entry["layer"], safe=":/%")
        uri.setParam("url", url)
        return QgsVectorLayer(uri.uri(False), name, "arcgisfeatureserver")
    return QgsVectorLayer(filename, name, "ogr")


class EcoSafeEarth:
    def __init__(self, iface):
        self.iface = iface
        self.catalog = read_catalog()
        self.cartography = EcoSafeCartografia(iface)
        self.dock = None
        self.conversions = set()

    def initGui(self):
        pixmap = QPixmap()
        pixmap.loadFromData(get_data(__package__, "icon.png"))
        icon = QIcon(pixmap)
        self.action = QAction(icon, NAME, self.iface.mainWindow())
        self.action.triggered.connect(self.open_panel)
        self.iface.addPluginToMenu(NAME, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        for task in self.conversions:
            task.cancel()
        self.conversions.clear()
        self.iface.removePluginMenu(NAME, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action.deleteLater()
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    @staticmethod
    def button(label, callback):
        widget = QPushButton(label)
        widget.clicked.connect(callback)
        return widget

    def open_panel(self):
        if self.dock is None:
            self.build_panel()
        self.dock.show()
        self.dock.raise_()

    def build_panel(self):
        self.dock = QDockWidget(NAME, self.iface.mainWindow())
        self.dock.setObjectName("EcoSafeEarthDock")
        body = QWidget(self.dock)
        layout = QVBoxLayout(body)

        search = QLineEdit()
        search.setPlaceholderText("Buscar camada ou fonte")
        search.textChanged.connect(self.filter_layers)
        layout.addWidget(search)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Camada e fonte"])
        groups = {}
        for entry in self.catalog.values():
            group_name = entry["group"]
            if group_name not in groups:
                groups[group_name] = QTreeWidgetItem(self.tree, [group_name])
            suffix = " (arquivo local)" if entry["kind"].startswith("local-") else ""
            item = QTreeWidgetItem(groups[group_name], [entry["name"] + suffix])
            item.setData(0, Qt.UserRole, entry["id"])
            item.setToolTip(0, "\n".join((entry["source"], entry["coverage"], entry["year"])))
        self.tree.expandAll()
        self.tree.itemDoubleClicked.connect(lambda item, column: self.add_layer())
        self.tree.currentItemChanged.connect(self.describe_layer)
        layout.addWidget(self.tree, 1)

        self.details = QLabel("Selecione uma camada para ver a fonte.")
        self.details.setTextFormat(Qt.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        layout.addWidget(self.button("Adicionar ao projeto", self.add_layer))

        tools = QHBoxLayout()
        tools.addWidget(self.button("Consultar", self.iface.actionIdentify().trigger))
        tools.addWidget(self.button("Medir distância", self.iface.actionMeasure().trigger))
        tools.addWidget(self.button("Medir área", self.iface.actionMeasureArea().trigger))
        layout.addLayout(tools)
        layout.addWidget(self.button("Ir para coordenadas", self.go_to_coordinates))
        layout.addWidget(self.button("Gerar carta de localização", self.cartography.run))
        layout.addWidget(self.button("Abrir EcoSafe Earth na web", lambda: QDesktopServices.openUrl(QUrl(SITE))))

        self.dock.setWidget(body)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

    def describe_layer(self, item, previous):
        entry = self.catalog.get(item.data(0, Qt.UserRole)) if item else None
        self.details.setText(
            f'{entry["source"]}\n{entry["coverage"]} · {entry["year"]}'
            if entry else "Selecione uma camada para ver a fonte."
        )

    def filter_layers(self, text):
        terms = text.casefold().split()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            any_visible = False
            for row in range(group.childCount()):
                item = group.child(row)
                entry = self.catalog[item.data(0, Qt.UserRole)]
                searchable = " ".join((item.text(0), entry["source"], entry["group"])).casefold()
                visible = all(term in searchable for term in terms)
                item.setHidden(not visible)
                any_visible |= visible
            group.setHidden(not any_visible)
            if terms and any_visible:
                group.setExpanded(True)

    def add_layer(self):
        item = self.tree.currentItem()
        entry = self.catalog.get(item.data(0, Qt.UserRole)) if item and not item.isHidden() else None
        if entry is None:
            return
        filename = None
        if entry["kind"].startswith("local-"):
            filename, _ = QFileDialog.getOpenFileName(
                self.dock, f'Selecionar vetor ou ZIP de atualização · {entry["name"]}', "",
                "Bases (*.gpkg *.shp *.geojson *.json *.zip)",
            )
            if not filename:
                return
            if Path(filename).suffix.lower() == ".zip":
                self.prepare_local_base(entry, filename)
                return
        self.load_layer(entry, filename)

    def prepare_local_base(self, entry, archive):
        proposed = Path(archive).with_name(entry["id"] + ".gpkg")
        filename, _ = QFileDialog.getSaveFileName(
            self.dock, "Salvar a base convertida", str(proposed), "GeoPackage (*.gpkg)",
            options=QFileDialog.DontConfirmOverwrite,
        )
        if not filename:
            return
        if not filename.lower().endswith(".gpkg"):
            filename += ".gpkg"
        filename = str(Path(filename).resolve())
        if any(task.output_path == filename for task in self.conversions):
            self.iface.messageBar().pushWarning(NAME, "Já existe uma conversão para esse arquivo.")
            return
        project = QgsProject.instance()
        if any(layer.source().split("|")[0] == filename for layer in project.mapLayers().values()):
            self.iface.messageBar().pushWarning(NAME, "Escolha outro nome. Esse arquivo está em uso no projeto.")
            return
        if Path(filename).exists() and QMessageBox.question(
            self.dock, NAME, "Substituir o GeoPackage existente?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        def finished(error, result=None):
            if task not in self.conversions:
                return
            self.conversions.discard(task)
            if error:
                self.iface.messageBar().pushWarning(NAME, str(error))
            elif result:
                self.load_layer(entry, result)

        task = QgsTask.fromFunction(
            f'Preparar {entry["name"]}', convert_archive, archive, entry["id"], filename,
            on_finished=finished,
        )
        task.output_path = filename
        self.conversions.add(task)
        QgsApplication.taskManager().addTask(task)

    def load_layer(self, entry, filename=None):
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if (layer.customProperty("ecosafeEarth/id") == entry["id"]
                    and layer.customProperty("ecosafeEarth/file", "") == (filename or "")):
                node = project.layerTreeRoot().findLayer(layer.id())
                if node:
                    node.setItemVisibilityCheckedParentRecursive(True)
                self.iface.setActiveLayer(layer)
                return

        self.iface.messageBar().pushMessage(NAME, f'Abrindo {entry["name"]}…', duration=3)
        layer = create_layer(entry, filename)
        if not layer.isValid():
            self.iface.messageBar().pushWarning(
                NAME, f'Não foi possível carregar {entry["name"]}. Confira a fonte e a conexão.'
            )
            return

        metadata = layer.metadata()
        metadata.setTitle(entry["name"])
        metadata.setAbstract(f'{entry["source"]}\n{entry["coverage"]}\n{entry["year"]}')
        metadata.setIdentifier(entry["url"])
        if entry["kind"] == "xyz":
            metadata.setRights([entry["source"]])
        layer.setMetadata(metadata)
        layer.setCustomProperty("ecosafeEarth/id", entry["id"])
        layer.setCustomProperty("ecosafeEarth/file", filename or "")
        root = project.layerTreeRoot()
        if entry["kind"] == "xyz":
            project.addMapLayer(layer, False)
            root.addLayer(layer)
        else:
            group = root.findGroup(NAME)
            if group is None:
                children = root.children()
                base_index = next(
                    (index for index, child in enumerate(children)
                     if hasattr(child, "layer") and child.layer()
                     and child.layer().customProperty("ecosafeEarth/id") == "satelite"),
                    len(children),
                )
                group = root.insertGroup(base_index, NAME)
            project.addMapLayer(layer, False)
            node = group.insertLayer(0, layer)
            node.setItemVisibilityCheckedParentRecursive(True)
        self.iface.setActiveLayer(layer)
        self.iface.messageBar().pushSuccess(NAME, f'{entry["name"]} adicionada ao projeto.')

    def go_to_coordinates(self):
        value, accepted = QInputDialog.getText(
            self.dock, "Ir para coordenadas",
            "Latitude; longitude em graus decimais (ex.: -6,497; -49,878)",
        )
        if not accepted:
            return
        try:
            latitude, longitude = (float(part.replace(",", ".")) for part in value.split(";"))
            if not (math.isfinite(latitude) and math.isfinite(longitude)
                    and -90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError
        except ValueError:
            self.iface.messageBar().pushWarning(NAME, "Informe latitude e longitude válidas, separadas por ponto e vírgula.")
            return
        canvas = self.iface.mapCanvas()
        project = QgsProject.instance()
        crs = canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), crs, project)
        try:
            target = transform.transform(longitude, latitude)
            if not (math.isfinite(target.x()) and math.isfinite(target.y())):
                raise ValueError
        except (QgsCsException, ValueError):
            self.iface.messageBar().pushWarning(NAME, "O SRC do mapa não permite localizar esse ponto.")
            return
        extent = canvas.extent()
        if extent.isEmpty():
            self.iface.messageBar().pushWarning(NAME, "Adicione uma camada ao mapa antes de navegar por coordenadas.")
            return
        half_width = extent.width() / 2
        half_height = extent.height() / 2
        canvas.setExtent(QgsRectangle(
            target.x() - half_width, target.y() - half_height,
            target.x() + half_width, target.y() + half_height,
        ))
        canvas.refresh()
