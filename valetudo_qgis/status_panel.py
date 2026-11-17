"""Dockable status panel: robot state, settings, statistics, consumables...

The panel refreshes itself while it is visible (every 5 s while the robot is
working, every 30 s otherwise), independently of live map tracking. Sections
the robot does not support stay hidden.
"""

import html
import math
import re
import time

from qgis.PyQt.QtCore import QDateTime, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QFontDatabase
from qgis.PyQt.QtWidgets import (
    QLabel,
    QInputDialog,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QTreeWidgetItem,
)
from qgis.core import QgsApplication, QgsSettings
from qgis.gui import QgsDockWidget

from .camera_widget import CameraWidget
from . import room_groups
from .i18n import tr
from . import host_info
from .icons import LOGO, RPI_LOGO, icon
from .robot_survey import RobotSurvey
from .log_tail import LOG_PATH, LogTail
from . import schedule
from .rooms_tree import RoomsTree
from .settings import load_settings
from .console_tab import ConsoleTab
from .timer_dialog import TimerDialog, day_names, format_offset, utc_offset_minutes
from .ui_loader import load_ui, set_row_visible as _set_row_visible

KEY_TAB = "valetudo/panel_tab"
KEY_GOTO_QUIET = "valetudo/goto_quiet"   # "Go to" without cleaning (emulated go-to only)
KEY_PI_MAP_FULL = "valetudo/pi_map_full"   # "Load Wi-Fi map from the Pi": all runs

# Layout: ui/status_panel.ui (Qt Designer). The code fills it at run time and
# relies on these object names.
UI_WIDGETS = (
    "lbl_connection", "btn_refresh", "lbl_robot", "lbl_badge", "bar_battery", "lbl_error",
    "grp_clean", "clean_grid", "rooms", "btn_rooms", "grp_robot", "robot_grid",
    "grp_dock", "dock_grid", "header_layout", "lbl_logo", "lbl_robot_info", "pi_header",
    "lbl_pi_logo", "lbl_pi_connection", "btn_pi_refresh", "lbl_pi_name", "lbl_pi_info", "lbl_feedback", "tabs", "tab_camera",
    "camera_layout", "camera_light", "status_form", "lbl_state", "lbl_dock", "dock_form",
    "settings_form", "combo_fan_speed", "combo_water_usage", "combo_operation_mode",
    "lbl_attachments",
    "lbl_position", "consumables_form", "lbl_cur_time", "lbl_cur_area", "lbl_tot_count",
    "lbl_tot_time", "lbl_tot_area", "tools_grid", "list_events", "txt_boot",
    "lbl_features", "tab_log", "lbl_log_status", "chk_log_follow", "btn_log_clear",
    "txt_log",
    "tab_console", "lbl_console_status", "btn_console_connect", "btn_console_clear",
    "txt_console", "lbl_console_prompt", "edit_console", "btn_console_run", "btn_console_stop",
    "tab_pi_console", "lbl_pi_console_status", "btn_pi_console_connect",
    "btn_pi_console_clear", "txt_pi_console", "lbl_pi_console_prompt", "edit_pi_console",
    "btn_pi_console_run", "btn_pi_console_stop",
    "tab_schedule", "timers", "btn_timer_new", "btn_timer_edit", "btn_timer_delete",
    "btn_timer_run", "lbl_timers_note", "chk_goto_quiet", "chk_pi_map_full",
)
# Collapsible sections -> key of their remembered open/closed state.
SECTIONS = {
    "box_status": "status", "box_dock": "dock", "box_settings": "settings",
    "box_position": "position",
    "box_consumables": "consumables", "box_current": "current", "box_total": "totals",
    "box_tools": "tools", "box_events": "events", "box_boot": "boot",
    "box_features": "features",
}
STATE_COLORS = {
    "cleaning": "#1565c0", "moving": "#1565c0", "manual_control": "#1565c0",
    "returning": "#ef6c00", "paused": "#f9a825", "docked": "#2e7d32",
    "idle": "#757575", "error": "#c62828",
}
ACTIVE_INTERVAL_MS = 5_000
IDLE_INTERVAL_MS = 30_000
PI_INTERVAL_MS = 30_000    # Pi block refresh (one short SSH command) while visible
CAMERA_GRACE_MS = 60_000   # the stream keeps running this long after the tab is left
ACTIVE_STATES = {"cleaning", "returning", "moving", "manual_control"}
LOW_PERCENT = 10
LOW_MINUTES = 600  # 10 h
MAX_EVENTS = 10

PRESET_ROWS = {  # capability -> attribute type in PresetSelectionStateAttribute
    "FanSpeedControlCapability": "fan_speed",
    "WaterUsageControlCapability": "water_grade",
    "OperationModeControlCapability": "operation_mode",
}


# ---------------------------------------------------------------------------
# Translated labels for Valetudo values (functions: evaluated after the
# translator is installed). Unknown values fall back to the raw value.
# ---------------------------------------------------------------------------

def _state_labels():
    return {
        "idle": tr("Idle"), "cleaning": tr("Cleaning"), "returning": tr("Returning to dock"),
        "docked": tr("Docked"), "paused": tr("Paused"), "error": tr("Error"),
        "manual_control": tr("Manual control"), "moving": tr("Moving"),
        # dock status values
        "pause": tr("Paused"), "emptying": tr("Emptying"), "drying": tr("Drying"),
        "washing": tr("Washing"),
    }


def _flag_labels():
    return {
        "segment": tr("Rooms"), "zone": tr("Zone"), "spot": tr("Spot"),
        "target": tr("Target"), "resumable": tr("Resumable"), "mapping": tr("Mapping"),
        "charging": tr("Charging"), "discharging": tr("Discharging"), "charged": tr("Charged"),
    }


def preset_labels():
    return {
        "off": tr("Off"), "min": tr("Minimum"), "low": tr("Low"), "medium": tr("Medium"),
        "high": tr("High"), "max": tr("Maximum"), "turbo": tr("Turbo"), "custom": tr("Custom"),
        # operation modes
        "vacuum": tr("Vacuum"), "mop": tr("Mop"), "vacuum_and_mop": tr("Vacuum and mop"),
        "vacuum_then_mop": tr("Vacuum, then mop"),
    }


def _attachment_labels():
    return {"dustbin": tr("Dust bin"), "watertank": tr("Water tank"), "mop": tr("Mop")}


def _consumable_label(ctype, subtype):
    labels = {
        ("brush", "main"): tr("Main brush"),
        ("brush", "side_right"): tr("Side brush"),
        ("brush", "side_left"): tr("Side brush"),
        ("filter", "main"): tr("Filter"),
        ("sensor", "all"): tr("Sensors"),
        ("mop", "main"): tr("Mop pad"),
        ("detergent", "main"): tr("Detergent"),
        ("bin", "main"): tr("Dust bag"),
    }
    return labels.get((ctype, subtype)) or " ".join(p for p in (ctype, subtype) if p)


# Dock components (DockComponentStateAttribute), in display order.
DOCK_COMPONENT_ORDER = ["water_tank_clean", "water_tank_dirty", "detergent", "dustbag"]
DOCK_COMPONENT_PROBLEMS = {"missing", "empty", "full"}


def dock_component_labels():
    return {
        "water_tank_clean": tr("Fresh water"),
        "water_tank_dirty": tr("Waste water"),
        "detergent": tr("Detergent"),
        "dustbag": tr("Dust bag"),
    }


def dock_component_values():
    return {
        "ok": tr("OK"), "missing": tr("Missing"), "empty": tr("Empty"),
        "full": tr("Full"), "unknown": tr("Unknown"),
    }


def dock_component_advice():
    return {"missing": tr("Put it back in place."), "empty": tr("Refill it."),
            "full": tr("Empty it.")}


# Capabilities listed with ✗ when missing (the ones the plugin uses).
CORE_CAPABILITIES = [
    "BasicControlCapability", "MapSegmentationCapability", "ZoneCleaningCapability",
    "GoToLocationCapability", "FanSpeedControlCapability", "WaterUsageControlCapability",
    "ConsumableMonitoringCapability", "CurrentStatisticsCapability",
    "TotalStatisticsCapability", "LocateCapability", "AutoEmptyDockManualTriggerCapability",
    "WifiConfigurationCapability", "CameraLightControlCapability",
]


def _humanize(capability):
    """'CarpetSensorModeControlCapability' -> 'Carpet sensor mode control' (fallback)."""
    name = capability[:-len("Capability")] if capability.endswith("Capability") else capability
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()
    return " ".join([words[0]] + [w.lower() for w in words[1:]]) if words else capability


def _capability_labels():
    return {
        "AutoEmptyDockAutoEmptyControlCapability": tr("Auto-empty dock"),
        "AutoEmptyDockAutoEmptyDurationControlCapability": tr("Auto-empty duration"),
        "AutoEmptyDockAutoEmptyIntervalControlCapability": tr("Auto-empty interval"),
        "CameraLightControlCapability": tr("Camera light"),
        "CarpetModeControlCapability": tr("Carpet mode"),
        "CarpetSensorModeControlCapability": tr("Carpet sensor mode"),
        "CleanRouteControlCapability": tr("Cleaning route"),
        "CollisionAvoidantNavigationControlCapability": tr("Collision-avoidant navigation"),
        "CombinedVirtualRestrictionsCapability": tr("Virtual walls and no-go zones"),
        "DoNotDisturbCapability": tr("Do not disturb"),
        "FloorMaterialDirectionAwareNavigationControlCapability":
            tr("Floor-direction-aware navigation"),
        "HighResolutionManualControlCapability": tr("Manual control (high resolution)"),
        "KeyLockCapability": tr("Child lock"),
        "ManualControlCapability": tr("Manual control"),
        "MapResetCapability": tr("Map reset"),
        "MapSegmentEditCapability": tr("Room editing"),
        "MapSegmentMaterialControlCapability": tr("Floor materials"),
        "MapSegmentRenameCapability": tr("Room renaming"),
        "MapSnapshotCapability": tr("Map snapshots"),
        "MappingPassCapability": tr("Mapping pass"),
        "MopDockCleanManualTriggerCapability": tr("Mop washing"),
        "MopDockDryManualTriggerCapability": tr("Mop drying"),
        "MopDockMopAutoDryingControlCapability": tr("Automatic mop drying"),
        "MopDockMopDryingTimeControlCapability": tr("Mop drying time"),
        "MopDockMopWashTemperatureControlCapability": tr("Mop wash temperature"),
        "MopExtensionControlCapability": tr("Mop extension"),
        "MopExtensionFurnitureLegHandlingControlCapability":
            tr("Mop extension around furniture legs"),
        "MopTwistControlCapability": tr("Mop twist"),
        "ObstacleAvoidanceControlCapability": tr("Obstacle avoidance"),
        "ObstacleImagesCapability": tr("Obstacle images"),
        "OperationModeControlCapability": tr("Operation mode"),
        "PendingMapChangeHandlingCapability": tr("Pending map changes"),
        "PetObstacleAvoidanceControlCapability": tr("Pet waste avoidance"),
        "QuirksCapability": tr("Quirks"),
        "SpeakerTestCapability": tr("Speaker test"),
        "SpeakerVolumeControlCapability": tr("Speaker volume"),
        "VoicePackManagementCapability": tr("Voice packs"),
        "WifiScanCapability": tr("Wi-Fi scan"),
        "BasicControlCapability": tr("Basic control"),
        "MapSegmentationCapability": tr("Room cleaning"),
        "ZoneCleaningCapability": tr("Zone cleaning"),
        "GoToLocationCapability": tr("Go to location"),
        "FanSpeedControlCapability": tr("Fan speed"),
        "WaterUsageControlCapability": tr("Water usage"),
        "ConsumableMonitoringCapability": tr("Consumables"),
        "CurrentStatisticsCapability": tr("Current statistics"),
        "TotalStatisticsCapability": tr("Total statistics"),
        "LocateCapability": tr("Locate"),
        "AutoEmptyDockManualTriggerCapability": tr("Empty dock"),
        "WifiConfigurationCapability": tr("Wi-Fi"),
    }


def _event_label(event):
    cls = event.get("__class", "")
    if cls == "DustBinFullValetudoEvent":
        return tr("Dust bin full")
    if cls == "ConsumableDepletedValetudoEvent":
        return tr("Consumable depleted: {name}").format(
            name=_consumable_label(event.get("type"), event.get("subType")))
    if cls == "ErrorStateValetudoEvent":
        return tr("Error: {message}").format(message=event.get("message", ""))
    if cls == "MissingResourceValetudoEvent":
        return tr("Missing resource: {message}").format(message=event.get("message", ""))
    if cls == "MopAttachmentReminderValetudoEvent":
        return tr("Mop attachment reminder")
    if cls == "PendingMapChangeValetudoEvent":
        return tr("Pending map change")
    return cls.replace("ValetudoEvent", "") or "?"


LOG_LEVEL_COLORS = {"error": "#c62828", "warn": "#ef6c00", "debug": "#757575",
                    "trace": "#9e9e9e"}


def _log_line_html(line):
    """One log line, coloured by its level ("[ERROR]", "[WARN]"…) when it has one."""
    match = re.search(r"\[(ERROR|WARN|WARNING|DEBUG|TRACE)\]", line, re.IGNORECASE)
    text = html.escape(line) or "&nbsp;"
    level = match.group(1).lower()[:5] if match else ""
    color = LOG_LEVEL_COLORS.get("warn" if level.startswith("warn") else level)
    return f"<span style='white-space:pre; color:{color}'>{text}</span>" if color \
        else f"<span style='white-space:pre'>{text}</span>"


def state_label(state):
    """Translated robot state ("docked" -> "Docked" / "À la base")."""
    return _label(_state_labels(), state)


def _label(mapping, value):
    return mapping.get(value, value) if value is not None else "—"


def _format_duration(seconds):
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    return tr("{minutes} min").format(minutes=minutes)


def _format_area_cm2(value):
    return tr("{area} m²").format(area=f"{value / 10_000:.1f}")


def _format_time(iso):
    dt = QDateTime.fromString(iso or "", Qt.DateFormat.ISODateWithMs)
    if not dt.isValid():
        dt = QDateTime.fromString(iso or "", Qt.DateFormat.ISODate)
    return dt.toLocalTime().toString("dd/MM HH:mm") if dt.isValid() else ""


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class ValetudoPanel(QgsDockWidget):
    clientRequested = pyqtSignal()   # the panel was shown but no client exists yet
    splitRequested = pyqtSignal(str, str)   # room id, room name: draw the cut on the map
    segmentsChanged = pyqtSignal(list)      # [(room id, name)] known on the robot

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
        self._pi = None            # last Pi info (host_info.parse_pi), None = never read
        self._pi_ok = None         # True / False after a Pi read, None before
        self._pi_last_ok = None    # time.monotonic() of the last successful Pi read
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
        self.lbl_logo.setPixmap(icon(LOGO).pixmap(20, 20))
        # Raspberry Pi block: one SSH command every PI_INTERVAL_MS while visible.
        self.lbl_pi_logo.setPixmap(icon(RPI_LOGO).pixmap(20, 20))
        self.btn_pi_refresh.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
        self.btn_pi_refresh.clicked.connect(self._refresh_pi)
        self.pi_runner = RobotSurvey(self)   # one-shot SSH runner
        self.pi_runner.finished.connect(self._on_pi_info)
        self._pi_timer = QTimer(self)
        self._pi_timer.setInterval(PI_INTERVAL_MS)
        self._pi_timer.timeout.connect(self._refresh_pi)
        self.btn_refresh.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
        self.btn_refresh.clicked.connect(self.refresh)
        self._set_badge(None)
        self.lbl_error.setVisible(False)

        # Rooms in a checkable tree: "All rooms" (tri-state) above one checkbox per
        # room. Right-click a room to rename, join or split it.
        self.rooms_ctl = RoomsTree(self.rooms, expanded_key="valetudo/room_group_open")
        self.rooms_ctl.checkedChanged.connect(self._update_rooms_button)
        self.rooms.customContextMenuRequested.connect(self._on_rooms_context_menu)
        self.rooms.setVisible(False)
        self.btn_rooms.setIcon(icon("clean_rooms"))
        self.btn_rooms.clicked.connect(self._clean_rooms)
        self.btn_rooms.setVisible(False)
        self._segments = []
        # Shown only for robots whose "Go to" is a small cleaning job (no native go-to).
        self.chk_goto_quiet.setChecked(QgsSettings().value(KEY_GOTO_QUIET, True, type=bool))
        self.chk_goto_quiet.toggled.connect(
            lambda checked: QgsSettings().setValue(KEY_GOTO_QUIET, checked))
        self.chk_goto_quiet.setVisible(False)
        self.chk_pi_map_full.setChecked(QgsSettings().value(KEY_PI_MAP_FULL, False, type=bool))
        self.chk_pi_map_full.toggled.connect(
            lambda checked: QgsSettings().setValue(KEY_PI_MAP_FULL, checked))

        self.preset_combos = {"FanSpeedControlCapability": self.combo_fan_speed,
                              "WaterUsageControlCapability": self.combo_water_usage,
                              "OperationModeControlCapability": self.combo_operation_mode}
        for capability, combo in self.preset_combos.items():
            combo.activated.connect(lambda index, c=capability: self._on_preset_chosen(c, index))

        self.lbl_position.setText(tr("Waiting for the robot position…"))

        # Camera: plays only while this tab is shown and the panel is visible.
        self.camera_page = self.tab_camera
        self.camera = CameraWidget()
        self.camera_layout.insertWidget(0, self.camera)
        # Coming back to the tab soon after leaving it shows the video at once,
        # instead of reconnecting and waiting for the robot's next full image.
        self._camera_grace = QTimer(self)
        self._camera_grace.setSingleShot(True)
        self._camera_grace.setInterval(CAMERA_GRACE_MS)
        self._camera_grace.timeout.connect(self.camera.stop)
        self.camera_light.setVisible(False)    # shown if the robot supports it
        self.camera_light.clicked.connect(self._on_camera_light_clicked)  # user only

        # Log: Valetudo's log file, followed over SSH while this tab is shown.
        self.txt_log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.btn_log_clear.clicked.connect(self.txt_log.clear)
        self.chk_log_follow.toggled.connect(self._on_log_follow_toggled)
        self.log_tail = LogTail(self)
        self.log_tail.linesReceived.connect(self._on_log_lines)
        self.log_tail.stateChanged.connect(self._on_log_state)
        self.lbl_log_status.setText(tr("Shown while this tab is open."))

        # SSH consoles (robot, Raspberry Pi): open when their tab is first shown, stay
        # open while the panel is visible, close when it is hidden.
        def console_widgets(p):
            return {"status": getattr(self, f"lbl_{p}console_status"),
                    "connect": getattr(self, f"btn_{p}console_connect"),
                    "clear": getattr(self, f"btn_{p}console_clear"),
                    "output": getattr(self, f"txt_{p}console"),
                    "prompt": getattr(self, f"lbl_{p}console_prompt"),
                    "edit": getattr(self, f"edit_{p}console"),
                    "run": getattr(self, f"btn_{p}console_run"),
                    "stop": getattr(self, f"btn_{p}console_stop")}
        self.consoles = [
            ConsoleTab(self.tab_console, console_widgets(""), self._ssh_target,
                       tr("No robot configured."), self),
            ConsoleTab(self.tab_pi_console, console_widgets("pi_"), self._pi_target,
                       tr("No Raspberry Pi set in the settings."), self),
        ]
        self._update_pi_tab()

        # Schedule: Valetudo's timers (run by the robot); fetched when the tab is shown.
        self._timers, self._timer_props = [], None
        self.timers.itemChanged.connect(self._on_timer_item_changed)
        self.timers.itemDoubleClicked.connect(lambda *_: self._edit_timer())
        self.timers.itemSelectionChanged.connect(self._update_timer_buttons)
        self.btn_timer_new.clicked.connect(self._new_timer)
        self.btn_timer_edit.clicked.connect(self._edit_timer)
        self.btn_timer_delete.clicked.connect(self._delete_timer)
        self.btn_timer_run.clicked.connect(self._run_timer)
        self.segmentsChanged.connect(lambda *_: self._render_timers())
        self._render_timers()

        # Sections remember whether they are open, under our own keys.
        for name, key in SECTIONS.items():
            self._remember_section(getattr(self, name), key)

        self._tab_keys = [self.tabs.widget(i).objectName().removeprefix("tab_")
                          for i in range(self.tabs.count())]
        last = QgsSettings().value(KEY_TAB, "robot", type=str)
        if last in self._tab_keys:
            self.tabs.setCurrentIndex(self._tab_keys.index(last))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        for box in (self.box_settings, self.box_current, self.box_total, self.box_consumables,
                    self.box_dock):
            box.setVisible(False)   # shown once the robot reports them
        _set_row_visible(self.status_form, self.lbl_attachments, False)

    @staticmethod
    def _remember_section(box, key, open_default=True):
        """A native QGIS collapsible section; its open/closed state is remembered."""
        box.setSaveCollapsedState(False)   # we store it ourselves, under our own key
        settings_key = f"valetudo/section_{key}"
        box.setCollapsed(not QgsSettings().value(settings_key, open_default, type=bool))
        box.collapsedStateChanged.connect(
            lambda collapsed: QgsSettings().setValue(settings_key, not collapsed))

    def _set_badge(self, state):
        """Coloured pill with the robot state, readable at a glance."""
        color = STATE_COLORS.get(state, "#757575")
        text = _label(_state_labels(), state) if state else tr("Unknown")
        self.lbl_badge.setText(text)
        self.lbl_badge.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold;"
            "border-radius: 9px; padding: 2px 10px;")

    def _on_tab_changed(self, index):
        if 0 <= index < len(self._tab_keys):
            QgsSettings().setValue(KEY_TAB, self._tab_keys[index])
        self._update_camera()
        self._update_log()
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
        def put(grid, keys, row=0, columns=2, hide=False):
            buttons = []
            for i, key in enumerate(k for k in keys if k in act):
                b = self._button(act[key], hide)
                grid.addWidget(b, row + i // columns, i % columns)
                buttons.append(b)
            return buttons

        # Clean: rooms list (row 0), Everything + Ticked rooms, Zone + Go to
        put(self.clean_grid, ["start"], row=1)
        self.clean_grid.addWidget(self.btn_rooms, 1, 1)
        put(self.clean_grid, ["zone", "goto"], row=2)
        put(self.robot_grid, ["pause", "home", "locate"], columns=3)
        dock = put(self.dock_grid, ["empty_dock", "mop_wash", "mop_dry"], columns=3, hide=True)
        self._dock_actions = [act[k] for k in ("empty_dock", "mop_wash", "mop_dry") if k in act]
        for action in self._dock_actions:
            action.changed.connect(self._update_dock_group)
        self._update_dock_group()
        if "live" in act:   # in the header, between the status and the refresh button
            live = self._button(act["live"])
            live.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.header_layout.insertWidget(self.header_layout.indexOf(self.btn_refresh), live)
        tools = put(self.tools_grid, ["edit_restrictions", "send_restrictions", "watch_boot",
                                      "reboot", "wifi_survey", "wifi_map",
                                      "robot_survey_install", "robot_survey_import",
                                      "robot_survey_remove", "pi_wifi_map"])
        # "Full map" goes right under "Load Wi-Fi map from the Pi", and follows its state.
        if "pi_wifi_map" in act and tools:
            last = len(tools) - 1   # put() fills two columns, row by row
            self.tools_grid.addWidget(self.chk_pi_map_full, last // 2 + 1, last % 2)
            pi_action = act["pi_wifi_map"]
            pi_action.changed.connect(
                lambda: self.chk_pi_map_full.setEnabled(pi_action.isEnabled()))
            self.chk_pi_map_full.setEnabled(pi_action.isEnabled())
        self._update_rooms_button()

    def _update_dock_group(self, *_):
        self.grp_dock.setVisible(any(a.isEnabled() for a in self._dock_actions))

    def show_feedback(self, text, kind="info"):
        """Called by the plugin with the result of a command."""
        colors = {"success": "#2e7d32", "warning": "#ef6c00", "critical": "#c62828"}
        self.lbl_feedback.setStyleSheet(f"color: {colors[kind]};" if kind in colors else "")
        self.lbl_feedback.setText(text)

    # -- rooms ----------------------------------------------------------------------

    def _on_segments(self, segments):
        rows = []
        for seg in segments:
            if isinstance(seg, dict) and seg.get("id") is not None:
                seg_id = str(seg["id"])
                rows.append((seg_id, seg.get("name") or f"{tr('Room')} {seg_id}"))
        rows.sort(key=lambda r: r[1].lower())
        if rows == self._segments:
            return
        self._segments = rows
        self.rooms_ctl.set_rooms(rows)
        self.rooms.setVisible(bool(rows))
        self._update_rooms_button()
        self.segmentsChanged.emit(rows)

    def set_room_groups(self, groups):
        """Groups from the room groups file: [(title, [entry, …]), …]."""
        self._room_groups = list(groups)
        self.rooms_ctl.set_groups(groups)

    @property
    def _checked_rooms(self):
        return set(self.rooms_ctl.checked)

    def _on_rooms_context_menu(self, pos):
        item = self.rooms.itemAt(pos)
        seg_id = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        global_pos = self.rooms.viewport().mapToGlobal(pos)
        if seg_id is not None:   # a room
            self._room_menu(seg_id, item.text(0), global_pos)
        else:                    # a group line or empty space
            menu = QMenu(self)
            menu.addAction(tr("Edit room groups…"), self.edit_room_groups)
            menu.exec(global_pos)

    def edit_room_groups(self, *_):
        """Open the room groups file in the system's text editor (created if needed)."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(room_groups.ensure_file()))

    def _room_menu(self, seg_id, name, global_pos):
        if self.client is None:
            return
        caps = self.capabilities
        can_rename = caps is None or "MapSegmentRenameCapability" in caps
        can_edit = caps is None or "MapSegmentEditCapability" in caps

        menu = QMenu(self)
        rename = menu.addAction(tr("Rename…"))
        rename.setEnabled(can_rename)
        rename.triggered.connect(lambda *_: self._rename_room(seg_id, name))
        join = menu.addMenu(tr("Join with"))
        join.setEnabled(can_edit and len(self._segments) > 1)
        for other_id, other_name in self._segments:
            if other_id != seg_id:
                action = join.addAction(other_name)
                action.triggered.connect(
                    lambda *_, o=other_id, on=other_name: self._join_rooms(seg_id, name, o, on))
        split = menu.addAction(tr("Split with a line on the map…"))
        split.setEnabled(can_edit)
        split.triggered.connect(lambda *_: self.splitRequested.emit(seg_id, name))
        if not can_rename or not can_edit:
            menu.addSeparator()
            note = menu.addAction(tr("Greyed out: not supported by this robot."))
            note.setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Edit room groups…"), self.edit_room_groups)
        menu.exec(global_pos)

    def _rename_room(self, seg_id, name):
        new_name, ok = QInputDialog.getText(self, tr("Rename room"), tr("New name:"), text=name)
        new_name = new_name.strip()
        if ok and new_name and new_name != name and self.client is not None:
            self.client.rename_segment(seg_id, new_name)

    def _join_rooms(self, seg_a, name_a, seg_b, name_b):
        answer = QMessageBox.question(
            self, tr("Join rooms"),
            tr("Join “{a}” and “{b}” into one room?").format(a=name_a, b=name_b),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.client is not None:
            self.rooms_ctl.uncheck({seg_a, seg_b})
            self.client.join_segments(seg_a, seg_b)

    def _update_rooms_button(self):
        """Shown when the robot knows its rooms; says how many are ticked."""
        supported = self.capabilities is None or "MapSegmentationCapability" in self.capabilities
        n = len(self._checked_rooms)
        self.btn_rooms.setVisible(bool(self._segments) and supported)
        self.btn_rooms.setText(tr("Clean room(s)"))
        self.btn_rooms.setEnabled(self.client is not None and n > 0)
        self.btn_rooms.setToolTip(tr("Tick rooms above, then click here.") if n == 0
                                  else tr("Clean the {n} ticked room(s).").format(n=n))

    def _clean_rooms(self, *_):
        ids = self.checked_room_ids()
        if self.client is not None and ids:
            self.client.clean_segments(ids)

    def checked_room_ids(self):
        """Ticked rooms, in list order."""
        return self.rooms_ctl.checked_ids()

    def _sync_run_button(self, *_):
        action = self._current_command()
        self.btn_run.setEnabled(action is not None and action.isEnabled())
        self.btn_run.setToolTip(action.toolTip() if action is not None else "")

    def _run_command(self, *_):
        action = self._current_command()
        if action is not None and action.isEnabled():
            action.trigger()   # same as the menu entry (toggles if checkable)

    # -- client wiring ---------------------------------------------------------

    def attach(self, client):
        """Called by the plugin whenever its client is created (or dropped: None)."""
        self.client = client
        self.capabilities = None
        self._reachable = None
        self._update_log()   # the robot address may have changed
        self._update_console()
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
        client.mapPeeked.connect(self.update_map)
        client.hostInfoReceived.connect(self._on_host_info)
        client.timersReceived.connect(self._on_timers)
        client.timerPropertiesReceived.connect(self._on_timer_properties)
        client.commandDone.connect(lambda *_: QTimer.singleShot(1500, self.refresh))
        self._robot_text = ""
        self._version_text = ""
        self._wifi_html, self._wifi_tip = "", ""
        self._update_schedule()
        client.fetch_robot_info(quiet=True)
        client.fetch_version(quiet=True)
        if self.isVisible():
            self.refresh()
            self._timer.start()

    def _on_camera_light_clicked(self, checked):
        if self.client is not None:
            self.client.set_toggle("CameraLightControlCapability", checked)

    def _on_toggle(self, capability, enabled):
        if capability == "CameraLightControlCapability":
            self.camera_light.setChecked(enabled)   # setChecked does not emit clicked

    # -- schedule (Valetudo timers) -------------------------------------------------

    def _update_schedule(self):
        """Read the timers each time the Schedule tab is shown."""
        if self.client is None or not self.isVisible() \
                or self.tabs.currentWidget() is not self.tab_schedule:
            return
        self.client.fetch_timers()
        if self._timer_props is None:
            self.client.fetch_timer_properties()

    def _on_timer_properties(self, properties):
        self._timer_props = properties

    def _on_timers(self, timers):
        offset = utc_offset_minutes()
        self._timers = sorted(timers, key=lambda t: schedule.sort_key(t, offset))
        self._render_timers()

    def _days_text(self, days):
        days = set(days)
        if len(days) == 7:
            return tr("Every day")
        if days == {1, 2, 3, 4, 5}:
            return tr("Weekdays")
        if days == {0, 6}:
            return tr("Weekends")
        names = day_names()
        return " ".join(names[d] for d in sorted(days, key=lambda d: (d - 1) % 7))

    def _cleaning_text(self, timer):
        action = timer.get("action") or {}
        params = action.get("params") or {}
        if action.get("type") == "segment_cleanup":
            text = ", ".join(self.rooms_ctl.name(i) for i in params.get("segment_ids") or [])
            if int(params.get("iterations") or 1) > 1:
                text += f" ×{int(params['iterations'])}"
        elif action.get("type") == "full_cleanup":
            text = tr("Whole home")
        else:
            text = action.get("type") or "?"
        labels = preset_labels()
        extras = [labels.get(v, v) for v in schedule.pre_action_values(timer).values() if v]
        return " · ".join([text] + extras)

    def _render_timers(self):
        offset = utc_offset_minutes()
        selected = self._selected_timer_id()
        self.timers.blockSignals(True)
        self.timers.clear()
        for timer in self._timers:
            days, hour, minute = schedule.local_schedule(timer, offset)
            item = QTreeWidgetItem([timer.get("label") or tr("(no name)"), self._days_text(days),
                                    f"{hour:02d}:{minute:02d}", self._cleaning_text(timer)])
            item.setData(0, Qt.ItemDataRole.UserRole, timer.get("id"))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                          | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemNeverHasChildren)
            item.setCheckState(0, Qt.CheckState.Checked if timer.get("enabled")
                               else Qt.CheckState.Unchecked)
            item.setToolTip(3, item.text(3))
            self.timers.addTopLevelItem(item)
            if timer.get("id") == selected:
                item.setSelected(True)
        self.timers.blockSignals(False)
        for column in range(3):
            self.timers.resizeColumnToContents(column)
        self.lbl_timers_note.setText(
            tr("Run by the robot itself, even when QGIS is closed. Local times ({offset}).")
            .format(offset=format_offset(offset)) if self.client is not None
            else tr("Not connected."))
        self._update_timer_buttons()

    def _selected_timer_id(self):
        items = self.timers.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selected_timer(self):
        timer_id = self._selected_timer_id()
        return next((t for t in self._timers if t.get("id") == timer_id), None)

    def _update_timer_buttons(self, *_):
        connected = self.client is not None
        selected = self._selected_timer() is not None
        self.btn_timer_new.setEnabled(connected)
        for button in (self.btn_timer_edit, self.btn_timer_delete, self.btn_timer_run):
            button.setEnabled(connected and selected)

    def _on_timer_item_changed(self, item, column):
        """The checkbox turns a timer on or off (saved on the robot at once)."""
        timer_id = item.data(0, Qt.ItemDataRole.UserRole)
        timer = next((t for t in self._timers if t.get("id") == timer_id), None)
        enabled = item.checkState(0) == Qt.CheckState.Checked
        if column != 0 or timer is None or self.client is None \
                or bool(timer.get("enabled")) == enabled:
            return
        timer["enabled"] = enabled
        self.client.save_timer(timer)

    def _open_timer_dialog(self, timer):
        dialog = TimerDialog(self, timer, self._segments, getattr(self, "_room_groups", []),
                             self.client, self.capabilities, self._timer_props)
        if dialog.exec() and self.client is not None:
            self.client.save_timer(dialog.timer())

    def _new_timer(self, *_):
        if self.client is not None:
            self._open_timer_dialog(schedule.new_timer())

    def _edit_timer(self, *_):
        timer = self._selected_timer()
        if timer is not None and self.client is not None:
            self._open_timer_dialog(dict(timer))

    def _delete_timer(self, *_):
        timer = self._selected_timer()
        if timer is None or self.client is None:
            return
        name = timer.get("label") or tr("(no name)")
        if QMessageBox.question(
                self, tr("Delete scheduled cleaning"),
                tr("Delete “{name}” from the robot?").format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.client.delete_timer(timer["id"])

    def _run_timer(self, *_):
        timer = self._selected_timer()
        if timer is None or self.client is None:
            return
        name = timer.get("label") or tr("(no name)")
        if QMessageBox.question(
                self, tr("Run scheduled cleaning now"),
                tr("Start “{name}” now?").format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.client.run_timer(timer["id"])

    # -- SSH consoles ---------------------------------------------------------------

    @staticmethod
    def _ssh_target():
        """(host, user, port) of the robot from the settings, or None without an address."""
        cfg = load_settings()
        host = QUrl(cfg["url"]).host() if cfg["url"] else ""
        return (host, cfg["ssh_user"] or "root", int(cfg["ssh_port"])) if host else None

    @staticmethod
    def _pi_target():
        """(host, user, port) of the Raspberry Pi, or None when none is set."""
        cfg = load_settings()
        return (cfg["pi_host"], cfg["pi_user"], int(cfg["pi_port"])) if cfg["pi_host"] else None

    def _update_pi_tab(self):
        """The Pi console tab and header block exist only when a Pi address is set;
        the block is read while the panel is visible."""
        has_pi = self._pi_target() is not None
        index = self.tabs.indexOf(self.tab_pi_console)
        if hasattr(self.tabs, "setTabVisible"):   # Qt >= 5.15
            self.tabs.setTabVisible(index, has_pi)
        self.pi_header.setVisible(has_pi)
        if has_pi and self.isVisible():
            if not self._pi_timer.isActive():
                self._pi_timer.start()
                self._refresh_pi()
        else:
            self._pi_timer.stop()
            self.pi_runner.stop()
        if not has_pi:
            self._pi, self._pi_ok, self._pi_last_ok = None, None, None

    # -- Raspberry Pi block ---------------------------------------------------------

    def _refresh_pi(self, *_):
        target = self._pi_target()
        if target is None or self.pi_runner.is_busy():
            return
        self.pi_runner.run("pi_info", *target, host_info.PI_COMMAND)
        if self._pi_ok is None:
            self.lbl_pi_connection.setText(
                f"<span style='color:#9e9e9e'>●</span> {tr('Connecting…')}")

    def _on_pi_info(self, _operation, ok, output, detail):
        if ok:
            self._pi = host_info.parse_pi(output, time.time())
            self._pi_ok, self._pi_last_ok = True, time.monotonic()
        else:
            self._pi_ok = False
            self.lbl_pi_connection.setToolTip(detail)
        self._update_pi_header()

    def _update_pi_header(self):
        if self._pi_ok is None:
            return
        if self._pi_ok:
            seconds = int(time.monotonic() - self._pi_last_ok)
            text = tr("Connected · updated {seconds} s ago").format(seconds=seconds)
            self.lbl_pi_connection.setText(f"<span style='color:#2e7d32'>●</span> {text}")
            self.lbl_pi_connection.setToolTip("")
        else:
            text = tr("Unreachable over SSH")
            self.lbl_pi_connection.setText(f"<span style='color:#c62828'>●</span> {text}")
        pi = self._pi or {}
        self.lbl_pi_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_pi_name.setText(" · ".join(p for p in (pi.get("hostname"), pi.get("uname")) if p))
        line, wrong = host_info.info_line(pi.get("ip") or (self._pi_target() or [""])[0],
                                          pi.get("time"), pi.get("received_at"),
                                          pi.get("uptime"), self._local_time)
        self.lbl_pi_info.setText(line)
        self.lbl_pi_info.setStyleSheet("color: #ef6c00;" if wrong else "")

    @staticmethod
    def _local_time(epoch):
        return QDateTime.fromSecsSinceEpoch(int(epoch)).toString("dd/MM/yyyy HH:mm")

    def settings_changed(self):
        """Called by the plugin after the Options page saved changes."""
        self._update_console()

    def _update_console(self):
        self._update_pi_tab()
        for console in self.consoles:
            console.update(self.isVisible(), self.tabs.currentWidget())

    def _update_camera(self):
        """Play while the panel is visible and the Camera tab is shown; keep playing
        CAMERA_GRACE_MS after that, so that a quick return is instant."""
        if self.isVisible() and self.tabs.currentWidget() is self.camera_page:
            self._camera_grace.stop()
            if not self.camera.stream.is_running():
                self.camera.play()
        elif self.camera.stream.is_running() and not self._camera_grace.isActive():
            self._camera_grace.start()

    # -- robot log ------------------------------------------------------------------

    def _update_log(self):
        """Follow the log only while the panel is visible and the Log tab is shown.

        The robot address and SSH user/port come from the settings; a change
        there reconnects (start() ignores an unchanged target)."""
        cfg = load_settings()
        host = QUrl(cfg["url"]).host() if cfg["url"] else ""
        if self.isVisible() and self.tabs.currentWidget() is self.tab_log:
            if not host:
                self.log_tail.stop(quiet=True)
                self.lbl_log_status.setText(tr("No robot configured."))
                return
            self.log_tail.start(host, cfg["ssh_user"], cfg["ssh_port"])
        else:
            self.log_tail.stop()

    def _on_log_state(self, state, detail):
        colors = {"following": "#2e7d32", "failed": "#c62828", "ssh_missing": "#c62828"}
        texts = {
            "connecting": tr("Connecting to {host} over SSH…").format(host=detail),
            "following": tr("Following {path} on {host}.").format(path=LOG_PATH, host=detail),
            "failed": tr("SSH connection lost or refused: {error}. Retrying in 10 s…")
                .format(error=detail),
            "ssh_missing": tr("ssh was not found: install an SSH client."),
            "stopped": tr("Shown while this tab is open."),
        }
        self.lbl_log_status.setStyleSheet(f"color: {colors[state]};" if state in colors else "")
        self.lbl_log_status.setText(texts.get(state, state))
        if state in ("failed", "ssh_missing"):
            self.lbl_log_status.setToolTip(tr("Needs key-based SSH login to the robot "
                                              "(ssh-copy-id root@<robot>), as for the reboot."))

    def _on_log_lines(self, lines):
        bar = self.txt_log.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        keep = None if at_bottom or self.chk_log_follow.isChecked() else bar.value()
        for line in lines:
            self.txt_log.appendHtml(_log_line_html(line))
        if keep is None:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(keep)   # reading older lines: do not jump

    def _on_log_follow_toggled(self, checked):
        if checked:
            bar = self.txt_log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def clear_boot_log(self):
        self.txt_boot.clear()

    def add_boot_log(self, line):
        self.txt_boot.appendPlainText(line)

    def shutdown(self):
        """Called by the plugin on unload."""
        self._camera_grace.stop()
        self.camera.shutdown()
        self._pi_timer.stop()
        self.pi_runner.stop()
        self.log_tail.stop(quiet=True)
        for console in self.consoles:
            console.shutdown()

    def _on_visibility(self, visible):
        self._update_camera()
        self._update_log()
        self._update_console()
        self._update_schedule()
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

    def refresh(self, *_):
        client = self.client
        if client is None:
            return
        client.fetch_attributes(quiet=True)
        client.fetch_events(quiet=True)
        client.fetch_host_info(quiet=True)
        # Position comes from the map: read it unless live tracking just delivered one.
        if time.monotonic() - self._last_map >= self._timer.interval() / 1000 * 0.9:
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

    def _on_preset_chosen(self, capability, index):
        combo = self.preset_combos[capability]
        name = combo.itemData(index)
        if self.client is not None and name:
            self.client.set_preset(capability, name)

    # -- header ------------------------------------------------------------------

    def _show_disconnected(self):
        self.lbl_connection.setText(f"<span style='color:#9e9e9e'>●</span> {tr('Not connected')}")
        self.lbl_robot.setText("")
        self.lbl_robot.setToolTip("")
        self._wifi_html, self._wifi_tip = "", ""
        self._robot_ip, self._host = "", {}
        self.lbl_robot_info.setText("")

    def _on_reachable(self, ok):
        self._reachable = ok
        if ok and self.client is not None and not self._robot_text:
            self.client.fetch_robot_info(quiet=True)   # robot was off when we connected
            self.client.fetch_version(quiet=True)
        if ok:
            self._last_ok = time.monotonic()
            self._last_ok_clock = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._update_header()

    def _update_header(self):
        self._update_pi_header()
        if self.client is None or self._reachable is None:
            return
        if self._reachable:
            seconds = int(time.monotonic() - (self._last_ok or time.monotonic()))
            text = tr("Connected · updated {seconds} s ago").format(seconds=seconds)
            self.lbl_connection.setText(f"<span style='color:#2e7d32'>●</span> {text}")
        else:
            text = tr("Unreachable · last update {time}").format(
                time=self._last_ok_clock or "—")
            self.lbl_connection.setText(f"<span style='color:#c62828'>●</span> {text}")

    def _on_robot_info(self, info):
        self._robot_text = " ".join(
            p for p in (info.get("manufacturer"), info.get("modelName")) if p)
        self._update_robot_label()

    def _on_version(self, version):
        release = version.get("release")
        self._version_text = f"Valetudo {release}" if release else ""
        self._update_robot_label()

    def _on_host_info(self, info):
        self._host = info or {}
        self._update_robot_info()

    def _update_robot_info(self):
        """Third header line: robot IP · robot's own date and time · uptime."""
        host = self._host
        ip = self._robot_ip or ((self._ssh_target() or [""])[0])
        line, wrong = host_info.info_line(ip, host.get("robot_time"), host.get("received_at"),
                                          host.get("uptime"), self._local_time)
        self.lbl_robot_info.setText(line)
        self.lbl_robot_info.setStyleSheet("color: #ef6c00;" if wrong else "")
        self.lbl_robot_info.setToolTip(
            tr("The robot's clock is wrong: check Valetudo's NTP settings.") if wrong else "")

    def _update_robot_label(self):
        """Second header line: robot model · Valetudo version · Wi-Fi signal."""
        parts = [html.escape(p) for p in (self._robot_text, self._version_text) if p]
        if self._wifi_html:
            parts.append(self._wifi_html)
        self.lbl_robot.setText(" · ".join(parts))
        self.lbl_robot.setToolTip(self._wifi_tip)

    # -- data --------------------------------------------------------------------

    def _on_capabilities(self, capabilities):
        self.capabilities = set(capabilities)
        caps = self.capabilities
        self.chk_goto_quiet.setVisible("GoToLocationCapability" not in caps
                                       and "ZoneCleaningCapability" in caps)

        any_preset = False
        for capability, combo in self.preset_combos.items():
            supported = capability in caps
            _set_row_visible(self.settings_form, combo, supported)
            any_preset |= supported
            if supported:
                self.client.fetch_presets(capability, quiet=True)
        self.box_settings.setVisible(any_preset)
        self.box_consumables.setVisible("ConsumableMonitoringCapability" in caps)
        self.box_current.setVisible("CurrentStatisticsCapability" in caps)
        self.box_total.setVisible("TotalStatisticsCapability" in caps)

        labels = _capability_labels()
        name = lambda c: labels.get(c) or _humanize(c)
        lines = [f"✓ {n}" for n in sorted(name(c) for c in caps)]
        lines += [f"✗ {name(c)}" for c in CORE_CAPABILITIES if c not in caps]
        if self.camera_light.isVisibleTo(self) != ("CameraLightControlCapability" in caps):
            self.camera_light.setVisible("CameraLightControlCapability" in caps)
        if "CameraLightControlCapability" in caps:
            self.client.fetch_toggle("CameraLightControlCapability")
        self.lbl_features.setText("\n".join(lines))
        self._update_rooms_button()
        if self.isVisible():   # nothing is fetched while the panel is hidden
            self.refresh()
            self._timer.start()

    def _on_presets(self, capability, presets):
        combo = self.preset_combos.get(capability)
        if combo is None:
            return
        current = combo.currentData()
        combo.clear()
        labels = preset_labels()
        for name in presets:
            combo.addItem(labels.get(name, name), name)
        if current is not None:
            combo.setCurrentIndex(max(0, combo.findData(current)))

    def _on_attributes(self, attributes):
        states, flags = _state_labels(), _flag_labels()
        attachments = []
        dock_value = None
        components = {}
        error_text = ""
        state = None
        for attr in attributes:
            cls = attr.get("__class")
            if cls == "StatusStateAttribute":
                state = attr.get("value")
                flag = attr.get("flag")
                text = _label(states, state)
                if flag and flag != "none":
                    text += f" ({_label(flags, flag)})"
                self.lbl_state.setText(text)
                self._set_badge(state)
                err = attr.get("error") or {}
                error_text = (err.get("message") if isinstance(err, dict) else "") \
                    or (attr.get("metaData") or {}).get("error_description", "")
                if state != "error" and not err:
                    error_text = ""
            elif cls == "BatteryStateAttribute":
                level = int(attr.get("level") or 0)
                flag = attr.get("flag")
                self.bar_battery.setValue(level)
                suffix = f" · {_label(flags, flag)}" if flag and flag != "none" else ""
                self.bar_battery.setFormat(f"{level} %{suffix}")
            elif cls == "PresetSelectionStateAttribute":
                for capability, ptype in PRESET_ROWS.items():
                    if attr.get("type") == ptype:
                        combo = self.preset_combos[capability]
                        index = combo.findData(attr.get("value"))
                        if index >= 0:
                            combo.setCurrentIndex(index)
            elif cls == "AttachmentStateAttribute":
                name = _label(_attachment_labels(), attr.get("type"))
                attachments.append(f"{name} {'✓' if attr.get('attached') else '✗'}")
            elif cls == "DockStatusStateAttribute":
                dock_value = attr.get("value")
            elif cls == "DockComponentStateAttribute":
                components[attr.get("type")] = attr.get("value")

        _set_row_visible(self.status_form, self.lbl_dock, dock_value is not None)
        self.lbl_dock.setText(_label(states, dock_value))
        self.lbl_error.setVisible(bool(error_text))
        self.lbl_error.setText(f"⚠ {error_text}" if error_text else "")
        _set_row_visible(self.status_form, self.lbl_attachments, bool(attachments))
        self._update_dock_components(components)
        self.lbl_attachments.setText("   ".join(attachments))

        self._timer.setInterval(ACTIVE_INTERVAL_MS if state in ACTIVE_STATES
                                else IDLE_INTERVAL_MS)

    def _update_dock_components(self, components):
        """One row per dock component; problems (missing/empty/full) in red with advice."""
        form = self.dock_form
        while form.rowCount():
            form.removeRow(0)
        self.box_dock.setVisible(bool(components))
        names, values, advice = (dock_component_labels(), dock_component_values(),
                                 dock_component_advice())
        order = DOCK_COMPONENT_ORDER + sorted(c for c in components
                                              if c not in DOCK_COMPONENT_ORDER)
        for component in order:
            if component not in components:
                continue
            value = components[component]
            label = QLabel(_label(values, value))
            name = _label(names, component)
            if value in DOCK_COMPONENT_PROBLEMS:
                name = f"{name} ⚠"
                label.setStyleSheet("color: #c62828; font-weight: bold;")
                label.setToolTip(advice[value])
                label.setText(f"{label.text()} · {advice[value]}")
            elif value == "ok":
                label.setStyleSheet("color: #2e7d32;")
            form.addRow(name, label)

    def _on_consumables(self, consumables):
        form = self.consumables_form
        while form.rowCount():
            form.removeRow(0)
        for item in consumables:
            remaining = item.get("remaining") or {}
            value, unit = remaining.get("value"), remaining.get("unit")
            if value is None:
                continue
            label = _consumable_label(item.get("type"), item.get("subType"))
            if unit == "percent":
                widget = QProgressBar()
                widget.setRange(0, 100)
                widget.setValue(int(value))
                widget.setFormat(f"{int(value)} %")
                low = value < LOW_PERCENT
            else:  # minutes
                widget = QLabel(tr("{hours} h left").format(hours=int(value) // 60))
                low = value < LOW_MINUTES
            if low:
                label = f"{label} ⚠"
                widget.setToolTip(tr("Replace soon"))
            form.addRow(label, widget)

    @staticmethod
    def _stats(items):
        return {s.get("type"): s.get("value") for s in items if isinstance(s, dict)}

    def _on_current_statistics(self, items):
        stats = self._stats(items)
        self.lbl_cur_time.setText(_format_duration(stats["time"]) if "time" in stats else "—")
        self.lbl_cur_area.setText(_format_area_cm2(stats["area"]) if "area" in stats else "—")

    def _on_total_statistics(self, items):
        stats = self._stats(items)
        self.lbl_tot_count.setText(str(stats["count"]) if "count" in stats else "—")
        self.lbl_tot_time.setText(_format_duration(stats["time"]) if "time" in stats else "—")
        self.lbl_tot_area.setText(_format_area_cm2(stats["area"]) if "area" in stats else "—")

    def _on_wifi(self, wifi):
        """Wi-Fi signal in the header, coloured with the Wi-Fi survey thresholds;
        network name, band and address in its tooltip."""
        details = (wifi or {}).get("details") or {}
        signal = details.get("signal")
        if signal is None:
            self._wifi_html, self._wifi_tip = "", ""
        else:
            cfg = load_settings()
            if signal >= cfg["wifi_good_dbm"]:
                color = "#2e7d32"
            elif signal >= cfg["wifi_fair_dbm"]:
                color = "#9e9d24"
            elif signal > cfg["wifi_bad_dbm"]:
                color = "#ef6c00"
            else:
                color = "#c62828"
            text = tr("Wi-Fi {signal} dBm").format(signal=signal)
            self._wifi_html = f"<span style='color:{color}'>{html.escape(text)}</span>"
            parts = [details.get("ssid"), details.get("frequency"),
                     (details.get("ips") or [None])[0]]
            self._robot_ip = (details.get("ips") or [""])[0] or ""
            self._update_robot_info()
            self._wifi_tip = tr("Wi-Fi: {details}").format(
                details=" · ".join(str(p) for p in parts if p) or "—")
        self._update_robot_label()

    def _on_events(self, events):
        self.list_events.clear()
        events = sorted((e for e in events if isinstance(e, dict)),
                        key=lambda e: e.get("timestamp") or "", reverse=True)[:MAX_EVENTS]
        if not events:
            self.list_events.addItem(tr("No recent events."))
            return
        for event in events:
            stamp = _format_time(event.get("timestamp"))
            self.list_events.addItem(f"{stamp}  {_event_label(event)}".strip())

    def update_map(self, map_json):
        """Called with each map: from the plugin (show map / live tracking) or peeked."""
        self._last_map = time.monotonic()
        robot = dock = None
        for ent in map_json.get("entities", []):
            pts = ent.get("points") or []
            if len(pts) < 2:
                continue
            if ent.get("type") == "robot_position":
                robot = (pts[0], pts[1], (ent.get("metaData") or {}).get("angle"))
            elif ent.get("type") == "charger_location":
                dock = (pts[0], pts[1])
        if robot is None:
            return
        x, y, angle = robot
        text = tr("x {x} cm · y {y} cm · heading {angle}°").format(
            x=round(x), y=round(y), angle=round(angle) if angle is not None else "?")
        if dock is not None:
            distance = math.hypot(x - dock[0], y - dock[1]) / 100
            text += "\n" + tr("{distance} m from the dock").format(distance=f"{distance:.1f}")
        self.lbl_position.setText(text)
