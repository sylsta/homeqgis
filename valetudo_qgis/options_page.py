"""The plugin's page in QGIS Settings › Options (layout: ``ui/settings_page.ui``).

QGIS calls ``apply()`` when the Options dialog is closed with OK (or Apply);
Cancel saves nothing, like the other Options pages.
"""

import os

from qgis.PyQt.QtCore import QDateTime, QLocale, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QFileDialog, QListWidgetItem, QMessageBox,
                                 QStackedWidget)
from qgis.core import QgsSettings
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory

from . import config_backup, room_groups
from .about import AboutWidget
from .i18n import tr
from .icons import APP_ICON, icon
from .servers import KEY_ACTIVE_ROBOT
from .servers_editor import ServersEditor
from .settings import (
    DEFAULT_CAMERA_PORT, KEY_ADVANCED, KEY_CAMERA_URL, KEY_CAMERA_WIDTH, KEY_FFMPEG,
    KEY_HISTORY, KEY_INTERVAL, KEY_LIVE_AT_START, KEY_NOTIFY_DOCK, PLUGIN_NAME, WIFI_DEFAULTS,
    active_robot_id, default_camera_url, load_settings, save_servers, set_secret,
)
from .ui_loader import load_ui

PAGE_NAME = "ValetudoOptionsPage"   # object name of the page (root of settings_page.ui)

UI_WIDGETS = (
    "interval", "live_at_start", "btn_room_groups",
    "camera_url", "ffmpeg", "camera_width", "notify_dock", "record_history",
    "servers_layout", "chk_advanced",
    "backup_folder", "btn_backup_browse", "btn_backup_open", "list_backups",
    "chk_backup_secrets", "btn_backup_save", "btn_backup_load", "btn_backup_load_file",
    "btn_backup_reset", "about_layout",
    "lbl_backup_status",
    *WIFI_DEFAULTS,   # one widget per Wi-Fi survey setting, named like the setting
)


class ValetudoOptionsPage(QgsOptionsPageWidget):
    def __init__(self, parent=None, on_applied=None):
        super().__init__(parent)
        load_ui("settings_page.ui", self, UI_WIDGETS)
        self.setObjectName(PAGE_NAME)
        self._on_applied = on_applied
        self.servers_editor = ServersEditor(self)
        self.servers_layout.addWidget(self.servers_editor)
        self._fill()
        self._setup_backup()
        self.about_layout.addWidget(AboutWidget(self))
        self.btn_room_groups.setToolTip(room_groups.file_path())
        self.btn_room_groups.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(room_groups.ensure_file())))

    def _fill(self):
        """Every field from the stored settings (also after loading a backup)."""
        s = QgsSettings()
        cfg = load_settings()
        self.servers_editor.load(cfg["servers"], active_robot_id())
        self.interval.setValue(cfg["interval_s"])
        self.live_at_start.setChecked(cfg["live_at_start"])
        # Empty camera URL = derived from the robot address.
        self.camera_url.setText(s.value(KEY_CAMERA_URL, "", type=str))
        self.camera_url.setPlaceholderText(
            default_camera_url(cfg["url"]) or f"tcp://192.168.1.23:{DEFAULT_CAMERA_PORT}")
        self.ffmpeg.setText(cfg["ffmpeg"])
        self.camera_width.setValue(cfg["camera_width"])
        self.notify_dock.setChecked(cfg["notify_dock"])
        self.record_history.setChecked(cfg["history"])
        self.chk_advanced.setChecked(cfg["advanced_tools"])
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            if kind is bool:
                widget.setChecked(cfg[key])
            else:
                widget.setValue(cfg[key])

    # -- Backup tab -----------------------------------------------------------------

    def _setup_backup(self):
        self.backup_folder.setText(config_backup.folder())
        self.btn_backup_browse.clicked.connect(self._choose_backup_folder)
        self.btn_backup_open.clicked.connect(self._open_backup_folder)
        self.btn_backup_save.clicked.connect(self._save_backup)
        self.btn_backup_load.clicked.connect(self._load_selected_backup)
        self.btn_backup_load_file.clicked.connect(self._load_backup_file)
        self.btn_backup_reset.clicked.connect(self._reset_config)
        self.list_backups.itemDoubleClicked.connect(lambda _item: self._load_selected_backup())
        self.list_backups.currentRowChanged.connect(
            lambda row: self.btn_backup_load.setEnabled(row >= 0))
        self._list_backups()

    def _list_backups(self, select=None):
        self.list_backups.clear()
        for path, stamp in config_backup.backups(self.backup_folder.text()):
            item = QListWidgetItem(QLocale().toString(stamp, QLocale.FormatType.LongFormat))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list_backups.addItem(item)
            if path == select:
                self.list_backups.setCurrentItem(item)
        self.btn_backup_load.setEnabled(self.list_backups.currentRow() >= 0)
        if not self.list_backups.count():
            self.lbl_backup_status.setText(tr("No saved configuration in this folder yet."))

    def _choose_backup_folder(self, *_):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Folder of the saved configurations"), self.backup_folder.text())
        if folder:
            self.backup_folder.setText(folder)
            QgsSettings().setValue(config_backup.KEY_BACKUP_DIR, folder)
            self.lbl_backup_status.setText("")
            self._list_backups()

    def _open_backup_folder(self, *_):
        folder = self.backup_folder.text()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _save_backup(self, *_):
        """Apply the values on screen (as OK does), then save them to a new file."""
        self.apply()
        try:
            path = config_backup.save(self.backup_folder.text(),
                                      self.chk_backup_secrets.isChecked())
        except OSError as exc:
            self.lbl_backup_status.setText("✗ " + tr("Not saved: {error}").format(error=exc))
            return
        self.lbl_backup_status.setText("✓ " + tr("Saved: {file}").format(
            file=os.path.basename(path)))
        self._list_backups(select=path)

    def _load_selected_backup(self, *_):
        item = self.list_backups.currentItem()
        if item is not None:
            self._load_backup(item.data(Qt.ItemDataRole.UserRole))

    def _load_backup_file(self, *_):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Load a configuration"), self.backup_folder.text(),
            tr("Configurations (*.json)"))
        if path:
            self._load_backup(path)

    def _load_backup(self, path):
        try:
            data = config_backup.read(path)
        except (OSError, ValueError) as exc:
            self.lbl_backup_status.setText("✗ " + tr("Cannot load {file}: {error}").format(
                file=os.path.basename(path), error=exc))
            return
        saved = QDateTime.fromString(data.get("saved", ""), Qt.DateFormat.ISODate)
        when = QLocale().toString(saved, QLocale.FormatType.LongFormat) if saved.isValid() else "?"
        answer = QMessageBox.question(
            self, tr("Load a configuration"),
            tr("Replace the current configuration by the one saved on {date}? "
               "This takes effect at once.").format(date=when)
            + ("\n\n" + tr("It includes tokens and passwords.") if data.get("secrets") else ""))
        if answer != QMessageBox.StandardButton.Yes:
            return
        before = load_settings()
        count, secrets = config_backup.apply(data)
        self._fill()
        self.lbl_backup_status.setText("✓ " + tr(
            "Loaded: {count} settings, {secrets} tokens or passwords, from {date}.").format(
                count=count, secrets=secrets, date=when))
        if self._on_applied is not None and (secrets or load_settings() != before):
            self._on_applied()

    def _reset_config(self, *_):
        """Save a backup of the stored configuration, then go back to the defaults."""
        secrets = self.chk_backup_secrets.isChecked()
        answer = QMessageBox.question(
            self, tr("Reset config"),
            tr("Go back to the default settings? The current configuration is saved "
               "first, so that you can load it back.")
            + "\n\n" + (tr("Tokens and passwords are included in that backup.") if secrets
                         else tr("Tokens and passwords are not included in that backup: "
                                 "tick the box above to keep them.")))
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path = config_backup.save(self.backup_folder.text(), secrets)
        except OSError as exc:
            self.lbl_backup_status.setText("✗ " + tr("Not reset: the backup failed ({error}).")
                                           .format(error=exc))
            return
        before = load_settings()
        config_backup.reset()
        self._fill()
        self._list_backups(select=path)
        self.lbl_backup_status.setText("✓ " + tr(
            "Reset to the defaults. The previous configuration is in {file}.").format(
                file=os.path.basename(path)))
        if self._on_applied is not None and load_settings() != before:
            self._on_applied()

    def apply(self):
        before = load_settings()
        s = QgsSettings()
        editor = self.servers_editor
        save_servers(editor.servers())
        s.setValue(KEY_ACTIVE_ROBOT, editor.active_robot())
        s.setValue(KEY_INTERVAL, self.interval.value())
        s.setValue(KEY_LIVE_AT_START, self.live_at_start.isChecked())
        s.setValue(KEY_CAMERA_URL, self.camera_url.text().strip())
        s.setValue(KEY_FFMPEG, self.ffmpeg.text().strip())
        s.setValue(KEY_CAMERA_WIDTH, self.camera_width.value())
        s.setValue(KEY_NOTIFY_DOCK, self.notify_dock.isChecked())
        s.setValue(KEY_HISTORY, self.record_history.isChecked())
        s.setValue(KEY_ADVANCED, self.chk_advanced.isChecked())
        secrets_changed, failed = False, False
        for key, value in editor.secret_changes():
            if set_secret(key, value):
                secrets_changed = True
            else:
                failed = True
        if failed:
            from qgis.utils import iface
            iface.messageBar().pushWarning(PLUGIN_NAME, tr(
                "A token or password was not saved: the QGIS master password "
                "is needed to store it encrypted."))
        else:
            editor.secrets_saved()
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            s.setValue(f"valetudo/{key}", widget.isChecked() if kind is bool else widget.value())
        # OK is pressed for any Options page: only react when ours changed something.
        if self._on_applied is not None and (secrets_changed or load_settings() != before):
            self._on_applied()


class ValetudoOptionsFactory(QgsOptionsWidgetFactory):
    """Registered with iface.registerOptionsWidgetFactory() while the plugin is loaded."""

    def __init__(self, on_applied=None):
        super().__init__(PLUGIN_NAME, icon(APP_ICON))
        self._on_applied = on_applied
        self._page = None

    def icon(self):
        return icon(APP_ICON)

    def createWidget(self, parent):
        self._page = ValetudoOptionsPage(parent, self._on_applied)
        return self._page

    def select_page(self):
        """Show our page in the open Options dialog.

        Backs up showOptionsDialog(currentPage=…), which matches the object
        name of the stacked pages: QGIS may wrap a plugin page in a scroll area.
        """
        widget = self._page
        try:
            for _ in range(10):   # the dialog's stack is a few levels up at most
                if widget is None:
                    return
                parent = widget.parentWidget()
                if isinstance(parent, QStackedWidget):
                    parent.setCurrentWidget(widget)
                    return
                widget = parent
        except RuntimeError:   # the page of a previous, closed dialog
            pass
