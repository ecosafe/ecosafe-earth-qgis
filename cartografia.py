# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
from tempfile import TemporaryDirectory

from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton,
)
from qgis.core import (
    Qgis, QgsBasicNumericFormat, QgsCoordinateTransform,
    QgsCsException, QgsFeature,
    QgsFillSymbol, QgsLayoutExporter,
    QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemPage, QgsLayoutItemPicture,
    QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutRenderContext, QgsLayoutSize,
    QgsPrintLayout,
    QgsProject, QgsRectangle, QgsVectorLayer, QgsWkbTypes,
)

NAME = "EcoSafe Earth"


def add_label(layout, text, x, y, width, height, size, bold=False):
    label = QgsLayoutItemLabel(layout)
    font = QFont("Times New Roman", size)
    font.setBold(bold)
    label.setFont(font)
    label.setFontColor(QColor("#173743"))
    label.setMargin(0)
    label.setText(text)
    layout.addLayoutItem(label)
    label.attemptMove(QgsLayoutPoint(x, y))
    label.attemptResize(QgsLayoutSize(width, height))
    return label


def export_map(project, layer, feature, visible_layers, fields, output):
    geometry = feature.geometry()
    if geometry.isEmpty():
        raise ValueError("O polígono selecionado está sem geometria.")
    crs = project.crs()
    if not crs.isValid() or not layer.crs().isValid():
        raise ValueError("Defina um SRC válido para o projeto e para a camada.")
    transform = QgsCoordinateTransform(layer.crs(), crs, project)
    if geometry.transform(transform) != 0:
        raise ValueError("Não foi possível transformar o polígono para o SRC do projeto.")
    extent = geometry.boundingBox()
    if extent.isEmpty():
        raise ValueError("A geometria selecionada não possui uma extensão utilizável.")
    original_long_side = max(extent.width(), extent.height())
    margin = original_long_side * 0.35
    extent = QgsRectangle(
        extent.xMinimum() - margin, extent.yMinimum() - margin,
        extent.xMaximum() + margin, extent.yMaximum() + margin,
    )

    highlight = QgsVectorLayer(
        QgsWkbTypes.displayString(geometry.wkbType()), "Área selecionada", "memory"
    )
    if not highlight.isValid():
        raise ValueError("O tipo de geometria selecionado não pôde ser destacado.")
    highlight.setCrs(crs)
    selected = QgsFeature()
    selected.setGeometry(geometry)
    added, _ = highlight.dataProvider().addFeatures([selected])
    if not added:
        raise ValueError("Não foi possível preparar o destaque do polígono.")
    highlight.updateExtents()
    highlight.renderer().setSymbol(QgsFillSymbol.createSimple({
        "color": "0,150,136,40", "outline_color": "0,100,89,255",
        "outline_width": "0.7",
    }))

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName("Carta de localização | EcoSafe")
    layout.pageCollection().pages()[0].setPageSize(
        "A4", QgsLayoutItemPage.Landscape
    )
    layout.renderContext().setDpi(300)
    layout.renderContext().setFlag(QgsLayoutRenderContext.FlagDrawSelection, False)

    map_item = QgsLayoutItemMap(layout)
    layout.addLayoutItem(map_item)
    map_item.attemptMove(QgsLayoutPoint(10, 34))
    map_item.attemptResize(QgsLayoutSize(277, 140))
    map_item.setCrs(crs)
    map_item.setLayers([highlight] + visible_layers)
    map_item.setKeepLayerSet(True)
    map_item.setFrameEnabled(True)
    map_item.zoomToExtent(extent)
    layout.setReferenceMap(map_item)

    add_label(layout, "ECOSAFE GEOTECNOLOGIAS", 10, 8, 210, 6, 11, True)
    add_label(layout, "Carta de localização", 10, 15, 210, 12, 24, True)
    if fields["logo"]:
        picture = QgsLayoutItemPicture(layout)
        layout.addLayoutItem(picture)
        picture.attemptMove(QgsLayoutPoint(246, 7))
        picture.attemptResize(QgsLayoutSize(41, 22))
        picture.setPicturePath(fields["logo"])
    legend = add_label(layout, "Área selecionada", 10, 178, 43, 7, 11, True)
    legend.setBackgroundEnabled(True)
    legend.setBackgroundColor(QColor("#c3e7df"))
    crs_name = crs.authid() or crs.description()
    add_label(layout, f"SRC: {crs_name}", 59, 178, 150, 7, 10)

    scale = QgsLayoutItemScaleBar(layout)
    scale.setStyle("Numeric")
    scale.setLinkedMap(map_item)
    number_format = QgsBasicNumericFormat()
    number_format.setNumberDecimalPlaces(0)
    number_format.setShowThousandsSeparator(False)
    scale.setNumericFormat(number_format)
    layout.addLayoutItem(scale)
    scale.attemptMove(QgsLayoutPoint(237, 178))

    client = fields["cliente"] or "—"
    city = fields["municipio"] or "—"
    add_label(layout, f"Cliente: {client}   |   Município: {city}", 10, 186, 277, 9, 11)
    source = fields["fontes"] or "Camadas visíveis do projeto QGIS"
    add_label(layout, f"Fontes: {source}", 10, 196, 277, 9, 10)

    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 300
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    output = Path(output)
    with TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "carta.pdf"
        result = QgsLayoutExporter(layout).exportToPdf(str(staged), settings)
        if result != QgsLayoutExporter.Success:
            raise RuntimeError(f"O QGIS não conseguiu exportar a carta (código {result}).")
        staged.replace(output)


class EcoSafeCartografia:
    def __init__(self, iface):
        self.iface = iface

    def run(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            QMessageBox.information(self.iface.mainWindow(), NAME, "Ative uma camada de polígonos.")
            return
        if layer.selectedFeatureCount() != 1:
            QMessageBox.information(self.iface.mainWindow(), NAME, "Selecione exatamente um polígono.")
            return
        feature = next(layer.getSelectedFeatures())
        project = QgsProject.instance()
        visible = self.iface.mapCanvas().layers()

        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle(NAME)
        dialog.setMinimumWidth(470)
        form = QFormLayout(dialog)
        inputs = {}
        for key, label, limit in (
            ("cliente", "Cliente", 60),
            ("municipio", "Município / UF", 60),
            ("fontes", "Fontes cartográficas", 150),
        ):
            field = QLineEdit(dialog)
            field.setMaxLength(limit)
            form.addRow(label, field)
            inputs[key] = field

        logo = QLineEdit(dialog)
        logo.setReadOnly(True)
        logo.setPlaceholderText("Opcional")
        browse = QPushButton("Escolher…", dialog)
        clear = QPushButton("Limpar", dialog)

        def choose_logo():
            path, _ = QFileDialog.getOpenFileName(
                dialog, "Escolher logotipo", "", "Imagens (*.png *.jpg *.jpeg *.svg)"
            )
            if path:
                logo.setText(path)

        browse.clicked.connect(choose_logo)
        clear.clicked.connect(logo.clear)
        logo_row = QHBoxLayout()
        logo_row.addWidget(logo)
        logo_row.addWidget(browse)
        logo_row.addWidget(clear)
        form.addRow("Logotipo", logo_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Gerar PDF…")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if not dialog.exec():
            return
        fields = {key: field.text().strip() for key, field in inputs.items()}
        fields["logo"] = logo.text()
        output, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(), "Salvar carta de localização",
            "Carta_de_Localizacao.pdf", "PDF (*.pdf)",
            options=QFileDialog.DontConfirmOverwrite,
        )
        if not output:
            return
        if not output.lower().endswith(".pdf"):
            output += ".pdf"
        if Path(output).exists() and QMessageBox.question(
            self.iface.mainWindow(), NAME, "Já existe um PDF com esse nome. Substituir?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            export_map(project, layer, feature, visible, fields, output)
        except (ValueError, OSError, RuntimeError, QgsCsException) as error:
            QMessageBox.warning(self.iface.mainWindow(), NAME, str(error))
            return
        self.iface.messageBar().pushSuccess(NAME, f"PDF salvo em {output}")
