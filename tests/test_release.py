"""Release metadata and QGIS runtime checks (runtime tests require QGIS)."""
import configparser
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GUIDE = 'https://geonod.se/integrationer#qgis-guide'


class MetadataTests(unittest.TestCase):
    def test_publication_metadata(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / 'geonod' / 'metadata.txt', encoding='utf-8')
        meta = config['general']
        self.assertEqual(meta['qgisMinimumVersion'], '3.28')
        self.assertIn('Swedish geodata', meta['description'])
        for text in ('EN:', 'SV:', 'GeoNode', 'GeoNod account', 'GeoNod-konto',
                     'webbläsaren', 'browser', GUIDE):
            self.assertIn(text, meta['about'])


try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from qgis.core import (QgsApplication, QgsFeature, QgsGeometry, QgsProject,
                           QgsVectorLayer, QgsWkbTypes, QgsVectorFileWriter)
    from qgis.PyQt.QtCore import Qt, QStandardPaths
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QSizePolicy
except ImportError:
    QgsApplication = None


@unittest.skipUnless(QgsApplication, 'QGIS Python bindings unavailable')
class QgisCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()

    def test_scoped_enums_are_available(self):
        self.assertEqual(QgsWkbTypes.geometryType(QgsWkbTypes.Type.Polygon), QgsWkbTypes.GeometryType.PolygonGeometry)
        self.assertNotEqual(QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
                            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        for group, member in ((Qt.ScrollBarPolicy, 'ScrollBarAlwaysOff'),
                              (Qt.AlignmentFlag, 'AlignCenter'), (Qt.AlignmentFlag, 'AlignTop'),
                              (Qt.ItemDataRole, 'UserRole'), (Qt.DockWidgetArea, 'RightDockWidgetArea'),
                              (QStandardPaths.StandardLocation, 'DocumentsLocation'),
                              (QSizePolicy.Policy, 'Expanding')):
            self.assertTrue(hasattr(group, member))

    def test_account_guidance_follows_connection_state(self):
        from geonod.dock_widget import GeoNodDockWidget
        panel = GeoNodDockWidget()
        self.assertFalse(panel.getting_started.isHidden())
        self.assertEqual(panel.getting_started.text(), 'Ny på GeoNod? Skapa ett konto på geonod.se. Klicka sedan på Anslut och godkänn anslutningen i webbläsaren.')
        panel.set_connected('Test', [])
        self.assertTrue(panel.getting_started.isHidden())
        panel.set_busy('Uppdaterar')
        panel.set_error('Ett fel uppstod')
        self.assertTrue(panel.getting_started.isHidden())
        panel.set_disconnected()
        self.assertFalse(panel.getting_started.isHidden())

    def test_help_opens_qgis_guide(self):
        from geonod.geonod_plugin import GeoNodPlugin
        with patch.object(QDesktopServices, 'openUrl') as open_url:
            GeoNodPlugin.open_help(GeoNodPlugin.__new__(GeoNodPlugin))
        self.assertEqual(open_url.call_args.args[0].toString(), GUIDE)

    def test_capture_polygon_and_write_both_package_modes(self):
        from geonod.aoi import capture_selected_polygon
        from geonod.delivery import DeliverySource, _persistent_reprojected_vector_layer

        layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'source', 'memory')
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt('POLYGON((0 0, 1 0, 1 1, 0 0))'))
        self.assertTrue(layer.dataProvider().addFeatures([feature])[0])
        layer.selectAll()
        class Iface:
            def activeLayer(self):
                return layer
        polygon, name, _ = capture_selected_polygon(Iface())
        self.assertEqual(polygon['type'], 'Polygon')
        self.assertEqual(name, 'source')

        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'display.gpkg'
            source = DeliverySource(package, 'vector', 'source')
            # Keep the real writer, but avoid a cached OGR reader locking the file on Windows.
            with patch('qgis.core.QgsVectorLayer', return_value=layer):
                for name, overwrite_file in [('first', True), ('second', False)]:
                    _persistent_reprojected_vector_layer(
                        layer, source, layer.crs(), QgsProject.instance(), package, name, overwrite_file)
            with closing(sqlite3.connect(package)) as connection:
                names = {row[0] for row in connection.execute('SELECT table_name FROM gpkg_contents')}
            self.assertEqual(names, {'first', 'second'})


if __name__ == '__main__':
    unittest.main()
