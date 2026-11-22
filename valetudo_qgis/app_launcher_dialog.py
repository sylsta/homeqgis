"""The "Create the app launcher…" dialog (see app_launcher.py)."""

import os

from qgis.PyQt.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                 QLineEdit, QVBoxLayout)
from qgis.core import QgsProject
from qgis.gui import QgsFileWidget

from . import app_launcher
from .i18n import tr
from .settings import load_settings


class AppLauncherDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("DomotiQGIS as an app"))
        layout = QVBoxLayout(self)
        intro = QLabel(tr(
            "Creates a launcher that starts QGIS like an app: in a profile of its own, with "
            "the robot project, the robot on the map and the DomotiQGIS panel, the other "
            "toolbars and panels hidden. Your usual QGIS is not changed."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.project = QgsFileWidget()
        self.project.setStorageMode(QgsFileWidget.StorageMode.GetFile)
        self.project.setFilter(tr("QGIS projects (*.qgz *.qgs)"))
        self.project.setFilePath(load_settings()["robot_project"]
                                 or QgsProject.instance().fileName())
        self.project.fileChanged.connect(self._check)
        form.addRow(tr("Robot project"), self.project)
        self.profile = QLineEdit(app_launcher.DEFAULT_PROFILE)
        self.profile.textChanged.connect(self._check)
        self.profile.setToolTip(tr("The QGIS profile of the app: its plugins and settings "
                                   "are kept apart from your usual QGIS."))
        form.addRow(tr("Profile"), self.profile)
        layout.addLayout(form)
        self.copy_settings = QCheckBox(tr("Copy the settings (servers, options, room groups)"))
        self.copy_secrets = QCheckBox(tr("Copy the tokens and passwords (QGIS's "
                                         "authentication database, if the profile has none)"))
        self.desktop = QCheckBox(tr("Shortcut on the desktop"))
        self.menu = QCheckBox(tr("Entry in the applications menu"))
        for box in (self.copy_settings, self.copy_secrets, self.desktop, self.menu):
            box.setChecked(True)
            layout.addWidget(box)
        note = QLabel(tr("Run this again after changing the settings here to copy them "
                         "again. In the app, Plugins › DomotiQGIS › App mode shows QGIS's "
                         "toolbars and panels again."))
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Create"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._check()

    def _check(self, *_):
        path, name = self.project.filePath().strip(), self.profile.text().strip()
        ok = bool(path) and os.path.isfile(path) and bool(name) \
            and not any(c in name for c in '/\\:*?"<>|')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self):
        return dict(profile=self.profile.text().strip(),
                    project=os.path.abspath(self.project.filePath().strip()),
                    copy_settings=self.copy_settings.isChecked(),
                    copy_secrets=self.copy_secrets.isChecked(),
                    desktop=self.desktop.isChecked(), menu=self.menu.isChecked())
