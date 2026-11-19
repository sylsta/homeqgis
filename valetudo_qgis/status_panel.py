"""Dockable status panel: robot state, settings, statistics, consumables...

The panel refreshes itself while it is visible (every 5 s while the robot is
working, every 30 s otherwise), independently of live map tracking. Sections
the robot does not support stay hidden.
"""

import html
import math
import re
import time

from qgis.PyQt.QtCore import QDateTime, QEvent, Qt, QTime, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QKeySequence, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QTimeEdit,
    QHBoxLayout,
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

try:
    from qgis.PyQt.QtGui import QShortcut   # Qt 6
except ImportError:
    from qgis.PyQt.QtWidgets import QShortcut   # Qt 5
from qgis.gui import QgsDockWidget

from .camera_widget import CameraWidget
from . import room_groups
from .i18n import tr
from . import host_info
from .icons import APP_ICON, HA_LOGO, KODI_ICON, LOGO, NUC_ICON, RPI_LOGO, icon
from .robot_survey import RobotSurvey
from .ssh_host_block import SshHostBlock
from .kodi_block import KodiBlock
from .kodi_client import rpc_url as kodi_rpc_url
from . import system_terminal
from .log_tab import LogTab
from .log_tail import COMMAND_PREFIX, LOG_PATH
from .panel_widgets import Sparkline, VideoWindow, badge_icon, signal_color
from .schedule_view import WeekView
from . import schedule
from .rooms_tree import RoomsTree
from .settings import (PLUGIN_NAME, KEY_ADVANCED, HA_SSH_PASSWORD_SETTING, KODI_PASSWORD_SETTING, NUC_AUTO_LOG_COMMAND, has_ha_token, has_secret, ha_token,
                       load_settings, secret)
from . import ssh_auth
from .ha_client import UNAUTHORISED, HomeAssistantClient, parse_timestamp
from .console_tab import ConsoleTab
from .timer_dialog import TimerDialog, day_names, format_offset, utc_offset_minutes
from .ui_loader import load_ui, set_row_visible as _set_row_visible

KEY_TAB = "valetudo/panel_tab"
KEY_TERMINAL = "valetudo/panel_terminal"     # "robot/console", "pi/log"…
PI_LOG_PATH = "valetudo/collect.log"         # the Pi collector's log (README's cron line)
KEY_COMPACT = "valetudo/panel_compact"       # compact mode: strip and big button only
KEY_ONCE_TIMERS = "valetudo/once_timers"     # "label|due Unix time" of one-off cleanings
ONCE_GRACE_S = 3600                          # deleted an hour after their start time
KEY_GOTO_QUIET = "valetudo/goto_quiet"   # "Go to" without cleaning (emulated go-to only)
KEY_PI_MAP_FULL = "valetudo/pi_map_full"   # "Load Wi-Fi map from the Pi": all runs

# Layout: ui/status_panel.ui (Qt Designer). The code fills it at run time and
# relies on these object names.
UI_WIDGETS = (
    # strip, details, action bar
    "strip", "strip_layout", "lbl_logo", "lbl_badge", "bar_battery", "lbl_wifi_strip", "lbl_job",
    "btn_warning", "sep_pi", "lbl_pi_strip_logo", "lbl_pi_strip",
    "sep_ha", "lbl_ha_strip_logo", "lbl_ha_strip", "btn_menu",
    "lbl_details_logo", "lbl_badge_details", "bar_battery_details",
    "ha_header", "lbl_ha_logo", "lbl_ha_connection", "lbl_ha_name",
    "lbl_ha_info", "nuc_header", "lbl_nuc_logo", "lbl_nuc_connection",
    "lbl_nuc_name", "lbl_nuc_info", "lbl_nuc_resources",
    "kodi_header", "lbl_kodi_logo", "lbl_kodi_connection",
    "lbl_kodi_name", "lbl_kodi_info", "kodi_play_row", "lbl_kodi_playing",
    "bar_kodi_progress", "btn_kodi_play", "btn_kodi_stop", "details", "header_layout", "lbl_connection",
    "btn_robot_web", "btn_robot_ssh", "btn_pi_web", "btn_pi_ssh", "btn_ha_web", "btn_ha_ssh",
    "btn_nuc_web", "btn_nuc_ssh", "btn_kodi_web", "btn_kodi_ssh",
    "lbl_robot", "lbl_robot_info", "pi_header", "lbl_pi_logo", "lbl_pi_connection",
    "lbl_pi_name", "lbl_pi_info", "action_layout", "btn_primary",
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
    "tab_pi_console", "lbl_pi_console_status", "btn_pi_console_connect",
    "btn_pi_console_clear", "txt_pi_console", "lbl_pi_console_prompt", "edit_pi_console",
    "btn_pi_console_run", "btn_pi_console_stop",
    "tab_log", "lbl_log_status", "chk_log_follow", "btn_log_clear", "txt_log",
    "tab_pi_log", "lbl_pi_log_status", "chk_pi_log_follow", "btn_pi_log_clear", "txt_pi_log",
    "tab_ha_console", "lbl_ha_console_status", "btn_ha_console_connect",
    "btn_ha_console_clear", "txt_ha_console", "lbl_ha_console_prompt", "edit_ha_console",
    "btn_ha_console_run", "btn_ha_console_stop",
    "tab_ha_log", "lbl_ha_log_status", "chk_ha_log_follow", "btn_ha_log_clear", "txt_ha_log",
    "tab_nuc_console", "lbl_nuc_console_status", "btn_nuc_console_connect",
    "btn_nuc_console_clear", "txt_nuc_console", "lbl_nuc_console_prompt", "edit_nuc_console",
    "btn_nuc_console_run", "btn_nuc_console_stop",
    "tab_nuc_log", "lbl_nuc_log_status", "chk_nuc_log_follow", "btn_nuc_log_clear", "txt_nuc_log",
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
ACTIVE_INTERVAL_MS = 5_000
IDLE_INTERVAL_MS = 30_000
SERVERS = ("robot", "pi", "ha", "nuc", "kodi")   # frames of the Status tab


TERMINAL_DEVICES = ("robot", "pi", "ha", "nuc")   # with a console and a log in QGIS


def _device_name(key):
    return {"robot": tr("Robot"), "pi": tr("Raspberry Pi"), "ha": "Home Assistant",
            "nuc": "NUC", "kodi": "Kodi"}.get(key, "")
PI_INTERVAL_MS = 30_000    # Pi block refresh (one short SSH command) while visible
HA_INTERVAL_MS = 60_000    # Home Assistant check (one GET) while visible
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
    piMapRequested = pyqtSignal(bool)       # Wi-Fi tab: load the Pi's map (True: full map)
    summaryChanged = pyqtSignal(str)        # one-line status (HTML) for the map overlay
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

        # -- Status tab: robot, Raspberry Pi, Home Assistant -----------------------------
        self.lbl_pi_logo.setPixmap(icon(RPI_LOGO).pixmap(20, 20))
        self.pi_runner = RobotSurvey(self)   # one-shot SSH runner
        # NUC: a server read over SSH (ssh_host_block), shown only when set
        self.lbl_nuc_logo.setPixmap(icon(NUC_ICON).pixmap(20, 20))
        self.nuc = SshHostBlock(
            {"header": self.nuc_header, "connection": self.lbl_nuc_connection,
             "name": self.lbl_nuc_name,
             "info": self.lbl_nuc_info, "resources": self.lbl_nuc_resources},
            self._nuc_target, lambda epoch: self._local_time(epoch),
            lambda wrong: self._set_problem(
                "nuc_clock", tr("The NUC's clock is wrong.") if wrong else None), self)
        # Kodi: read over its JSON-RPC (kodi_block), shown only when set
        self.lbl_kodi_logo.setPixmap(icon(KODI_ICON).pixmap(20, 20))
        self.kodi = KodiBlock(
            {"header": self.kodi_header, "connection": self.lbl_kodi_connection,
             "name": self.lbl_kodi_name,
             "info": self.lbl_kodi_info, "play_row": self.kodi_play_row,
             "playing": self.lbl_kodi_playing, "progress": self.bar_kodi_progress,
             "play": self.btn_kodi_play, "stop": self.btn_kodi_stop},
            self._kodi_settings, self)
        # Each server's frame: 🌐 its web interface (system browser), >_ SSH (system terminal)
        self._terminal_entries = []   # "Console / Log in QGIS": advanced tools
        for prefix in SERVERS:
            web, ssh = getattr(self, f"btn_{prefix}_web"), getattr(self, f"btn_{prefix}_ssh")
            web.setIcon(icon("web"))
            ssh.setIcon(icon("tab_terminal"))
            web.clicked.connect(lambda _=False, p=prefix: self.open_web(p))
            ssh.clicked.connect(lambda _=False, p=prefix: self.open_ssh(p))
            if prefix in TERMINAL_DEVICES:
                # Click: the system terminal; its arrow: the console or log in QGIS
                menu = QMenu(ssh)
                menu.addAction(icon("tab_terminal"), tr("Terminal window"),
                               lambda p=prefix: self.open_ssh(p))
                self._terminal_entries += [
                    menu.addAction(tr("Console in QGIS"),
                                   lambda p=prefix: self.open_terminal(p, "console")),
                    menu.addAction(tr("Log in QGIS"),
                                   lambda p=prefix: self.open_terminal(p, "log"))]
                ssh.setMenu(menu)
                ssh.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.pi_runner.finished.connect(self._on_pi_info)
        self._pi_timer = QTimer(self)
        self._pi_timer.setInterval(PI_INTERVAL_MS)
        self._pi_timer.timeout.connect(self._refresh_pi)
        self.lbl_pi_strip_logo.setPixmap(icon(RPI_LOGO).pixmap(16, 16))
        self.lbl_ha_strip_logo.setPixmap(icon(HA_LOGO).pixmap(16, 16))
        for name in ("sep_pi", "lbl_pi_strip_logo", "lbl_pi_strip",
                     "sep_ha", "lbl_ha_strip_logo", "lbl_ha_strip"):
            getattr(self, name).setVisible(False)
        self.lbl_details_logo.setPixmap(icon(LOGO).pixmap(20, 20))
        self.lbl_ha_logo.setPixmap(icon(HA_LOGO).pixmap(20, 20))
        self.ha_header.setVisible(False)
        self._ha_client = None
        self._ha_token = None        # read (decrypted) once, when first needed
        self._ha_state = None        # None (hidden), "connecting", "online", "no_token", "offline"
        self._ha = {}                # url, name, version, time zone, clock, start, error
        self._ha_last_ok = None      # time.monotonic() of the last answer
        self._ha_last_ok_clock = ""
        self._ha_timer = QTimer(self)
        self._ha_timer.setInterval(HA_INTERVAL_MS)
        self._ha_timer.timeout.connect(self._refresh_ha)
        self._set_badge(None)
        self.lbl_error.setVisible(False)

        # -- the big button: Start / Pause / Resume, after the robot's state ------------
        self._state = None
        self.btn_primary.clicked.connect(self._on_primary)
        self._update_primary()

        # -- Clean -------------------------------------------------------------------------
        # Rooms in a checkable tree: "All rooms" (tri-state) above one checkbox per
        # room. Right-click a room to rename, join or split it.
        self.rooms_ctl = RoomsTree(self.rooms, expanded_key="valetudo/room_group_open")
        self.rooms_ctl.checkedChanged.connect(self._update_rooms_button)
        self.rooms.customContextMenuRequested.connect(self._on_rooms_context_menu)
        self.rooms.setVisible(False)
        self.rooms.setDragEnabled(True)   # a group can be dropped on the week view
        self.rooms.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.btn_rooms.setIcon(icon("clean_rooms"))
        self.btn_rooms.clicked.connect(self._clean_rooms)
        self.btn_rooms.setVisible(False)
        self._segments = []
        # Shown only for robots whose "Go to" is a small cleaning job (no native go-to).
        self.chk_goto_quiet.setChecked(QgsSettings().value(KEY_GOTO_QUIET, True, type=bool))
        self.chk_goto_quiet.toggled.connect(
            lambda checked: QgsSettings().setValue(KEY_GOTO_QUIET, checked))
        self.chk_goto_quiet.setVisible(False)
        self.preset_combos = {"FanSpeedControlCapability": self.combo_fan_speed,
                              "WaterUsageControlCapability": self.combo_water_usage,
                              "OperationModeControlCapability": self.combo_operation_mode}
        for capability, combo in self.preset_combos.items():
            combo.activated.connect(lambda index, c=capability: self._on_preset_chosen(c, index))

        # -- Wi-Fi ---------------------------------------------------------------------------
        self.sparkline = Sparkline()
        self.sparkline_layout.addWidget(self.sparkline)
        cfg = load_settings()
        for name, key in (("spin_wifi_good", "wifi_good_dbm"), ("spin_wifi_fair", "wifi_fair_dbm"),
                          ("spin_wifi_bad", "wifi_bad_dbm")):
            spin = getattr(self, name)
            spin.setValue(int(cfg[key]))
            spin.valueChanged.connect(lambda value, k=key: self._on_threshold(k, value))
        self._update_thresholds()
        self.btn_pi_latest.clicked.connect(lambda: self.piMapRequested.emit(False))
        self.btn_pi_full.clicked.connect(lambda: self.piMapRequested.emit(True))
        self.lbl_pi_thumb.setVisible(False)

        # -- Camera: plays only while this tab is shown and the panel is visible ---------
        self.lbl_position.setText(tr("Waiting for the robot position…"))
        self.camera_page = self.tab_camera
        self.camera = CameraWidget()
        self.camera_layout.insertWidget(0, self.camera)
        # Coming back to the tab soon after leaving it shows the video at once,
        # instead of reconnecting and waiting for the robot's next full image.
        self._camera_grace = QTimer(self)
        self._camera_grace.setSingleShot(True)
        self._camera_grace.setInterval(CAMERA_GRACE_MS)
        self._camera_grace.timeout.connect(self._camera_grace_over)
        self.camera_light.setVisible(False)    # shown if the robot supports it
        self.camera_light.clicked.connect(self._on_camera_light_clicked)  # user only
        self.video_window = None
        self.btn_camera_full.setIcon(theme("/mActionZoomFullExtent.svg"))
        self.btn_camera_full.clicked.connect(self._show_video_window)
        snapshot = QShortcut(QKeySequence("Ctrl+Shift+S"), self.tab_camera)
        snapshot.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        snapshot.activated.connect(self.camera.save_snapshot)

        # -- Terminal: robot or Pi, console or log -----------------------------------------
        def console_widgets(p):
            return {"status": getattr(self, f"lbl_{p}console_status"),
                    "connect": getattr(self, f"btn_{p}console_connect"),
                    "clear": getattr(self, f"btn_{p}console_clear"),
                    "output": getattr(self, f"txt_{p}console"),
                    "prompt": getattr(self, f"lbl_{p}console_prompt"),
                    "edit": getattr(self, f"edit_{p}console"),
                    "run": getattr(self, f"btn_{p}console_run"),
                    "stop": getattr(self, f"btn_{p}console_stop")}

        def log_widgets(p):
            return {"status": getattr(self, f"lbl_{p}log_status"),
                    "follow": getattr(self, f"chk_{p}log_follow"),
                    "clear": getattr(self, f"btn_{p}log_clear"),
                    "output": getattr(self, f"txt_{p}log")}
        self.consoles = [
            ConsoleTab(self.tab_console, console_widgets(""), self._ssh_target,
                       tr("No robot configured."), self),
            ConsoleTab(self.tab_pi_console, console_widgets("pi_"), self._pi_target,
                       tr("No Raspberry Pi set in the settings."), self),
            ConsoleTab(self.tab_ha_console, console_widgets("ha_"), self._ha_ssh_target,
                       tr("No Home Assistant SSH address set in the settings."), self),
            ConsoleTab(self.tab_nuc_console, console_widgets("nuc_"), self._nuc_target,
                       tr("No NUC set in the settings."), self),
        ]
        self.logs = [
            LogTab(self.tab_log, log_widgets(""), self._ssh_target, LOG_PATH,
                   tr("No robot configured."), self),
            LogTab(self.tab_pi_log, log_widgets("pi_"), self._pi_target, PI_LOG_PATH,
                   tr("No Raspberry Pi set in the settings."), self),
            LogTab(self.tab_ha_log, log_widgets("ha_"), self._ha_ssh_target,
                   lambda: COMMAND_PREFIX + load_settings()["ha_log_command"],
                   tr("No Home Assistant SSH address set in the settings."), self),
            LogTab(self.tab_nuc_log, log_widgets("nuc_"), self._nuc_target,
                   lambda: COMMAND_PREFIX + (load_settings()["nuc_log_command"]
                                             or NUC_AUTO_LOG_COMMAND),
                   tr("No NUC set in the settings."), self),
        ]
        # The Terminal tab is opened on a server from its >_ menu in the Status tab,
        # and hidden again with its ✕.
        choice = QgsSettings().value(KEY_TERMINAL, "robot/console", type=str) or "robot/console"
        device, _, mode = str(choice).partition("/")
        self._term_device = device if device in TERMINAL_DEVICES else "robot"
        (self.btn_term_log if mode == "log" else self.btn_term_console).setChecked(True)
        for button in (self.btn_term_console, self.btn_term_log):
            button.toggled.connect(self._on_terminal_switch)
        self.btn_term_close.clicked.connect(self.close_terminal)
        self._show_terminal_page()

        # -- Schedule: Valetudo's timers (run by the robot); read when the tab is shown --
        self._timers, self._timer_props = [], None
        self.week = WeekView()
        self.week.drop_source = self.rooms
        self.week_layout.addWidget(self.week)
        self.week.timerClicked.connect(self._select_timer)
        self.week.timerDoubleClicked.connect(lambda timer_id: (self._select_timer(timer_id),
                                                               self._edit_timer()))
        self.week.slotDoubleClicked.connect(self._new_timer_at)
        self.week.groupDropped.connect(self._new_timer_for_group)
        self.timers.itemChanged.connect(self._on_timer_item_changed)
        self.timers.itemDoubleClicked.connect(lambda *_: self._edit_timer())
        self.timers.itemSelectionChanged.connect(self._update_timer_buttons)
        self.timers.itemSelectionChanged.connect(
            lambda: self.week.set_selected(self._selected_timer_id()))
        self.btn_timer_new.clicked.connect(self._new_timer)
        self.btn_timer_edit.clicked.connect(self._edit_timer)
        self.btn_timer_delete.clicked.connect(self._delete_timer)
        self.btn_timer_run.clicked.connect(self._run_timer)
        self.btn_tonight.clicked.connect(self._tonight)
        self.segmentsChanged.connect(lambda *_: self._render_timers())
        self._render_timers()

        # -- Sections remember whether they are open, under our own keys -----------------
        for name, key in SECTIONS.items():
            self._remember_section(getattr(self, name), key)

        # -- Side tabs: icons, their titles as tooltips; each page starts with its title
        self._tab_keys = [self.tabs.widget(i).objectName().removeprefix("tab_")
                          for i in range(self.tabs.count())]
        self._tab_icons = {}
        self._tab_titles = {}
        for i, key in enumerate(self._tab_keys):
            self._tab_icons[key] = icon(f"tab_{key}")
            title = self.tabs.tabText(i)
            self.tabs.setTabToolTip(i, title)
            self.tabs.setTabText(i, "")
            self.tabs.setTabIcon(i, self._tab_icons[key])
            self._tab_titles[key] = self._add_page_title(self.tabs.widget(i),
                                                         self._tab_icons[key], title)
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
        self._set_tab_shown("terminal", False)   # see open_terminal
        last = QgsSettings().value(KEY_TAB, "clean", type=str)
        last = {"care": "maintenance", "system": "maintenance", "terminal": "status"}.get(last, last)
        if last in self._tab_keys:
            self.tabs.setCurrentIndex(self._tab_keys.index(last))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._update_pi_tab()
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
        for badge in (self.lbl_badge, self.lbl_badge_details):
            badge.setText(text)
            badge.setStyleSheet(
                f"background-color: {color}; color: white; font-weight: bold;"
                "border-radius: 9px; padding: 2px 10px;")

    def _on_tab_changed(self, index):
        if 0 <= index < len(self._tab_keys):
            QgsSettings().setValue(KEY_TAB, self._tab_keys[index])
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
        # Action bar: [Dock] next to the big button
        if "home" in act:
            self._dock_button = self._button(act["home"])
            self._dock_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._dock_button.setMinimumHeight(34)
            self.action_layout.addWidget(self._dock_button)
        for key in ("start", "pause"):
            if key in act:
                act[key].changed.connect(self._update_primary)
        # Strip: [Show on map] then [⚙] Settings (icons only), before the ⋮ menu
        if "live" in act:
            live = QToolButton()
            live.setDefaultAction(act["live"])
            live.setAutoRaise(True)
            self.strip_layout.insertWidget(self.strip_layout.indexOf(self.btn_menu), live)
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
        self.menu.addAction(icon(APP_ICON), tr("About…"), self.show_about)
        # Care: dock station commands (hidden when the robot has none)
        put(self.dock_grid, ["empty_dock", "mop_wash", "mop_dry"], columns=3, hide=True)
        self._dock_actions = [act[k] for k in ("empty_dock", "mop_wash", "mop_dry") if k in act]
        for action in self._dock_actions:
            action.changed.connect(self._update_dock_group)
        # Wi-Fi: recording with QGIS open, recorder on the robot, maps from the Pi
        put(self.wifi_qgis_grid, ["wifi_survey", "wifi_map"])
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
                self._show_body(not self.tabs.isVisible())
            else:
                self.show_tab("status")
            return True
        return super().eventFilter(obj, event)

    def show_about(self, *_):
        from .about import AboutDialog
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
        for entry in self._terminal_entries:
            entry.setVisible(on)
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

    def _set_tab_shown(self, key, shown):
        """Show or hide a side tab (Qt 5.15+)."""
        if key in self._tab_keys:
            self.tabs.setTabVisible(self._tab_keys.index(key), shown)

    def show_tab(self, key):
        """Bring a side tab to the front (unfolding a compact panel)."""
        if key in self._tab_keys:
            if self.is_compact() and not self.tabs.isVisible():
                self._show_body(True)
            self.tabs.setCurrentIndex(self._tab_keys.index(key))

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
        dock = getattr(self, "_dock_button", None)
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
        for i, tab_key in enumerate(self._tab_keys):
            flagged = any(t == tab_key for _, t in problems)
            self.tabs.setTabIcon(i, badge_icon(self._tab_icons[tab_key]) if flagged
                                 else self._tab_icons[tab_key])

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
            parts = [_format_duration(seconds)] if seconds is not None else []
            if area is not None:
                parts.append(_format_area_cm2(area))
            self.lbl_job.setText(" · ".join(parts))
        self._emit_summary()

    def _emit_summary(self):
        """State, battery and job in one line, for the card over the map."""
        state = self._state
        if state is None:
            self.summaryChanged.emit("")
            return
        color = STATE_COLORS.get(state, "#757575")
        parts = [f"<b style='color:{color}'>{html.escape(_label(_state_labels(), state))}</b>"]
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
        for widget in (self.tabs, self.lbl_feedback):
            widget.setVisible(visible)

    # -- terminal -------------------------------------------------------------------------

    def _on_terminal_switch(self, checked):
        if not checked:   # the other button of the pair is being checked
            return
        device, mode = self._terminal_choice()
        QgsSettings().setValue(KEY_TERMINAL, f"{device}/{mode}")
        self._show_terminal_page()
        self._update_console()

    def open_terminal(self, device, mode="console"):
        """Show the Terminal tab on a server's console or log."""
        self._term_device = device
        (self.btn_term_log if mode == "log" else self.btn_term_console).setChecked(True)
        QgsSettings().setValue(KEY_TERMINAL, f"{device}/{mode}")
        self._set_tab_shown("terminal", True)
        self._show_terminal_page()
        self.show_tab("terminal")
        self._update_console()

    def close_terminal(self, *_):
        """Hide the Terminal tab; its sessions stop (they run only while shown)."""
        self._set_tab_shown("terminal", False)
        if self.tabs.currentWidget() is self.tab_terminal:
            self.show_tab("status")
        self._update_console()

    def _show_terminal_page(self):
        if "terminal" in self._tab_titles:
            self._tab_titles["terminal"][0].setText(
                tr("Terminal · {server}").format(server=_device_name(self._term_device)))
        pages = {("robot", "console"): self.tab_console, ("pi", "console"): self.tab_pi_console,
                 ("ha", "console"): self.tab_ha_console,
                 ("nuc", "console"): self.tab_nuc_console, ("nuc", "log"): self.tab_nuc_log,
                 ("robot", "log"): self.tab_log, ("pi", "log"): self.tab_pi_log,
                 ("ha", "log"): self.tab_ha_log}
        self.terminal_stack.setCurrentWidget(pages[self._terminal_choice()])

    def _terminal_choice(self):
        """(device, mode) of the Terminal tab."""
        return self._term_device, ("log" if self.btn_term_log.isChecked() else "console")

    # -- Wi-Fi tab ------------------------------------------------------------------------

    def _on_threshold(self, key, value):
        QgsSettings().setValue(f"valetudo/{key}", value)
        self._update_thresholds()

    def _update_thresholds(self):
        self.sparkline.thresholds = (self.spin_wifi_good.value(), self.spin_wifi_fair.value(),
                                     self.spin_wifi_bad.value())
        self.sparkline.update()

    def set_robot_recorder_status(self, text):
        """Called by the plugin: where the Wi-Fi recorder of the robot stands."""
        self.lbl_robot_recorder.setText(text)

    def set_pi_thumbnail(self, path):
        """Called by the plugin with the PNG of the last map loaded from the Pi."""
        pixmap = QPixmap(path) if path else QPixmap()
        self.lbl_pi_thumb.setVisible(not pixmap.isNull())
        if not pixmap.isNull():
            self.lbl_pi_thumb.setPixmap(pixmap.scaledToWidth(
                min(260, pixmap.width()), Qt.TransformationMode.SmoothTransformation))

    # -- camera ---------------------------------------------------------------------------

    def _show_video_window(self, *_):
        if self.video_window is None:
            self.video_window = VideoWindow(self)
            self.camera.stream.frameReady.connect(self.video_window.show_image)
        if not self.camera.stream.is_running():
            self.camera.play()
        self.video_window.showFullScreen()

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

    def toggle_room(self, seg_id):
        """From the map: tick or untick a room in the Clean tab."""
        ids = list(self.rooms_ctl.checked)
        ids = [i for i in ids if i != seg_id] if seg_id in ids else ids + [seg_id]
        self.rooms_ctl.set_checked(ids)
        self.show_feedback(tr("Ticked: {rooms}").format(
            rooms=", ".join(self.rooms_ctl.name(i) for i in ids) or "—"))

    def room_menu(self, seg_id, name, global_pos):
        """From the map: the room's menu (rename, join, split)."""
        self._room_menu(seg_id, name or self.rooms_ctl.name(seg_id), global_pos)

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
            self.client.clean_segments(ids, self.passes())

    def passes(self):
        """Number of passes chosen in the Clean tab (rooms and zones)."""
        return self.spin_passes.value()

    def checked_room_ids(self):
        """Ticked rooms, in list order."""
        return self.rooms_ctl.checked_ids()

    # -- client wiring ---------------------------------------------------------

    def attach(self, client):
        """Called by the plugin whenever its client is created (or dropped: None)."""
        self.client = client
        self.capabilities = None
        self._reachable = None
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
        if QgsSettings().value(KEY_ONCE_TIMERS, [], type=list):
            client.fetch_timers()   # a one-off cleaning may be due for removal
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
        self._remove_done_once_timers()

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
        entries = []
        for timer in self._timers:
            days, hour, minute = schedule.local_schedule(timer, offset)
            entries.append((timer.get("id"), timer.get("label") or tr("(no name)"),
                            days, hour, minute, bool(timer.get("enabled"))))
        self.week.set_entries(entries, day_names())
        self.week.set_selected(selected)
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

    def _select_timer(self, timer_id):
        for i in range(self.timers.topLevelItemCount()):
            item = self.timers.topLevelItem(i)
            item.setSelected(item.data(0, Qt.ItemDataRole.UserRole) == timer_id)
        self.week.set_selected(timer_id)

    def _new_timer_at(self, dow, hour, minute, segment_ids=None, label=""):
        """New cleaning at a slot of the week view (local time), rooms pre-ticked."""
        if self.client is None:
            return
        self._open_timer_dialog(schedule.build_timer(
            None, label, [dow], hour, minute, utc_offset_minutes(), segment_ids=segment_ids,
            iterations=self.passes()))

    def _dragged_rooms(self):
        """(room ids, group title) of the line being dragged from the rooms tree."""
        item = self.rooms.currentItem()
        if item is None:
            return [], ""
        seg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if seg_id is not None:
            return [seg_id], item.text(0)
        ids = [item.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(item.childCount())]
        return [i for i in ids if i is not None], item.text(0)

    def _new_timer_for_group(self, dow, hour, minute):
        ids, title = self._dragged_rooms()
        if ids:
            self._new_timer_at(dow, hour, minute, ids, title[:24])

    def _tonight(self, *_):
        """Clean the ticked rooms (or the whole home) once, tonight: a timer for today
        that the plugin deletes once its time is past."""
        if self.client is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Tonight"))
        form = QFormLayout(dialog)
        when = QTimeEdit(QTime(22, 0))
        when.setDisplayFormat("HH:mm")
        form.addRow(tr("Start at"), when)
        ids = self.rooms_ctl.checked_ids(ticked_order=True)
        names = ", ".join(self.rooms_ctl.name(i) for i in ids) or tr("Whole home")
        form.addRow(tr("Clean"), QLabel(names))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        start = QDateTime.currentDateTime()
        start.setTime(when.time())
        if start <= QDateTime.currentDateTime():
            start = start.addDays(1)   # already past today: tomorrow
        dow = start.date().dayOfWeek() % 7          # Qt: 1 = Monday … 7 = Sunday
        label = tr("Once {date}").format(date=start.toString("dd/MM HH:mm"))[:24]
        timer = schedule.build_timer(None, label, [dow], when.time().hour(),
                                     when.time().minute(), utc_offset_minutes(),
                                     segment_ids=ids or None, iterations=self.passes())
        once = QgsSettings().value(KEY_ONCE_TIMERS, [], type=list) or []
        once.append(f"{label}|{start.toSecsSinceEpoch()}")
        QgsSettings().setValue(KEY_ONCE_TIMERS, once)
        self.client.save_timer(timer)

    def _remove_done_once_timers(self):
        """Delete the one-off cleanings ("Tonight") whose time is past by an hour."""
        once = QgsSettings().value(KEY_ONCE_TIMERS, [], type=list) or []
        if not once or self.client is None:
            return
        now, keep = time.time(), []
        labels = {t.get("label"): t.get("id") for t in self._timers}
        for entry in once:
            label, _, due = entry.rpartition("|")
            if not due.isdigit() or label not in labels:
                continue           # unknown or already gone: forget it
            if now > int(due) + ONCE_GRACE_S:
                self.client.delete_timer(labels[label])
            else:
                keep.append(entry)
        QgsSettings().setValue(KEY_ONCE_TIMERS, keep)

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

    def _ha_ssh_target(self):
        """(host, user, port) of the Home Assistant server over SSH, or None.

        Registers its SSH password, if one is stored (read once per target)."""
        cfg = load_settings()
        if not cfg["ha_ssh_host"]:
            return None
        target = (cfg["ha_ssh_host"], cfg["ha_ssh_user"], int(cfg["ha_ssh_port"]))
        if getattr(self, "_ha_ssh_password_for", None) != target:
            password = (secret(HA_SSH_PASSWORD_SETTING)
                        if has_secret(HA_SSH_PASSWORD_SETTING) else "")
            ssh_auth.set_password(*target, password)
            self._ha_ssh_password_for = target
        return target

    @staticmethod
    def _kodi_settings():
        """(url, user, password) of Kodi, or None when no address is set."""
        cfg = load_settings()
        if not cfg["kodi_url"]:
            return None
        password = secret(KODI_PASSWORD_SETTING) if has_secret(KODI_PASSWORD_SETTING) else ""
        return (cfg["kodi_url"], cfg["kodi_user"], password)

    @staticmethod
    def _nuc_target():
        """(host, user, port) of the NUC, or None when none is set."""
        cfg = load_settings()
        return (cfg["nuc_host"], cfg["nuc_user"], int(cfg["nuc_port"])) if cfg["nuc_host"] else None

    # -- web interfaces and SSH sessions (Status tab) -------------------------------

    def _server_web(self, prefix):
        """Address of a server's web interface, or ""."""
        cfg = load_settings()
        url = {"robot": cfg["url"], "pi": cfg["pi_web_url"], "ha": cfg["ha_url"],
               "nuc": cfg["nuc_web_url"],
               "kodi": kodi_rpc_url(cfg["kodi_url"])[:-len("jsonrpc")] if cfg["kodi_url"]
               else ""}[prefix].strip()
        if url and "://" not in url:
            url = "http://" + url
        return url

    def _server_ssh(self, prefix):
        """(host, user, port) for an SSH session on a server, or None. Kodi runs on
        the NUC: its host, with the NUC's SSH user and port."""
        if prefix == "kodi":
            cfg = load_settings()
            host = QUrl(kodi_rpc_url(cfg["kodi_url"])).host() if cfg["kodi_url"] else ""
            return (host, cfg["nuc_user"], int(cfg["nuc_port"])) if host else None
        return {"robot": self._ssh_target, "pi": self._pi_target, "ha": self._ha_ssh_target,
                "nuc": self._nuc_target}[prefix]()

    def _update_server_buttons(self):
        """Each button only where there is something to open; the tooltip says what."""
        for prefix in SERVERS:
            web, ssh = getattr(self, f"btn_{prefix}_web"), getattr(self, f"btn_{prefix}_ssh")
            url, target = self._server_web(prefix), self._server_ssh(prefix)
            web.setVisible(bool(url))
            web.setToolTip(tr("Open the web interface in the browser: {url}").format(url=url))
            ssh.setVisible(target is not None)
            if target is not None:
                ssh.setToolTip(tr("Open an SSH session in a terminal: {command}").format(
                    command=system_terminal.describe(*target)))

    def open_web(self, prefix):
        url = self._server_web(prefix)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def open_ssh(self, prefix):
        target = self._server_ssh(prefix)
        if target is None:
            return
        problem = system_terminal.open_ssh(*target, tr("Press Enter to close."))
        if problem == "no_terminal":
            self.show_feedback(tr("No terminal program found: set the TERMINAL environment "
                                  "variable to the one you use."), "warning")
        elif problem:
            self.show_feedback(tr("The terminal could not be started."), "warning")

    def _update_pi_tab(self):
        """The Pi's details, card and terminal exist only when a Pi address is set;
        its details are read while the panel is visible. Same for the NUC's block."""
        self.nuc.update(self.isVisible())
        self._update_server_buttons()
        self.kodi.update(self.isVisible())
        has_pi = self._pi_target() is not None
        self.pi_header.setVisible(has_pi)
        for widget in (self.lbl_pi_strip_logo, self.lbl_pi_strip):
            widget.setVisible(has_pi)
        self._strip_servers = {**getattr(self, "_strip_servers", {}), "pi": has_pi}
        self._update_strip_separators()
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
            self._set_strip_status(self.lbl_pi_strip, "#9e9e9e", tr("Connecting…"))

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
            self._set_strip_status(self.lbl_pi_strip, "#2e7d32", tr("Online"), text)
        else:
            text = tr("Unreachable over SSH")
            self.lbl_pi_connection.setText(f"<span style='color:#c62828'>●</span> {text}")
            self._set_strip_status(self.lbl_pi_strip, "#c62828", tr("Offline"), text)
        pi = self._pi or {}
        self.lbl_pi_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_pi_name.setText(" · ".join(p for p in (pi.get("hostname"), pi.get("uname")) if p))
        # Offline: its last clock and uptime are no longer true, only the address is
        online = bool(self._pi_ok)
        line, wrong = host_info.info_line(pi.get("ip") or (self._pi_target() or [""])[0],
                                          pi.get("time") if online else None,
                                          pi.get("received_at"),
                                          pi.get("uptime") if online else None,
                                          self._local_time)
        self.lbl_pi_info.setText(line)
        self.lbl_pi_info.setStyleSheet("color: #ef6c00;" if wrong else "")
        self._set_problem("pi_clock", tr("The Raspberry Pi's clock is wrong.") if wrong else None,
                          "maintenance")

    def _update_strip_tip(self):
        """What a click on the strip does, then the Wi-Fi signal (no longer shown in it)."""
        lines = [tr("Click to unfold or fold the panel") if self.is_compact()
                 else tr("Click for the detailed status")]
        wifi = getattr(self, "_wifi_html", "")
        if wifi:
            lines.append(wifi + (" · " + html.escape(self._wifi_tip) if self._wifi_tip else ""))
        self.strip.setToolTip("<br>".join(lines))

    def _set_strip_status(self, label, color, text, tooltip=""):
        """A server in the strip: its logo and a coloured dot; the words in the tooltip."""
        name = tr("Raspberry Pi") if label is self.lbl_pi_strip else "Home Assistant"
        label.setText(f"<span style='color:{color}'>●</span>")
        tip = f"<b>{html.escape(name)}</b>: {html.escape(text)}" + (
            f"<br>{html.escape(tooltip)}" if tooltip else "")
        label.setToolTip(tip)
        logo = self.lbl_pi_strip_logo if label is self.lbl_pi_strip else self.lbl_ha_strip_logo
        logo.setToolTip(tip)

    def _update_strip_separators(self):
        """One separator before the servers, whichever are shown."""
        shown = getattr(self, "_strip_servers", {})
        self.sep_pi.setVisible(any(shown.values()))
        self.sep_ha.setVisible(False)

    # -- Home Assistant (strip) -----------------------------------------------------

    def _update_ha(self):
        """Check Home Assistant every HA_INTERVAL_MS while the panel is visible."""
        if self.isVisible():
            if not self._ha_timer.isActive():
                self._ha_timer.start()
                self._refresh_ha()
        else:
            self._ha_timer.stop()

    def _refresh_ha(self, *_):
        url = load_settings()["ha_url"]
        has_token = has_ha_token()
        if not has_token:
            self._ha_token = ""
        elif not self._ha_token:
            self._ha_token = ha_token()   # may ask for the QGIS master password, once
        if self._ha_client is not None:
            self._ha_client.close()
        client = self._ha_client = HomeAssistantClient(url, self._ha_token, self)
        self._ha["url"] = url
        if self._ha_state is None and has_token:
            self._ha_state = "connecting"
            self._update_ha_header()

        def ok(config):
            config = config if isinstance(config, dict) else {}
            self._ha.update(name=config.get("location_name") or "",
                            version=config.get("version") or "",
                            time_zone=config.get("time_zone") or "",
                            time=client.server_time, received_at=client.received_at,
                            error="")
            self._ha_state = "online"
            self._ha_last_ok = time.monotonic()
            self._ha_last_ok_clock = QDateTime.currentDateTime().toString("HH:mm:ss")
            self._update_ha_header()
            # Uptime: the "Uptime" integration's sensor (its state is the start time)
            client.get("/states/sensor.uptime", uptime_ok,
                       lambda _error: self._set_ha_start(None), timeout_ms=5000)

        def uptime_ok(state):
            start = parse_timestamp(state.get("state")) if isinstance(state, dict) else None
            self._set_ha_start(start)

        def failed(error):
            self._ha["error"] = error
            if error == UNAUTHORISED:   # there, but no token to go further
                self._ha_state = "no_token"
            elif has_token:
                self._ha_state = "offline"
            else:   # no token and nothing answers: no Home Assistant, nothing to show
                self._ha_state = None
            self._update_ha_header()

        client.get("/config", ok, failed, timeout_ms=5000)

    def _set_ha_start(self, start):
        self._ha["start"] = start
        self._update_ha_header()

    def _update_ha_header(self):
        """Home Assistant in the strip (status) and in the details (three lines)."""
        state = self._ha_state
        shown = state is not None
        for widget in (self.lbl_ha_strip_logo, self.lbl_ha_strip, self.ha_header):
            widget.setVisible(shown)
        self._strip_servers = {**getattr(self, "_strip_servers", {}), "ha": shown}
        self._update_strip_separators()
        if not shown:
            return
        ha, url = self._ha, self._ha.get("url", "")
        if state == "connecting":
            color, short = "#9e9e9e", tr("Connecting…")
            long = short
        elif state == "online":
            seconds = int(time.monotonic() - self._ha_last_ok)
            color, short = "#2e7d32", tr("Online")
            long = tr("Connected · updated {seconds} s ago").format(seconds=seconds)
        elif state == "no_token":
            color, short = "#ef6c00", tr("No token")
            long = tr("Found, no access token")
        else:
            color, short = "#c62828", tr("Offline")
            long = tr("Unreachable · last update {time}").format(
                time=self._ha_last_ok_clock or "—")
        self.lbl_ha_connection.setText(f"<span style='color:{color}'>●</span> {long}")
        self.lbl_ha_connection.setToolTip(ha.get("error", "") if state == "offline" else "")
        # Second line: Home Assistant <version> · <home name> · <time zone>
        if state == "no_token":
            name = tr("Home Assistant answers at {url}. Add an access token in "
                      "Settings › Options › {name} to use it.").format(url=url, name=PLUGIN_NAME)
        else:
            version = ha.get("version", "")
            name = " · ".join(p for p in (
                f"Home Assistant {version}" if version else "Home Assistant",
                ha.get("name"), ha.get("time_zone")) if p)
        self.lbl_ha_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_ha_name.setText(name)
        # Third line: address · Home Assistant's clock · uptime
        host = QUrl(url).host() or url
        online = state == "online"
        uptime = None
        if online and ha.get("start") and ha.get("time"):
            uptime = max(0, ha["time"] - ha["start"])
        line, wrong = host_info.info_line(host, ha.get("time") if online else None,
                                          ha.get("received_at"), uptime, self._local_time)
        self.lbl_ha_info.setText(line)
        self.lbl_ha_info.setStyleSheet("color: #ef6c00;" if wrong else "")
        if state == "offline":
            tip = ha.get("error", "")
        elif state == "no_token":
            tip = name
        else:
            tip = " · ".join(p for p in (ha.get("name"), ha.get("version"), url) if p)
        self._set_strip_status(self.lbl_ha_strip, color, short, tip)

    @staticmethod
    def _local_time(epoch):
        return QDateTime.fromSecsSinceEpoch(int(epoch)).toString("dd/MM/yyyy HH:mm")

    def settings_changed(self):
        """Called by the plugin after the Options page saved changes."""
        self._ha_ssh_password_for = None   # the SSH password may have changed
        self._update_console()
        self._ha_token = None   # the token may have changed
        if self.isVisible():
            self._refresh_ha()

    def _update_console(self):
        """Consoles and logs run only while their page of the Terminal tab is shown."""
        self._update_pi_tab()
        page = (self.terminal_stack.currentWidget()
                if self.tabs.currentWidget() is self.tab_terminal else None)
        for view in self.consoles + self.logs:
            view.update(self.isVisible(), page)

    def _update_camera(self):
        """Play while the panel is visible and the Camera tab is shown; keep playing
        CAMERA_GRACE_MS after that, so that a quick return is instant."""
        if self.isVisible() and self.tabs.currentWidget() is self.camera_page:
            self._camera_grace.stop()
            if not self.camera.stream.is_running():
                self.camera.play()
        elif self.camera.stream.is_running() and not self._camera_grace.isActive():
            self._camera_grace.start()

    def _camera_grace_over(self):
        """The Camera tab was left a while ago: stop, unless a recording runs."""
        if self.camera.is_recording():
            return   # stopped with the recording (Stop recording, or the panel closing)
        self.camera.stop()

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
        self.nuc.stop()
        self.kodi.stop()
        self._ha_timer.stop()
        if self._ha_client is not None:
            self._ha_client.close()
        for log in self.logs:
            log.shutdown()
        for console in self.consoles:
            console.shutdown()

    def _on_visibility(self, visible):
        self._update_camera()
        self._update_console()
        self._update_ha()
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

    def refresh_all(self, *_):
        """Status tab: read every server again now."""
        self.refresh()
        if self._pi_target() is not None:
            self._refresh_pi()
        self.nuc.refresh()
        self.kodi.refresh()
        if self._ha_state is not None:
            self._refresh_ha()

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
        self._update_strip_tip()
        self.lbl_wifi_now.setText(tr("Not connected."))
        self.sparkline.clear()
        self._state, self._job, self._battery = None, None, None
        self._update_primary()
        self._update_job()
        for key in ("error", "dock", "consumables", "robot_clock"):
            self._set_problem(key, None)

    def _on_reachable(self, ok):
        self._reachable = ok
        if not ok:
            self._show_unreachable()
        if ok and self.client is not None and not self._robot_text:
            self.client.fetch_robot_info(quiet=True)   # robot was off when we connected
            self.client.fetch_version(quiet=True)
        if ok:
            self._last_ok = time.monotonic()
            self._last_ok_clock = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._update_header()

    def _show_unreachable(self):
        """The robot no longer answers: its last state, battery, Wi-Fi, clock and
        uptime are no longer true, so they are not shown (they come back with the
        next answer)."""
        for badge in (self.lbl_badge, self.lbl_badge_details):
            badge.setText(tr("Unreachable"))
            badge.setStyleSheet("background-color: #9e9e9e; color: white; font-weight: bold;"
                                "border-radius: 9px; padding: 2px 10px;")
        for bar in (self.bar_battery, self.bar_battery_details):
            bar.setValue(0)
            bar.setFormat("—")
            bar.setEnabled(False)
        self.lbl_state.setText(tr("Unreachable"))
        self._wifi_html, self._wifi_tip = "", ""
        self._update_strip_tip()
        self.lbl_wifi_now.setText(tr("The robot does not answer."))
        self._host = {}
        self._update_robot_info()
        self._update_robot_label()
        self._state, self._job, self._battery = None, None, None
        self._update_primary()
        self._update_job()

    def _update_header(self):
        self._update_pi_header()
        self.nuc.render()
        self.kodi.render()
        if self._ha_state == "online":
            self._update_ha_header()
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
        self._set_problem("robot_clock", tr("The robot's clock is wrong: check Valetudo's "
                                            "NTP settings.") if wrong else None, "maintenance")

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
                self._state = state
                err = attr.get("error") or {}
                error_text = (err.get("message") if isinstance(err, dict) else "") \
                    or (attr.get("metaData") or {}).get("error_description", "")
                if state != "error" and not err:
                    error_text = ""
            elif cls == "BatteryStateAttribute":
                level = int(attr.get("level") or 0)
                flag = attr.get("flag")
                self._battery = level
                suffix = f" · {_label(flags, flag)}" if flag and flag != "none" else ""
                for bar in (self.bar_battery, self.bar_battery_details):
                    bar.setEnabled(True)
                    bar.setValue(level)
                    bar.setFormat(f"{level} %{suffix}")
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
        self._set_problem("error", error_text or None)
        self._update_primary()
        self._update_job()
        self._emit_summary()
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
        self._has_components = bool(components)
        self._update_dock_group()
        names, values, advice = (dock_component_labels(), dock_component_values(),
                                 dock_component_advice())
        issues = [f"{_label(names, c)}: {advice[v]}" for c, v in components.items()
                  if v in DOCK_COMPONENT_PROBLEMS]
        self._set_problem("dock", " · ".join(issues) or None, "maintenance")
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
        worn = []
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
                worn.append(label)
                label = f"{label} ⚠"
                widget.setToolTip(tr("Replace soon"))
            form.addRow(label, widget)
        self._set_problem("consumables", tr("Replace soon: {parts}").format(
            parts=", ".join(worn)) if worn else None, "maintenance")

    @staticmethod
    def _stats(items):
        return {s.get("type"): s.get("value") for s in items if isinstance(s, dict)}

    def _on_current_statistics(self, items):
        stats = self._stats(items)
        self.lbl_cur_time.setText(_format_duration(stats["time"]) if "time" in stats else "—")
        self.lbl_cur_area.setText(_format_area_cm2(stats["area"]) if "area" in stats else "—")
        self._job = (stats.get("time"), stats.get("area"))
        self._update_job()

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
            self._update_strip_tip()
        else:
            cfg = load_settings()
            color = signal_color(signal, cfg["wifi_good_dbm"], cfg["wifi_fair_dbm"],
                                 cfg["wifi_bad_dbm"])
            text = tr("Wi-Fi {signal} dBm").format(signal=signal)
            self.sparkline.add(signal)
            self._wifi_html = f"<span style='color:{color}'>{html.escape(text)}</span>"
            parts = [details.get("ssid"), details.get("frequency"),
                     (details.get("ips") or [None])[0]]
            self._robot_ip = (details.get("ips") or [""])[0] or ""
            self._update_robot_info()
            self._wifi_tip = tr("Wi-Fi: {details}").format(
                details=" · ".join(str(p) for p in parts if p) or "—")
            self._update_strip_tip()
            self.lbl_wifi_now.setText(" · ".join(
                [f"<b style='color:{color}'>{signal} dBm</b>"]
                + [html.escape(str(p)) for p in parts if p]))
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
