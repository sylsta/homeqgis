"""The plugin's folder, for its data (forms, icons, translations, manual, metadata)."""

import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_PACKAGE = os.path.basename(PLUGIN_DIR)   # its folder name, as QGIS knows it
