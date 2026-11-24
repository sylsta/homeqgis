"""Dockable status panel: robot state, settings, statistics, consumables...

The panel refreshes itself while it is visible (every 5 s while the robot is
working, every 30 s otherwise), independently of live map tracking. Sections
the robot does not support stay hidden.
"""

import html
import time

from qgis.PyQt.QtCore import QEvent, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QTabWidget,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsSettings
from qgis.gui import QgsDockWidget

from ..core.i18n import tr
from ..core.icons import APP_ICON, LOGO, icon
from ..core.manual import open_manual
from ..core.settings import KEY_ADVANCED, load_settings, tab_order
from ..core.ui_loader import load_ui, set_row_visible as _set_row_visible
from ..history.tab import HistoryTab
from ..home.tab import HomeTab
from ..servers.remote_desktop import RemoteDesktop
from ..valetudo.box import ValetudoBox
from ..valetudo.robot_settings import RobotSettingsBox
from .camera_tab import CameraMixin
from .clean_tab import CleanMixin
from .common import (
    ACTIVE_STATES,
    IDLE_INTERVAL_MS,
    KEY_ONCE_TIMERS,
    dock_labels,
    flag_labels,
    format_area_cm2,
    format_seconds,
    label_or_raw,
    state_labels,
)
from .robot_state import RobotStateMixin
from .schedule_tab import ScheduleMixin
from .servers_section import ServersMixin
from .terminal_tab import TerminalMixin
from .widgets import badge_icon
from .wifi_tab import WifiMixin

KEY_TAB = "valetudo/panel_tab"
KEY_TOP_TAB = "valetudo/panel_section"   # robot, home or servers
TOP_TABS = ("robot", "home", "servers")
SERVER_TABS = ("status", "terminal")     # side tabs of the Servers section
KEY_COMPACT = "valetudo/panel_compact"       # compact mode: strip and big button only

# Layout: ui/status_panel.ui (Qt Designer). The code fills it at run time and
# relies on these object names.
UI_WIDGETS = (
    # strip, details, action bar
    "strip", "strip_layout", "lbl_logo", "lbl_badge", "bar_battery", "lbl_wifi_strip", "lbl_job",
    "btn_warning", "sep_servers", "btn_menu",
    "lbl_details_logo", "lbl_badge_details", "bar_battery_details", "details", "header_layout", "lbl_connection",
    "btn_robot_web", "btn_robot_ssh",
    "lbl_robot", "lbl_robot_info", "action_layout", "btn_primary",
    "lbl_error", "lbl_feedback", "tabs",
    # Clean
    "tab_clean", "rooms", "box_settings", "settings_form", "combo_operation_mode",
    "combo_water_usage", "combo_fan_speed", "clean_grid", "btn_rooms", "chk_goto_quiet",
    "spin_passes",
    # Schedule
    "tab_schedule", "week_layout", "timers", "btn_timer_new", "btn_timer_edit",
    "btn_timer_delete", "btn_timer_run", "btn_tonight", "lbl_timers_note",
    # Wi-Fi
    "tab_wifi", "lbl_wifi_now", "sparkline_layout", "spin_wifi_good", "spin_wifi_fair",
    "spin_wifi_bad", "wifi_qgis_grid", "lbl_robot_recorder", "wifi_robot_grid",
    "btn_pi_latest", "btn_pi_full", "lbl_pi_thumb",
    # Camera
    "tab_camera", "camera_layout", "camera_light", "btn_camera_full",
    # Maintenance (robot, consumables, dock station, statistics, boot, events)
    "tab_maintenance", "box_consumables", "consumables_form", "box_dock", "dock_form", "dock_grid",
    "box_current", "lbl_cur_time", "lbl_cur_area", "box_total", "lbl_tot_count",
    "lbl_tot_time", "lbl_tot_area",
    # Terminal
    "tab_terminal", "btn_term_close", "btn_term_console",
    "btn_term_log",
    "terminal_stack",
    "tab_console", "lbl_console_status", "btn_console_connect", "btn_console_clear",
    "txt_console", "lbl_console_prompt", "edit_console", "btn_console_run", "btn_console_stop",
    "tab_log", "lbl_log_status", "chk_log_follow", "btn_log_clear", "txt_log",
    "box_status", "status_form", "lbl_state", "lbl_dock", "lbl_attachments",
    "lbl_position", "system_grid", "txt_boot", "list_events",
    "lbl_features",
)

# Collapsible sections -> key of their remembered open/closed state.
SECTIONS = {
    "box_settings": "settings", "box_wifi_live": "wifi_live", "box_wifi_legend": "wifi_legend",
    "box_wifi_qgis": "wifi_qgis", "box_wifi_robot": "wifi_robot", "box_wifi_pi": "wifi_pi",
    "box_consumables": "consumables", "box_dock": "dock", "box_current": "current",
    "box_total": "totals", "box_status": "status",
    "box_boot": "boot", "box_events": "events", "box_features": "features",
}
STATE_COLORS = {
    "cleaning": "#1565c0", "moving": "#1565c0", "manual_control": "#1565c0",
    "returning": "#ef6c00", "paused": "#f9a825", "docked": "#2e7d32",
    "idle": "#757575", "error": "#c62828",
}
DOCK_TASKS = ("cleaning", "washing", "drying", "emptying", "pause", "error")


class ValetudoPanel(CleanMixin, WifiMixin, CameraMixin, TerminalMixin,
                    ScheduleMixin, ServersMixin, RobotStateMixin,
                    QgsDockWidget):
    clientRequested = pyqtSignal()   # the panel was shown but no client exists yet
    splitRequested = pyqtSignal(str, str)   # room id, room name: draw the cut on the map
    segmentsChanged = pyqtSignal(list)      # [(room id, name)] known on the robot
    piMapRequested = pyqtSignal(bool)       # Wi-Fi tab: load the Pi's map (True: full map)
    summaryChanged = pyqtSignal(str)        # one-line status (HTML) for the map overlay
    jobStarted = pyqtSignal()               # the robot leaves its dock for a job
    advancedChanged = pyqtSignal(bool)      # the ⋮ menu's "Advanced tools" was toggled

    def __init__(self, parent=None):
        super().__init__(parent)   # title and object name come from the .ui
        self.client = None
        self.capabilities = None
        self._last_ok = None        # time.monotonic() of the last successful request
        self._last_ok_clock = ""
        self._reachable = None
        self._robot_text = self._version_text = ""
        self._wifi_html, self._wifi_tip = "", ""   # Wi-Fi signal in the header
        self._robot_ip, self._host = "", {}        # third header line
        self._last_map = 0.0   # time.monotonic() of the last map received

        self._timer = QTimer(self)
        self._timer.setInterval(IDLE_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(1000)
        self._age_timer.timeout.connect(self._update_header)

        self._build_ui()
        self.visibilityChanged.connect(self._on_visibility)
        self._show_disconnected()

    # -- UI construction -------------------------------------------------------

    def _build_ui(self):
        load_ui("status_panel.ui", self, UI_WIDGETS)
        self.setObjectName("ValetudoStatusPanel")   # QGIS restores the dock by this name
        self._tab_titles = {}   # tab key -> (title label, title row): filled with the side tabs
        theme = QgsApplication.getThemeIcon

        # -- status strip: click it for the Status tab ---------------------------------
        self.lbl_logo.setPixmap(icon(LOGO).pixmap(18, 18))
        self.btn_menu.setIcon(icon("menu"))
        self.menu = QMenu(self)
        self.btn_menu.setMenu(self.menu)
        self.btn_warning.setIcon(theme("/mIconWarning.svg"))
        self.btn_warning.setVisible(False)
        self.btn_warning.clicked.connect(self._on_warning_clicked)
        self._problems = {}          # key -> (text, tab key): shown by the ⚠ button
        self.lbl_job.setVisible(False)
        self.lbl_wifi_strip.setVisible(False)   # the Wi-Fi is in the strip's tooltip
        self.strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.strip.installEventFilter(self)
        # 📷 the Camera tab in one click, with the robot (then 🗺 Show on map, see
        # bind_actions), before the servers
        self.btn_strip_camera = QToolButton()
        self.btn_strip_camera.setIcon(icon("tab_camera"))
        self.btn_strip_camera.setAutoRaise(True)
        self.btn_strip_camera.setToolTip(tr("Camera"))
        self.btn_strip_camera.clicked.connect(lambda _=False: self.show_tab("camera"))
        self.strip_layout.insertWidget(self.strip_layout.indexOf(self.sep_servers),
                                       self.btn_strip_camera)

        # -- Status tab: the robot's frame (from the .ui), then a frame per server of the
        # settings, built by _build_server_frames()
        self._server_entries = []   # see _build_server_frames
        self._available = {}       # server id -> {"web", "ssh", "rd", "wake"}: buttons it has
        self._ssh_passwords = {}    # server id -> SSH target its password was given for
        self._terminal_entries = []   # "Console / Log in QGIS": advanced tools
        self.btn_robot_web.setIcon(icon("web"))
        self.btn_robot_ssh.setIcon(icon("tab_terminal"))
        self.btn_robot_web.clicked.connect(lambda _=False: self.open_web("robot"))
        self.btn_robot_ssh.clicked.connect(lambda _=False: self.open_ssh("robot"))
        menu = QMenu(self.btn_robot_ssh)   # click: the system terminal; arrow: in QGIS
        menu.addAction(icon("tab_terminal"), tr("Terminal window"),
                       lambda: self.open_ssh("robot"))
        self._terminal_entries += [
            menu.addAction(tr("Console in QGIS"), lambda: self.open_terminal("robot", "console")),
            menu.addAction(tr("Log in QGIS"), lambda: self.open_terminal("robot", "log"))]
        self.btn_robot_ssh.setMenu(menu)
        self.btn_robot_ssh.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.remote_desktop = RemoteDesktop(self)   # 🖥 of the computers
        self.remote_desktop.failed.connect(self._on_remote_desktop_failed)
        self.sep_servers.setVisible(False)   # shown with the strip's servers
        self.lbl_details_logo.setPixmap(icon(LOGO).pixmap(20, 20))
        self._set_badge(None)
        self.lbl_error.setVisible(False)

        # -- the big button: Start / Pause / Resume, after the robot's state ------------
        self._state = None
        self._flag = None
        self._dock_value = None     # DockStatusStateAttribute
        self._battery_flag = None   # charging, charged, discharging
        self.btn_primary.clicked.connect(self._on_primary)
        self._update_primary()

        self._build_clean()

        self._build_wifi()

        self._build_camera()

        self._build_terminal()

        self._build_schedule()

        # -- Sections remember whether they are open, under our own keys -----------------
        for name, key in SECTIONS.items():
            self._remember_section(getattr(self, name), key)

        # -- History: the robot's recorded outings (after the Schedule tab) -------------
        self.tab_history = QWidget()
        self.tab_history.setObjectName("tab_history")
        QVBoxLayout(self.tab_history).setContentsMargins(4, 0, 4, 4)
        self.history_tab = HistoryTab(self.tab_history)
        self.tab_history.layout().addWidget(self.history_tab)
        self.tabs.insertTab(self.tabs.indexOf(self.tab_schedule) + 1, self.tab_history,
                            tr("History"))

        # -- Side tabs: icons, their titles as tooltips; each page starts with its title
        self._tab_keys = [self.tabs.widget(i).objectName().removeprefix("tab_")
                          for i in range(self.tabs.count())]
        self._tab_icons = {}
        for i, key in enumerate(self._tab_keys):
            self._tab_icons[key] = icon(f"tab_{key}")
            title = self.tabs.tabText(i)
            self.tabs.setTabToolTip(i, title)
            self.tabs.setTabText(i, "")
            self.tabs.setTabIcon(i, self._tab_icons[key])
            self._tab_titles[key] = self._add_page_title(self.tabs.widget(i),
                                                         self._tab_icons[key], title)
        self._build_top_tabs()
        # Status: Refresh all, at the right of its title
        self.btn_refresh_all = QToolButton()
        self.btn_refresh_all.setText(tr("Refresh all"))
        self.btn_refresh_all.setToolTip(tr("Read every server again now (each one also "
                                           "refreshes by itself)"))
        self.btn_refresh_all.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_refresh_all.setAutoRaise(True)
        self.btn_refresh_all.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
        self.btn_refresh_all.clicked.connect(self.refresh_all)
        if "status" in self._tab_titles:
            self._tab_titles["status"][1].addWidget(self.btn_refresh_all)
        self._apply_tab_order()
        self._show_terminal_page()   # its title names the server
        self._set_tab_shown("terminal", False)   # see open_terminal
        last = QgsSettings().value(KEY_TAB, "clean", type=str)
        last = {"care": "maintenance", "system": "maintenance", "terminal": "status"}.get(last, last)
        if last in self._tab_keys:
            self.tabs.setCurrentIndex(self._tab_keys.index(last))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        top = QgsSettings().value(KEY_TOP_TAB, "robot", type=str)
        if last == "status" and top not in self._top_pages:   # (earlier versions)
            top = "servers"
        self.top_tabs.setCurrentWidget(self._top_pages.get(top, self._top_pages["robot"]))

        self._build_server_frames()
        for box in (self.box_settings, self.box_current, self.box_total, self.box_consumables,
                    self.box_dock):
            box.setVisible(False)   # shown once the robot reports them
        _set_row_visible(self.status_form, self.lbl_attachments, False)
        self._build_robot_sections()

    def _build_robot_sections(self):
        """Maintenance: the robot's own settings and Valetudo itself, after the robot."""
        self.box_robot_settings = RobotSettingsBox()
        self.box_valetudo = ValetudoBox()
        layout = self.box_status.parentWidget().layout()
        index = layout.indexOf(self.box_status)
        for offset, (box, key) in enumerate(((self.box_robot_settings, "robot_settings"),
                                             (self.box_valetudo, "valetudo"))):
            layout.insertWidget(index + 1 + offset, box)
            self._remember_section(box, key, open_default=False)
            box.collapsedStateChanged.connect(lambda *_: self._update_maintenance())
        self.box_valetudo.setVisible(False)   # once a robot is set

    def _update_maintenance(self):
        """The Maintenance tab in front: read the robot's settings and Valetudo's state."""
        if not self.isVisible() or self.client is None:
            return
        if self._page_shown(self._tab_pages.get("maintenance")):
            if not self.box_robot_settings.isCollapsed():
                self.box_robot_settings.load()
            if not self.box_valetudo.isCollapsed():
                self.box_valetudo.load()

    @staticmethod
    def _remember_section(box, key, open_default=True):
        """A native QGIS collapsible section; its open/closed state is remembered."""
        box.setSaveCollapsedState(False)   # we store it ourselves, under our own key
        settings_key = f"valetudo/section_{key}"
        box.setCollapsed(not QgsSettings().value(settings_key, open_default, type=bool))
        box.collapsedStateChanged.connect(
            lambda collapsed: QgsSettings().setValue(settings_key, not collapsed))

    def _docked_detail(self):
        """On the dock: what it is doing (a dock task first, else the charge), or ""."""
        if self._state != "docked":
            return ""
        if self._dock_value in DOCK_TASKS:
            return label_or_raw(dock_labels(), self._dock_value)
        if self._battery_flag in ("charging", "charged"):
            return label_or_raw(flag_labels(), self._battery_flag)
        return ""

    def _set_badge(self, state):
        """Coloured pill with the robot state (on the dock: what it is doing there),
        readable at a glance."""
        color = STATE_COLORS.get(state, "#757575")
        text = label_or_raw(state_labels(), state) if state else tr("Unknown")
        detail = self._docked_detail() if state else ""
        if detail:
            text = f"{text} · {detail}"
        for badge in (self.lbl_badge, self.lbl_badge_details):
            badge.setText(text)
            badge.setStyleSheet(
                f"background-color: {color}; color: white; font-weight: bold;"
                "border-radius: 9px; padding: 2px 10px;")

    def _on_tab_changed(self, index):
        if 0 <= index < len(self._tab_keys):
            QgsSettings().setValue(KEY_TAB, self._tab_keys[index])
        self._update_maintenance()
        self._update_camera()
        self._update_console()
        self._update_schedule()

    @staticmethod
    def _button(action, hide_when_disabled=False):
        """A labelled button bound to a plugin QAction: same text, state and tooltip.

        Checkable actions (map tools, Show on map) stay pressed while active."""
        button = QToolButton()
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if hide_when_disabled:
            button.setVisible(action.isEnabled())
            action.changed.connect(lambda b=button, a=action: b.setVisible(a.isEnabled()))
        return button

    def bind_actions(self, act):
        """Place the plugin's actions; called once by the plugin."""
        self.act = act

        def put(grid, keys, row=0, columns=2, hide=False):
            buttons = []
            for i, key in enumerate(k for k in keys if k in act):
                b = self._button(act[key], hide)
                grid.addWidget(b, row + i // columns, i % columns)
                buttons.append(b)
            return buttons

        # Clean: [Clean everything] [Clean room(s)], then [Clean a zone…] [Go to…]
        put(self.clean_grid, ["start"], row=0)
        put(self.clean_grid, ["zone", "goto"], row=1)
        put(self.clean_grid, ["drive"], row=2, hide=True)   # if the robot can be driven
        # Action bar: [Dock] next to the big button
        if "home" in act:
            self._dock_button = self._button(act["home"])
            self._dock_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._dock_button.setMinimumHeight(34)
            self.action_layout.addWidget(self._dock_button)
        for key in ("start", "pause"):
            if key in act:
                act[key].changed.connect(self._update_primary)
        # Strip: [⌂ Return to dock] while the robot is out, then [Show on map]…
        if "home" in act:
            self.btn_strip_home = QToolButton()
            self.btn_strip_home.setDefaultAction(act["home"])
            self.btn_strip_home.setAutoRaise(True)
            self.btn_strip_home.setToolTip(tr("Return to dock (recorded by the camera)"))
            self.btn_strip_home.setVisible(False)   # see _update_primary
            self.strip_layout.insertWidget(self.strip_layout.indexOf(self.btn_strip_camera),
                                           self.btn_strip_home)
        if "live" in act:
            live = QToolButton()
            live.setDefaultAction(act["live"])
            live.setAutoRaise(True)
            self.strip_layout.insertWidget(self.strip_layout.indexOf(self.sep_servers), live)
            # …and in the details, next to the connection line
            live_details = QToolButton()
            live_details.setDefaultAction(act["live"])
            live_details.setAutoRaise(True)
            self.header_layout.insertWidget(self.header_layout.indexOf(self.btn_robot_web),
                                            live_details)
        if "settings" in act:
            settings = QToolButton()
            settings.setDefaultAction(act["settings"])
            settings.setAutoRaise(True)
            self.strip_layout.insertWidget(self.strip_layout.indexOf(self.btn_menu), settings)
        # ⋮ menu: occasional commands
        for key in ("locate", None, "watch_boot", "reboot", None, "settings"):
            if key is None:
                self.menu.addSeparator()
            elif key in act:
                self.menu.addAction(act[key])
        self.menu.addAction(QgsApplication.getThemeIcon("/mActionRefresh.svg"), tr("Refresh now"),
                            self.refresh)
        self.act_compact = self.menu.addAction(tr("Compact mode"))
        self.act_compact.setCheckable(True)
        self.act_compact.setChecked(QgsSettings().value(KEY_COMPACT, False, type=bool))
        self.act_compact.toggled.connect(self.set_compact)
        self.act_advanced = self.menu.addAction(tr("Advanced tools"))
        self.act_advanced.setCheckable(True)
        self.act_advanced.setToolTip(tr("Terminal (consoles and logs in QGIS), Wi-Fi recorder "
                                        "on the robot, boot watch, editing of no-go zones"))
        self.act_advanced.setChecked(load_settings()["advanced_tools"])
        self.act_advanced.toggled.connect(self._on_advanced_toggled)
        self.menu.addSeparator()
        self.menu.addAction(QgsApplication.getThemeIcon("/mActionHelpContents.svg"),
                            tr("User manual"), lambda: open_manual())
        self.menu.addAction(icon(APP_ICON), tr("About…"), self.show_about)
        # Care: dock station commands (hidden when the robot has none)
        put(self.dock_grid, ["empty_dock", "mop_wash", "mop_dry"], columns=3, hide=True)
        self._dock_actions = [act[k] for k in ("empty_dock", "mop_wash", "mop_dry") if k in act]
        for action in self._dock_actions:
            action.changed.connect(self._update_dock_group)
        # Wi-Fi: recording with QGIS open, recorder on the robot, maps from the Pi
        put(self.wifi_qgis_grid, ["wifi_survey", "wifi_map"])
        put(self.wifi_qgis_grid, ["wifi_scan"], row=1, hide=True)   # if the robot can scan
        put(self.wifi_robot_grid, ["robot_survey_install", "robot_survey_import",
                                   "robot_survey_remove"], columns=1)
        if "pi_wifi_map" in act:
            pi_action = act["pi_wifi_map"]

            def follow_pi_action():
                for button in (self.btn_pi_latest, self.btn_pi_full):
                    button.setEnabled(pi_action.isEnabled())
                    button.setToolTip(pi_action.toolTip())
            pi_action.changed.connect(follow_pi_action)
            follow_pi_action()
        # System: boot tools of the robot card
        put(self.system_grid, ["watch_boot", "reboot"])
        self._update_dock_group()
        self._update_rooms_button()
        self._update_primary()
        self.set_compact(self.act_compact.isChecked())

    def _update_dock_group(self, *_):
        actions = getattr(self, "_dock_actions", [])
        self.box_dock.setVisible(any(a.isEnabled() for a in actions)
                                 or getattr(self, "_has_components", False))

    # -- status strip, big button, warnings ---------------------------------------------

    def eventFilter(self, obj, event):
        if obj is getattr(self, "strip", None) \
                and event.type() == QEvent.Type.MouseButtonRelease:
            if self.is_compact():   # compact mode: the strip folds / unfolds the panel
                self._show_body(not self.top_tabs.isVisible())
            else:
                self.show_tab("status")
            return True
        return super().eventFilter(obj, event)

    def show_about(self, *_):
        from ..core.about import AboutDialog
        AboutDialog(self).exec()

    def _on_advanced_toggled(self, on):
        QgsSettings().setValue(KEY_ADVANCED, on)
        self.advancedChanged.emit(on)

    def set_advanced(self, on):
        """Advanced tools shown or not: the Terminal (its >_ menu entries), the Wi-Fi
        recorder on the robot and the boot log (the plugin hides their commands)."""
        if self.act_advanced.isChecked() != on:
            self.act_advanced.blockSignals(True)
            self.act_advanced.setChecked(on)
            self.act_advanced.blockSignals(False)
        for entry in list(self._terminal_entries):
            try:
                entry.setVisible(on)
            except RuntimeError:   # deleted with its menu: forget it
                self._terminal_entries.remove(entry)
        for box in (self.box_wifi_robot, self.box_boot):
            box.setVisible(on)
        if not on:
            self.close_terminal()

    @staticmethod
    def _add_page_title(page, tab_icon, text):
        """A title row (icon, name in bold) at the top of a tab's page, outside its
        scrolling area. Returns (label, row layout) so that a page can add buttons."""
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 4, 2)
        picture = QLabel()
        picture.setPixmap(tab_icon.pixmap(20, 20))
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        label.setFont(font)
        row.addWidget(picture)
        row.addWidget(label, 1)
        page.layout().insertLayout(0, row)
        return label, row

    def _apply_tab_order(self):
        """The side tabs in the order chosen in the settings (Panel tab)."""
        bar = self.tabs.tabBar()
        current = self.tabs.currentWidget()
        self.tabs.blockSignals(True)
        for target, key in enumerate(k for k in tab_order() if k in self._tab_keys):
            source = self._tab_keys.index(key)
            if source != target:
                bar.moveTab(source, target)
                self._tab_keys.insert(target, self._tab_keys.pop(source))
        self.tabs.setCurrentWidget(current)
        self.tabs.blockSignals(False)

    # -- top-level tabs: 🤖 Robot · 🏠 Home · 🖥 Servers ---------------------------------

    def _build_top_tabs(self):
        """The robot's side tabs go under 🤖 Robot; Status and Terminal (all the servers)
        under 🖥 Servers, with side tabs of their own; 🏠 Home lists Home Assistant's
        devices (home/tab.py)."""
        self._tab_pages = {key: self.tabs.widget(i) for i, key in enumerate(self._tab_keys)}
        self.server_tabs = QTabWidget()
        self.server_tabs.setTabPosition(self.tabs.tabPosition())
        self.server_tabs.setDocumentMode(self.tabs.documentMode())
        self.server_tabs.setIconSize(self.tabs.iconSize())
        for key in SERVER_TABS:
            page = self._tab_pages.get(key)
            if page is None:
                continue
            index = self.tabs.indexOf(page)
            tip = self.tabs.tabToolTip(index)
            self.tabs.removeTab(index)
            self.server_tabs.setTabToolTip(
                self.server_tabs.addTab(page, self._tab_icons[key], ""), tip)
        self._tab_keys = [key for key in self._tab_keys if key not in SERVER_TABS]
        # No side bar there: Status is the page, the Terminal comes from a server's >_
        # menu and goes with its ✕ (each page has its own title)
        self.server_tabs.tabBar().setVisible(False)
        self.top_tabs = QTabWidget()
        self.top_tabs.setDocumentMode(True)
        root = self.tabs.parentWidget().layout()
        index = root.indexOf(self.tabs)
        root.removeWidget(self.tabs)
        pages = {}
        for key, inner in (("robot", self.tabs), ("servers", self.server_tabs)):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(inner)
            pages[key] = page
        self.home_tab = HomeTab()
        self.home_tab.problemsChanged.connect(self._on_home_problems)
        self.home_tab.robotDaysRequested.connect(
            lambda days: [self.history_tab._load_day(day) for day in days])
        pages["home"] = self.home_tab
        self._top_pages = pages
        self._top_icons = {"robot": icon(LOGO), "home": icon("tab_home"),
                           "servers": icon("tab_servers")}
        titles = {"robot": tr("Robot"), "home": tr("Home"), "servers": tr("Servers")}
        for key in TOP_TABS:
            self.top_tabs.addTab(pages[key], self._top_icons[key], titles[key])
        root.insertWidget(index, self.top_tabs, 1)
        for tabs in (self.server_tabs, self.top_tabs):
            tabs.currentChanged.connect(self._on_section_changed)

    def _tabs_for(self, key):
        return self.server_tabs if key in SERVER_TABS else self.tabs

    @staticmethod
    def _top_for(key):
        return "servers" if key in SERVER_TABS else ("home" if key == "home" else "robot")

    def _page_shown(self, page):
        """A side tab's page is in front: its section chosen and it selected there."""
        for key, tab_page in self._tab_pages.items():
            if tab_page is page:
                return (self.top_tabs.currentWidget() is self._top_pages[self._top_for(key)]
                        and self._tabs_for(key).currentWidget() is page)
        return False

    def _on_section_changed(self, *_):
        top = next((k for k, p in self._top_pages.items()
                    if p is self.top_tabs.currentWidget()), "robot")
        QgsSettings().setValue(KEY_TOP_TAB, top)
        self._update_camera()
        self._update_console()
        self._update_schedule()
        self._update_home()
        self._update_maintenance()

    def _update_home(self):
        self.home_tab.set_active(self.isVisible()
                                 and self.top_tabs.currentWidget() is self.home_tab)

    def _on_home_problems(self, unavailable, low, soon=0):
        self._set_problem("home_unavailable", tr("{n} Home Assistant device(s) unavailable.")
                          .format(n=unavailable) if unavailable else None, "home")
        self._set_problem("home_battery", tr("{n} Home Assistant device(s) with a low "
                                             "battery.").format(n=low) if low else None, "home")
        self._set_problem("home_battery_soon", tr(
            "{n} Home Assistant battery(ies) to change within two weeks.").format(n=soon)
            if soon else None, "home")

    def _set_tab_shown(self, key, shown):
        """Show or hide a side tab (Qt 5.15+)."""
        page = self._tab_pages.get(key)
        if page is not None:
            tabs = self._tabs_for(key)
            tabs.setTabVisible(tabs.indexOf(page), shown)

    def show_tab(self, key):
        """Bring a side tab (or "home") to the front, with its section (unfolding a
        compact panel)."""
        if self.is_compact() and not self.top_tabs.isVisible():
            self._show_body(True)
        self.top_tabs.setCurrentWidget(self._top_pages[self._top_for(key)])
        page = self._tab_pages.get(key)
        if page is not None:
            self._tabs_for(key).setCurrentWidget(page)

    def _update_primary(self, *_):
        """Start when docked or idle, Pause while working, Resume when paused."""
        act = getattr(self, "act", {})
        state = self._state
        if state in ACTIVE_STATES:
            key, text, tip = "pause", tr("Pause"), tr("Pause the current job.")
        elif state == "paused":
            key, text, tip = "start", tr("Resume"), tr("Resume the paused job.")
        else:
            key, text, tip = ("start", tr("Start cleaning all rooms"),
                              tr("Start cleaning the whole home."))
        self._primary_key = key
        self.btn_primary.setIcon(icon(key))   # icons/start.svg, icons/pause.svg
        self.btn_primary.setText(text)
        self.btn_primary.setToolTip(tip)
        self.btn_primary.setEnabled(self.client is not None and key in act
                                    and act[key].isEnabled())
        for dock in (getattr(self, "_dock_button", None), getattr(self, "btn_strip_home", None)):
            if dock is not None:
                dock.setVisible(state not in ("docked", None))

    def _on_primary(self, *_):
        action = getattr(self, "act", {}).get(getattr(self, "_primary_key", "start"))
        if action is not None and action.isEnabled():
            action.trigger()

    def _set_problem(self, key, text, tab="status"):
        """A problem shown by the ⚠ of the strip (text None: solved) and on its tab."""
        if text:
            self._problems[key] = (text, tab)
        else:
            self._problems.pop(key, None)
        problems = list(self._problems.values())
        self.btn_warning.setVisible(bool(problems))
        self.btn_warning.setToolTip("\n".join(f"⚠ {text}" for text, _ in problems))
        if not hasattr(self, "_tab_pages"):
            return
        for tab_key, page in self._tab_pages.items():
            flagged = any(t == tab_key for _, t in problems)
            tabs = self._tabs_for(tab_key)
            tabs.setTabIcon(tabs.indexOf(page), badge_icon(self._tab_icons[tab_key])
                            if flagged else self._tab_icons[tab_key])
        for top_key, page in self._top_pages.items():   # the sections too
            flagged = any(self._top_for(t) == top_key for _, t in problems if t)
            self.top_tabs.setTabIcon(self.top_tabs.indexOf(page),
                                     badge_icon(self._top_icons[top_key]) if flagged
                                     else self._top_icons[top_key])

    def _on_warning_clicked(self, *_):
        """Open the tab of the first problem that has one."""
        tab = next((t for _, t in self._problems.values() if t), "status")
        self.show_tab(tab)

    def _update_job(self):
        """Time and area of the job in progress, in the strip."""
        job = getattr(self, "_job", None)
        show = self._state in ACTIVE_STATES and job is not None
        self.lbl_job.setVisible(show)
        if show:
            seconds, area = job
            parts = [format_seconds(seconds)] if seconds is not None else []
            if area is not None:
                parts.append(format_area_cm2(area))
            self.lbl_job.setText(" · ".join(parts))
        self._emit_summary()

    def _emit_summary(self):
        """State, battery and job in one line, for the card over the map."""
        state = self._state
        if state is None:
            self.summaryChanged.emit("")
            return
        color = STATE_COLORS.get(state, "#757575")
        label = label_or_raw(state_labels(), state)
        detail = self._docked_detail()
        if detail:
            label = f"{label} · {detail}"
        parts = [f"<b style='color:{color}'>{html.escape(label)}</b>"]
        battery = getattr(self, "_battery", None)
        if battery is not None:
            parts.append(f"{battery} %")
        if self.lbl_job.isVisibleTo(self):
            parts.append(html.escape(self.lbl_job.text()))
        self.summaryChanged.emit(" · ".join(parts))

    # -- compact mode ---------------------------------------------------------------------

    def is_compact(self):
        return getattr(self, "_compact", False)

    def set_compact(self, compact):
        """Only the strip and the big button; a click on the strip unfolds or folds
        the rest. Nothing folds by itself (focus or mouse moving elsewhere)."""
        self._compact = compact
        QgsSettings().setValue(KEY_COMPACT, compact)
        self._update_strip_tip()
        self._show_body(not compact)

    def _show_body(self, visible):
        for widget in (self.top_tabs, self.lbl_feedback):
            widget.setVisible(visible)

    # -- feedback ---------------------------------------------------------------------------


    def show_feedback(self, text, kind="info"):
        """Called by the plugin with the result of a command."""
        colors = {"success": "#2e7d32", "warning": "#ef6c00", "critical": "#c62828"}
        self.lbl_feedback.setStyleSheet(f"color: {colors[kind]};" if kind in colors else "")
        self.lbl_feedback.setText(text)

    # -- client wiring ---------------------------------------------------------

    def attach(self, client):
        """Called by the plugin whenever its client is created (or dropped: None)."""
        self.client = client
        self.capabilities = None
        self._reachable = None
        self._update_console()
        self.box_robot_settings.set_robot(client, [])
        self.box_valetudo.set_client(client)
        self.box_valetudo.setVisible(client is not None)
        if client is None:
            self._timer.stop()
            self._show_disconnected()
            for box in (self.box_settings, self.box_current, self.box_total,
                        self.box_consumables, self.box_dock):
                box.setVisible(False)
            _set_row_visible(self.status_form, self.lbl_attachments, False)
            self.lbl_features.setText("—")
            self._segments = []
            self.rooms_ctl.clear()
            self.rooms.setVisible(False)
            self.segmentsChanged.emit([])
            self._update_rooms_button()
            self.camera_light.setVisible(False)
            self.chk_goto_quiet.setVisible(False)
            self._set_badge(None)
            self.lbl_error.setVisible(False)
            self._timers, self._timer_props = [], None
            self._render_timers()
            return
        client.reachable.connect(self._on_reachable)
        client.robotInfoReceived.connect(self._on_robot_info)
        client.versionReceived.connect(self._on_version)
        client.capabilitiesReceived.connect(self._on_capabilities)
        client.attributesReceived.connect(self._on_attributes)
        client.consumablesReceived.connect(self._on_consumables)
        client.currentStatisticsReceived.connect(self._on_current_statistics)
        client.totalStatisticsReceived.connect(self._on_total_statistics)
        client.wifiReceived.connect(self._on_wifi)
        client.eventsReceived.connect(self._on_events)
        client.presetsReceived.connect(self._on_presets)
        client.segmentsReceived.connect(self._on_segments)
        client.toggleReceived.connect(self._on_toggle)
        client.commandSent.connect(self._on_command_sent)
        client.mapPeeked.connect(self.update_map)
        client.hostInfoReceived.connect(self._on_host_info)
        client.timersReceived.connect(self._on_timers)
        client.timerPropertiesReceived.connect(self._on_timer_properties)
        client.commandDone.connect(lambda *_: QTimer.singleShot(1500, self.refresh))
        self._robot_text = ""
        self._version_text = ""
        self._wifi_html, self._wifi_tip = "", ""
        self._update_schedule()
        if QgsSettings().value(KEY_ONCE_TIMERS, [], type=list):
            client.fetch_timers()   # a one-off cleaning may be due for removal
        client.fetch_robot_info(quiet=True)
        client.fetch_version(quiet=True)
        if self.isVisible():
            self.refresh()
            self._timer.start()

    def _on_toggle(self, capability, enabled):
        if capability == "CameraLightControlCapability":
            self.camera_light.setChecked(enabled)   # setChecked does not emit clicked

    # -- settings, lifecycle, refresh ------------------------------------------------------


    def settings_changed(self):
        """Called by the plugin after the Options page saved changes: the servers'
        frames are built again from the settings."""
        self._ssh_passwords = {}   # SSH passwords may have changed
        self._apply_tab_order()
        self.home_tab.settings_changed()
        self._build_server_frames()
        self._update_console()

    def clear_boot_log(self):
        self.txt_boot.clear()

    def add_boot_log(self, line):
        self.txt_boot.appendPlainText(line)

    def shutdown(self):
        """Called by the plugin on unload."""
        self.history_tab.shutdown()
        self.home_tab.shutdown()
        self._camera_grace.stop()
        self.camera.shutdown()
        for entry in self._server_entries:
            entry["block"].stop()
        for log in self.logs:
            log.shutdown()
        for console in self.consoles:
            console.shutdown()

    def _on_visibility(self, visible):
        self._update_camera()
        self._update_console()
        self._update_schedule()
        self._update_home()
        if not visible:
            self._timer.stop()
            self._age_timer.stop()
            return
        self._age_timer.start()
        if self.client is None:
            self.clientRequested.emit()   # the plugin creates the client, then calls attach()
        else:
            self.refresh()
            self._timer.start()

    def refresh_all(self, *_):
        """Status tab: read every server again now."""
        self.refresh()
        for entry in self._server_entries:
            entry["block"].refresh()

    def refresh(self, *_):
        client = self.client
        if client is None:
            return
        # (pushed by Valetudo as they change when its live streams are open)
        if not client.streaming("attributes"):
            client.fetch_attributes(quiet=True)
        client.fetch_events(quiet=True)
        client.fetch_host_info(quiet=True)
        # Position comes from the map: read it unless live tracking just delivered one.
        if (not client.streaming("map")
                and time.monotonic() - self._last_map >= self._timer.interval() / 1000 * 0.9):
            client.peek_map()
        caps = self.capabilities or set()
        if "ConsumableMonitoringCapability" in caps:
            client.fetch_consumables(quiet=True)
        if "CurrentStatisticsCapability" in caps:
            client.fetch_current_statistics(quiet=True)
        if "TotalStatisticsCapability" in caps:
            client.fetch_total_statistics(quiet=True)
        if "WifiConfigurationCapability" in caps:
            client.fetch_wifi(quiet=True)
        if "MapSegmentationCapability" in caps:
            client.fetch_segments()


