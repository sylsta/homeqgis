"""The plugin's page in QGIS Settings › Options (layout: ``ui/settings_page.ui``).

QGIS calls ``apply()`` when the Options dialog is closed with OK (or Apply);
Cancel saves nothing, like the other Options pages.
"""

import os

from qgis.PyQt.QtCore import QDateTime, QLocale, QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                                 QPushButton, QToolButton, QVBoxLayout, QWidget,
                                 QFileDialog, QListWidgetItem, QMessageBox,
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
    KEY_HISTORY, KEY_INTERVAL, KEY_LIVE_AT_START, KEY_NOTIFY_DOCK, KEY_RDP_COMMAND,
    KEY_FOLLOW_ROBOT, KEY_STRIP_DOTS, KEY_TAB_ORDER, KEY_TOOLBAR, KEY_VNC_COMMAND, PANEL_TABS, PLUGIN_NAME, TOOLBAR_CHOICES,
    WIFI_DEFAULTS, tab_order, toolbar_keys,
    active_robot_id, default_camera_url, load_settings, save_servers, set_secret,
)
from .ui_loader import load_ui

PAGE_NAME = "ValetudoOptionsPage"   # object name of the page (root of settings_page.ui)

UI_WIDGETS = (
    "interval", "live_at_start", "btn_room_groups",
    "camera_url", "ffmpeg", "camera_width", "notify_dock", "record_history",
    "servers_layout", "chk_advanced", "tabs",
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
        self._build_panel_tab()
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
        self.servers_editor.load_programs(cfg["vnc_command"], cfg["rdp_command"])
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
        self._fill_tab_order(tab_order())
        chosen = toolbar_keys()
        for key, box in self.toolbar_boxes.items():
            box.setChecked(key in chosen)
        self.chk_strip_dots.setChecked(cfg["strip_dots"])
        self.chk_follow_robot.setChecked(cfg["follow_robot"])
        for key, (_, kind) in WIFI_DEFAULTS.items():
            widget = getattr(self, key)
            if kind is bool:
                widget.setChecked(cfg[key])
            else:
                widget.setValue(cfg[key])

    # -- UI configuration tab: the panel's side tabs, the toolbar ----------------------

    def _build_panel_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>" + tr("Order of the robot's tabs") + "</b>"))
        row = QHBoxLayout()
        self.list_tabs = QListWidget()
        self.list_tabs.setIconSize(QSize(20, 20))
        self.list_tabs.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_tabs.setMaximumWidth(260)
        row.addWidget(self.list_tabs)
        buttons = QVBoxLayout()
        for text, tip, step in (("▲", tr("Move up"), -1), ("▼", tr("Move down"), 1)):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=step: self._move_tab(s))
            buttons.addWidget(button)
        buttons.addStretch(1)
        row.addLayout(buttons)
        row.addStretch(1)
        layout.addLayout(row)
        default = QPushButton(tr("Default order"))
        default.clicked.connect(lambda: self._fill_tab_order(list(PANEL_TABS)))
        layout.addWidget(default, 0, Qt.AlignmentFlag.AlignLeft)
        hint = QLabel(tr("Drag the tabs, or move the selected one with ▲ ▼: the side tabs of "
                         "the panel's Robot section follow this order from top to bottom "
                         "(applied with OK)."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        # The plugin's toolbar: which commands it shows
        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>" + tr("Toolbar") + "</b>"))
        labels = {"status_panel": tr("{name} panel").format(name=PLUGIN_NAME),
                  "live": tr("Show on map"), "start": tr("Clean everything"),
                  "home": tr("Dock"), "zone": tr("Clean a zone…"), "goto": tr("Go to…"),
                  "settings": tr("Settings…"), "pick_rooms": tr("Pick rooms on the map"),
                  "place_sensor": tr("Place a sensor on the map"),
                  "edit_restrictions": tr("Edit no-go zones and walls"),
                  "send_restrictions": tr("Send no-go zones and walls to robot…")}
        map_tools = ("pick_rooms", "place_sensor", "edit_restrictions", "send_restrictions")
        self.toolbar_boxes = {}
        grid = QGridLayout()
        for index, key in enumerate(TOOLBAR_CHOICES):
            box = QCheckBox(labels[key])
            box.setIcon(icon(APP_ICON if key == "status_panel" else key))
            if key in map_tools:
                box.setToolTip(tr("Shown in the toolbar while Show on map is on."))
            grid.addWidget(box, index % 7, index // 7)   # the map tools: right column
            self.toolbar_boxes[key] = box
        layout.addLayout(grid)
        self.chk_strip_dots = QCheckBox(tr("Servers as a coloured dot instead of an "
                                           "On the air / Off the air label"))
        self.chk_strip_dots.setToolTip(tr("Takes less room; hover the dot for the details."))
        self.chk_follow_robot = QCheckBox(tr("Keep the robot in view while Show on map is on"))
        self.chk_follow_robot.setToolTip(tr("Recentres the map when the robot nears the edge "
                                            "of the view. Off: the map stays where you put it."))
        note = QLabel(tr("The map tools (right column) appear while Show on map is on; the "
                         "advanced ones only with Advanced tools."))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>" + tr("Status strip") + "</b>"))
        layout.addWidget(self.chk_strip_dots)
        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>" + tr("Map") + "</b>"))
        layout.addWidget(self.chk_follow_robot)
        layout.addStretch(1)
        self.tabs.insertTab(self.tabs.count() - 2, page, tr("UI configuration"))

    def _fill_tab_order(self, order):
        labels = {"status": tr("Status"), "clean": tr("Clean"), "schedule": tr("Schedule"),
                  "history": tr("History"), "wifi": tr("Wi-Fi"), "camera": tr("Camera"),
                  "maintenance": tr("Maintenance"), "terminal": tr("Terminal")}
        self.list_tabs.clear()
        for key in order:
            item = QListWidgetItem(icon(f"tab_{key}"), labels.get(key, key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_tabs.addItem(item)

    def _tab_order_on_screen(self):
        return [self.list_tabs.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_tabs.count())]

    def _move_tab(self, step):
        row = self.list_tabs.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list_tabs.count():
            return
        item = self.list_tabs.takeItem(row)
        self.list_tabs.insertItem(target, item)
        self.list_tabs.setCurrentRow(target)

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
        vnc, rdp = editor.programs()
        s.setValue(KEY_VNC_COMMAND, vnc)
        s.setValue(KEY_RDP_COMMAND, rdp)
        s.setValue(KEY_INTERVAL, self.interval.value())
        s.setValue(KEY_LIVE_AT_START, self.live_at_start.isChecked())
        s.setValue(KEY_CAMERA_URL, self.camera_url.text().strip())
        s.setValue(KEY_FFMPEG, self.ffmpeg.text().strip())
        s.setValue(KEY_CAMERA_WIDTH, self.camera_width.value())
        s.setValue(KEY_NOTIFY_DOCK, self.notify_dock.isChecked())
        s.setValue(KEY_HISTORY, self.record_history.isChecked())
        s.setValue(KEY_ADVANCED, self.chk_advanced.isChecked())
        s.setValue(KEY_TAB_ORDER, ",".join(self._tab_order_on_screen()))
        s.setValue(KEY_TOOLBAR, ",".join(key for key, box in self.toolbar_boxes.items()
                                         if box.isChecked()))
        s.setValue(KEY_STRIP_DOTS, self.chk_strip_dots.isChecked())
        s.setValue(KEY_FOLLOW_ROBOT, self.chk_follow_robot.isChecked())
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
