"""Main plugin class: actions, toolbar, menu, panels, map tools.

Every command exists once, as a QAction in ``self.act``. The toolbar, the
Valetudo menu and the status panel all show these same objects, so their
enabled/checked state can never disagree.
"""

import os

from qgis.PyQt.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl
from qgis.PyQt.QtWidgets import (
    QAction, QCheckBox, QDockWidget, QFileDialog, QInputDialog, QMessageBox, QPushButton,
    QToolBar, QToolButton,
)
from qgis.core import (
    QgsApplication,
    Qgis, QgsCoordinateReferenceSystem, QgsMessageLog, QgsProject, QgsSettings,
)

from . import room_groups
from .boot_monitor import BootMonitor
from .client import ValetudoClient
from .coords import q2v, v2q
from .history_recorder import HistoryRecorder
from .history_store import history_folder
from .goto_emulation import ZONE_SIZE_CM as GOTO_ZONE_SIZE_CM, GoToEmulator
from .i18n import install_translator, remove_translator, tr
from .icons import APP_ICON, has_icon, icon
from .map_layers import ValetudoLayers
from .map_overlay import MapOverlay
from .map_tools import GoToMapTool, LineMapTool, RoomPickMapTool, SensorMapTool, ZoneMapTool
from .restrictions import RestrictionLayers, layer_names as restriction_layer_names
from . import pi_maps, robot_survey
from .robot_survey import RobotSurvey
from . import app_launcher
from .app_launcher import KEY_APP_MODE
from .manual import open_manual
from .options_page import PAGE_NAME as OPTIONS_PAGE, ValetudoOptionsFactory
from .settings import (KEY_ADVANCED, KEY_ROBOT_PROJECT, PLUGIN_NAME, TOOLBAR_CHOICES, follow_robot,
                       has_ha_token, load_settings, toolbar_keys)
from .sensors import SensorManager
from .quiet_travel import QUIET_PRESETS, QuietTravel
from .ssh_reboot import SshReboot
from .status_panel import (
    DOCK_COMPONENT_PROBLEMS,
    KEY_GOTO_QUIET,
    KEY_PI_MAP_FULL,
    preset_labels,
    state_label as dock_state_label,
    ValetudoPanel,
    dock_component_advice,
    dock_component_labels,
    dock_component_values,
)
from .wifi_survey import WifiSurvey, build_wifi_map, layer_names as wifi_layer_names

KEY_GOTO_ZONE_OK = "valetudo/goto_zone_confirmed"
KEY_ROBOT_SURVEY_DIR = "valetudo/robot_survey_dir"   # set once the survey is on the robot
MIN_ZONE_SIZE_CM = 20  # smaller rectangles are treated as accidental clicks
WATCH_INTERVAL_MS = 60_000  # background check of the dock station, panel open or not
LIVE_AT_START_DELAY_MS = 3_000   # after QGIS has opened a project given at launch
LIVE_AT_START_WINDOW_MS = 60_000  # robot answering later than that: no automatic start
SENSOR_POLL_MS = 15_000           # how often Home Assistant sensor values are refreshed
SENSOR_REMOVE_TOLERANCE_CM = 40   # right-click this close to a sensor removes it

# Valetudo capability required by each action (absent: always available).
# Alternatives: an action is also available with any of these capabilities.
# "Go here" falls back to a tiny zone clean followed by a pause (see goto_emulation.py).
ALTERNATIVE_CAPABILITIES = {
    "goto": ["ZoneCleaningCapability"],
}

REQUIRED_CAPABILITY = {
    "start": "BasicControlCapability",
    "pause": "BasicControlCapability",
    "home": "BasicControlCapability",
    "zone": "ZoneCleaningCapability",
    "goto": "GoToLocationCapability",
    "locate": "LocateCapability",
    "empty_dock": "AutoEmptyDockManualTriggerCapability",
    "mop_wash": "MopDockCleanManualTriggerCapability",
    "mop_dry": "MopDockDryManualTriggerCapability",
    "edit_restrictions": "CombinedVirtualRestrictionsCapability",
    "send_restrictions": "CombinedVirtualRestrictionsCapability",
    "wifi_survey": "WifiConfigurationCapability",
}



# Layout, None = separator. The panel shows the robot and map rows.
# Simple menu and toolbar: everything else is in the panel's command list.
MAP_TOOLS = ["pick_rooms", "place_sensor", "edit_restrictions",
             "send_restrictions"]   # shown with "Show on map"
# Hidden unless "Advanced tools" is on (with the panel's Terminal, recorder and boot log)
ADVANCED_ACTIONS = ["edit_restrictions", "send_restrictions", "watch_boot",
                    "robot_survey_install", "robot_survey_import", "robot_survey_remove"]
MENU = ["status_panel", "settings", "setup", "app_launcher", "app_mode", "manual"]
APP_TOOLBARS = ("ValetudoToolbar", "mMapNavToolBar")   # kept on screen in app mode
LOG_TAG = PLUGIN_NAME   # tab of the QGIS "Log Messages" panel


def command_hints():
    """Tooltip of each button: what it does, and what to do next for map tools."""
    return {
        "start": tr("Start cleaning the whole home."),
        "zone": tr("Click, then drag a rectangle on the map: that zone is cleaned."),
        "goto": tr("Click, then click a point on the map: the robot goes there."),
        "pause": tr("Pause the current job."),
        "home": tr("Send the robot back to its dock."),
        "locate": tr("The robot beeps, to find it."),
        "live": tr("Show the robot's map in QGIS and follow the robot live."),
        "edit_restrictions": tr("Load no-go zones and walls as layers you can edit."),
        "send_restrictions": tr("Send the edited no-go zones and walls to the robot."),
        "place_sensor": tr("Click a point on the map to place a Home Assistant sensor; "
                           "right-click a sensor to remove it."),
        "empty_dock": tr("Empty the robot's dust bin into the dock."),
        "mop_wash": tr("Wash the mops in the dock."),
        "mop_dry": tr("Dry the mops in the dock."),
        "watch_boot": tr("Follow the robot's startup; the log is below."),
        "reboot": tr("Reboot the robot over SSH (asks first)."),
        "wifi_survey": tr("Record the robot's Wi-Fi signal where it goes; "
                          "click again to stop and build the Wi-Fi map."),
        "robot_survey_install": tr("Install a Wi-Fi recorder on the robot: it records the "
                                   "signal whenever the robot moves, even when QGIS is closed."),
        "robot_survey_import": tr("Bring the readings recorded on the robot into the "
                                  "“Wi-Fi survey” layer, then build the Wi-Fi map."),
        "robot_survey_remove": tr("Stop the Wi-Fi recorder on the robot and delete it with "
                                  "its readings."),
        "pi_wifi_map": tr("Add a Wi-Fi map built on the Raspberry Pi to the map, with its "
                          "readings: the latest run, or all runs combined with “Full map” "
                          "ticked (set the Pi in the settings)."),
        "wifi_map": tr("Build the Wi-Fi map again from the survey points "
                       "(only the selected ones, if any)."),
    }


def command_labels():
    """Translated labels for the command keys emitted by ValetudoClient."""
    return {
        "start": tr("Start"),
        "pause": tr("Pause"),
        "stop": tr("Stop"),
        "home": tr("Return to dock"),
        "segments": tr("Clean rooms"),
        "zone": tr("Clean zone"),
        "goto": tr("Go to"),
        "fan_speed": tr("Fan speed"),
        "water_usage": tr("Water usage"),
        "operation_mode": tr("Mode"),
        "camera_light": tr("Camera light"),
        "locate": tr("Locate robot (beep)"),
        "empty_dock": tr("Empty dust bin"),
        "mop_wash": tr("Wash mops"),
        "mop_dry": tr("Dry mops"),
        "restrictions": tr("Send no-go zones and walls"),
        "rename_room": tr("Rename room"),
        "join_rooms": tr("Join rooms"),
        "split_room": tr("Split room"),
        "timer_save": tr("Save scheduled cleaning"),
        "timer_delete": tr("Delete scheduled cleaning"),
        "timer_run": tr("Run scheduled cleaning now"),
    }


class ValetudoPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.translator = install_translator()  # before any tr() call
        self.menu = "&" + PLUGIN_NAME
        self.act = {}            # key -> QAction
        self._unloaded = False   # set by unload(): late signals and timers do nothing
        self._live_at_start = False   # "Show on map" pending at start-up
        self._last_map = None    # last map received, for "Follow the robot"
        self.toolbar = None
        self.client = None
        self.capabilities = None  # None = unknown (no robot contacted yet)
        self._reachable = None
        self.layers = ValetudoLayers(QgsProject.instance())
        self.restrictions = RestrictionLayers(QgsProject.instance())
        self._edit_bar = None           # message bar shown while restrictions are edited
        self._reload_quietly = False    # next restrictions reload: no editing, no bar
        self.zone_tool = self.goto_tool = None
        self.pick_tool = self.overlay = None
        self.sensor_tool = self.sensors = None
        self._map_tool_entries = []
        self.panel = None
        self.options_factory = None   # our page in Settings › Options
        self._dock_state = {}  # dock component -> last known value
        self._watch = None
        self._reboot = None
        self.survey = None
        self.history = None   # HistoryRecorder, while the robot is connected
        self._history_bar = None

    # ------------------------------------------------------------------
    # GUI setup / teardown
    # ------------------------------------------------------------------

    def _new_action(self, key, text, slot=None, checkable=False):
        action = QAction(text, self.iface.mainWindow())
        if has_icon(key):
            action.setIcon(icon(key))
        action.setToolTip(command_hints().get(key, text))
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(slot)
        self.act[key] = action
        return action

    def initGui(self):
        labels = command_labels()
        win = self.iface.mainWindow()

        # "Advanced tools": decided once, on for an existing configuration (nothing
        # disappears for those who use it), off for a new one.
        stored = QgsSettings()
        if not stored.contains(KEY_ADVANCED):
            stored.setValue(KEY_ADVANCED, bool(load_settings()["url"]))
        self._new_action("settings", tr("Settings…"), self.configure)
        self._new_action("setup", tr("Setup assistant…"), self.run_setup)
        self._new_action("app_launcher", tr("Create the app launcher…"), self.create_app_launcher)
        self.act["app_launcher"].setIcon(icon(APP_ICON))
        # In the app's profile only: QGIS's other toolbars and panels hidden, or not
        if QgsSettings().contains(KEY_APP_MODE):
            self._new_action("app_mode", tr("App mode"), self._on_app_mode, checkable=True)
            self.act["app_mode"].setToolTip(tr("Only the map and DomotiQGIS on screen; "
                                               "untick to show QGIS's toolbars and panels."))
            self.act["app_mode"].setChecked(QgsSettings().value(KEY_APP_MODE, True, type=bool))
        self._new_action("manual", tr("User manual"), lambda *_: open_manual())
        self.act["manual"].setIcon(QgsApplication.getThemeIcon("/mActionHelpContents.svg"))
        # The settings are a page of Settings › Options; "Settings…" opens it.
        self.options_factory = ValetudoOptionsFactory(self._on_settings_applied)
        self.iface.registerOptionsWidgetFactory(self.options_factory)
        # One switch for the map: load it and track the robot live (in view, if asked).
        self._new_action("live", tr("Show on map"), self.toggle_live, checkable=True)
        self.act["live"].setIcon(icon("show_map"))   # (a map with the robot)
        self._new_action("start", tr("Clean everything"), lambda *_: self.control("start"))
        self._new_action("pause", labels["pause"], lambda *_: self.control("pause"))
        self._new_action("home", tr("Dock"), lambda *_: self.control("home"))
        self._new_action("zone", tr("Clean a zone…"), self.activate_zone_tool, checkable=True)
        self._new_action("goto", tr("Go to…"), self.activate_goto_tool, checkable=True)
        dock_labels = {"locate": tr("Locate"), "empty_dock": tr("Empty bin"),
                       "mop_wash": tr("Wash mops"), "mop_dry": tr("Dry mops")}
        for key in ("locate", "empty_dock", "mop_wash", "mop_dry"):
            self._new_action(key, dock_labels[key], lambda *_, k=key: self.simple_command(k))
        self._new_action("edit_restrictions", tr("Edit no-go zones and walls"),
                         self.edit_restrictions)
        self._new_action("send_restrictions", tr("Send no-go zones and walls to robot…"),
                         self.send_restrictions)
        self._new_action("watch_boot", tr("Watch robot boot"), self.watch_boot)
        self._new_action("reboot", tr("Reboot robot (SSH)…"), self.reboot_robot)
        self._new_action("wifi_survey", tr("Record Wi-Fi survey"), self.toggle_wifi_survey,
                         checkable=True)
        self._new_action("wifi_map", tr("Build Wi-Fi map"), self.build_wifi_map)
        self._new_action("robot_survey_install", tr("Record Wi-Fi on the robot…"),
                         self.install_robot_survey)
        self._new_action("robot_survey_import", tr("Import Wi-Fi from the robot"),
                         self.import_robot_survey)
        self._new_action("robot_survey_remove", tr("Remove Wi-Fi recorder from robot…"),
                         self.remove_robot_survey)
        self.robot_survey = RobotSurvey()
        self.robot_survey.finished.connect(self._on_robot_survey_finished)
        self._new_action("pi_wifi_map", tr("Load Wi-Fi map from the Pi"),
                         lambda *_: self.load_pi_wifi_map())
        self._new_action("pick_rooms", tr("Pick rooms on the map"), self.activate_pick_tool,
                         checkable=True)
        self._new_action("place_sensor", tr("Place a sensor on the map"),
                         self.activate_sensor_tool, checkable=True)
        self.pi_ssh = RobotSurvey()   # the same one-shot SSH runner, towards the Pi
        self.pi_ssh.finished.connect(self._on_pi_wifi_map)
        self._update_pi_actions()
        self._update_robot_survey_actions()
        self.survey = WifiSurvey(QgsProject.instance())
        self.survey.sampleAdded.connect(self._on_wifi_sample)
        self.goto_emulator = GoToEmulator()
        self.goto_emulator.finished.connect(self._on_goto_finished)
        self.quiet_travel = QuietTravel()
        self.quiet_travel.ready.connect(self._on_quiet_ready)
        self.quiet_travel.failed.connect(self._on_quiet_failed)
        self.quiet_travel.restored.connect(
            lambda: self._message(tr("Your fan, water and mode settings are restored."),
                                  Qgis.MessageLevel.Info))
        self.boot = BootMonitor()
        self.boot.stage.connect(self._on_boot_stage)
        self.boot.logTail.connect(self._on_boot_log_tail)
        self._reboot = SshReboot()
        self._reboot.finished.connect(self._on_reboot_finished)

        # Panels: hidden by default; their toggle actions follow their visibility.
        self.panel = ValetudoPanel(win)
        self.panel.clientRequested.connect(self._on_panel_needs_client)
        self.panel.history_tab.importRequested.connect(
            lambda: self._import_robot_history(auto=False))
        self._update_robot_survey_actions()   # the History tab's "From the robot"
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
        self.panel.hide()
        self.act["status_panel"] = self.panel.toggleViewAction()
        self.act["status_panel"].setText(tr("{name} panel").format(name=PLUGIN_NAME))
        self.act["status_panel"].setIcon(icon(APP_ICON))
        self.panel.setWindowIcon(icon(APP_ICON))   # shown when the panel floats

        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName("ValetudoToolbar")   # filled by _build_toolbar()
        for key in MENU:
            if key is not None and key in self.act:
                self.iface.addPluginToMenu(self.menu, self.act[key])
        if QgsSettings().contains(KEY_APP_MODE):   # the app's profile
            # QGIS started alone must open the usual profile, not this one
            app_launcher.restore_last_profile()
            QgsApplication.instance().aboutToQuit.connect(
                app_launcher.restore_last_profile_after_exit)
        if self.act.get("app_mode") is not None and self.act["app_mode"].isChecked():
            # Once QGIS has restored its window (and now, if the plugin is enabled later)
            self.iface.initializationCompleted.connect(self._enter_app_mode)
            QTimer.singleShot(0, self._enter_app_mode)
        # QGIS creates the plugin's submenu of Plugins without an icon: give it the logo.
        for entry in self.iface.pluginMenu().actions():
            if entry.text() == self.menu and entry.menu() is not None:
                entry.setIcon(icon(APP_ICON))
        # Frequent commands as icon buttons; the others in the panel's "More" menu.
        self.panel.bind_actions(self.act)
        self.panel.advancedChanged.connect(lambda *_: self._apply_advanced())
        self._apply_advanced()
        self.panel.chk_goto_quiet.toggled.connect(lambda *_: self._apply_capabilities())

        # Room groups file: loaded now, reloaded whenever it is saved.
        self._groups_watcher = QFileSystemWatcher()
        self._groups_watcher.addPath(os.path.dirname(room_groups.file_path()))
        self._groups_watcher.directoryChanged.connect(self._schedule_groups_reload)
        self._groups_watcher.fileChanged.connect(self._schedule_groups_reload)
        self._groups_timer = QTimer()
        self._groups_timer.setSingleShot(True)
        self._groups_timer.setInterval(300)   # editors save in several steps
        self._groups_timer.timeout.connect(self._reload_room_groups)
        self._reload_room_groups()

        canvas = self.iface.mapCanvas()
        self.zone_tool = ZoneMapTool(canvas)
        self.zone_tool.setAction(self.act["zone"])  # QGIS unchecks it when another tool is picked
        self.zone_tool.zoneDrawn.connect(self._on_zone)
        self.goto_tool = GoToMapTool(canvas)
        self.goto_tool.setAction(self.act["goto"])
        self.goto_tool.pointPicked.connect(self._on_goto)
        self.split_tool = LineMapTool(canvas)
        self.split_tool.lineDrawn.connect(self._on_split_line)
        self.split_tool.cancelled.connect(lambda: self.iface.actionPan().trigger())
        self._split_room = None   # (id, name) of the room being split
        self.panel.splitRequested.connect(self._start_split)
        self.pick_tool = RoomPickMapTool(
            canvas, lambda: self.layers.layer("rooms") if self.layers.exists() else None)
        self.pick_tool.setAction(self.act["pick_rooms"])
        self.pick_tool.roomClicked.connect(self._on_room_clicked)
        self.sensor_tool = SensorMapTool(canvas)
        self.sensor_tool.setAction(self.act["place_sensor"])
        self.sensor_tool.placeRequested.connect(self._on_place_sensor)
        self.sensor_tool.removeRequested.connect(self._on_remove_sensor)
        self.sensors = SensorManager(self.iface.mainWindow())
        self.sensors.sensorsUpdated.connect(self._on_sensors_updated)
        self.panel.piMapRequested.connect(lambda full: self.load_pi_wifi_map(full=full))

        # While "Show on map" is on: a status card over the canvas (and the map tools
        # chosen for the toolbar, see _build_toolbar)
        self._build_toolbar()
        self.overlay = MapOverlay(canvas)
        self.panel.summaryChanged.connect(self.overlay.set_html)
        self.act["live"].toggled.connect(self._on_live_toggled)

        self._apply_capabilities()

        # Background watch: starts silently if a robot is configured (never prompts).
        self._watch = QTimer()
        self._watch.setInterval(WATCH_INTERVAL_MS)
        self._watch.timeout.connect(self._watch_tick)
        self._watch.start()
        QTimer.singleShot(0, self._watch_tick)

        # "Show on map" at start-up, if set and the robot answers (never prompts).
        self._live_at_start = False
        QTimer.singleShot(LIVE_AT_START_DELAY_MS, self._start_live_at_start)

    def _schedule_groups_reload(self, *_):
        if not self._unloaded:
            self._groups_timer.start()

    def _reload_room_groups(self):
        path = room_groups.file_path()
        # Editors often replace the file when saving: watch it again each time.
        if os.path.exists(path) and path not in self._groups_watcher.files():
            self._groups_watcher.addPath(path)
        if self.panel is not None:
            self.panel.set_room_groups(room_groups.load())

    def _on_panel_needs_client(self):
        if not self._unloaded:
            self._get_client(prompt=False)
        # Our layers in the project: found again when one is opened, saved next to it
        project = QgsProject.instance()
        project.readProject.connect(self._on_project_read)
        project.homePathChanged.connect(self._persist_layers)
        self._on_project_read()   # a project opened with QGIS, before the plugin

    def _on_project_read(self, *_):
        if self._unloaded:
            return
        self.layers.find()
        self.restrictions._adopt()
        if self.survey is not None:
            self.survey.layer()   # takes over a survey layer of the project
        self._persist_layers()   # e.g. a project saved by an older version

    def _persist_layers(self, *_):
        """The project has a folder (first save, Save as…): the map and the Wi-Fi survey
        go to files next to it."""
        if self._unloaded or not QgsProject.instance().fileName():
            return
        try:
            self.layers.persist()
            if self.survey is not None and self.survey.layer() is not None:
                self.survey.persist()
        except OSError as exc:
            self._message(tr("Could not save the robot's layers next to the project: {error}")
                          .format(error=exc), Qgis.MessageLevel.Warning)

    def unload(self):
        self._unloaded = True   # before anything else: removing the panel emits signals
        if QgsSettings().contains(KEY_APP_MODE):
            try:
                QgsApplication.instance().aboutToQuit.disconnect(
                    app_launcher.restore_last_profile_after_exit)
            except (TypeError, RuntimeError):
                pass
        project = QgsProject.instance()
        for signal, slot in ((project.readProject, self._on_project_read),
                             (project.homePathChanged, self._persist_layers),
                             (self.iface.initializationCompleted, self._enter_app_mode)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        if getattr(self, "_groups_timer", None) is not None:
            self._groups_timer.stop()
            self._groups_watcher.deleteLater()
            self._groups_watcher = self._groups_timer = None
        if self.panel is not None:
            try:
                self.panel.clientRequested.disconnect(self._on_panel_needs_client)
            except (TypeError, RuntimeError):
                pass
        self._hide_edit_bar()
        if getattr(self, "boot", None) is not None:
            self.boot.stop()
        if getattr(self, "robot_survey", None) is not None:
            self.robot_survey.stop()
        if getattr(self, "pi_ssh", None) is not None:
            self.pi_ssh.stop()
        if getattr(self, "goto_emulator", None) is not None:
            self.goto_emulator.stop()
        if self.sensors is not None:
            self.sensors.close()
        if self.survey is not None:
            self.survey.stop()
            self.survey = None
        if self._watch is not None:
            self._watch.stop()
            self._watch = None
        self._drop_client()
        self._hide_history_bar()
        if self.history is not None:
            self.history.deleteLater()
            self.history = None
        if getattr(self, "options_factory", None) is not None:
            self.iface.unregisterOptionsWidgetFactory(self.options_factory)
            self.options_factory = None
        canvas = self.iface.mapCanvas()
        split_tool = getattr(self, "split_tool", None)
        for tool in (self.zone_tool, self.goto_tool, split_tool,
                     getattr(self, "pick_tool", None), getattr(self, "sensor_tool", None)):
            if tool is not None and canvas.mapTool() is tool:
                canvas.unsetMapTool(tool)
        self.pick_tool = None
        self.sensor_tool = self.sensors = None
        if getattr(self, "overlay", None) is not None:
            self.overlay.remove()
            self.overlay = None
        self._map_tool_entries = []
        if self.zone_tool is not None:
            self.zone_tool.cleanup()
        if split_tool is not None:
            split_tool.cleanup()
        self.zone_tool = self.goto_tool = self.split_tool = None

        for key in MENU:
            if key is not None and key in self.act:
                self.iface.removePluginMenu(self.menu, self.act[key])
        if self.panel is not None:
            self.panel.shutdown()
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None
        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None
        self.act = {}
        remove_translator(self.translator)
        self.translator = None

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _get_client(self, prompt=True):
        """Return the client, creating it if needed.

        prompt=False never opens the settings dialog (e.g. a panel restored at
        QGIS startup); it just returns None when no robot is configured.
        """
        if self._unloaded:
            return None
        if self.client:
            return self.client
        cfg = load_settings()
        if not cfg["url"]:
            if not prompt or not self.configure():
                return None
            if self.client:   # already connected by _on_settings_applied()
                return self.client
            cfg = load_settings()
        self.client = ValetudoClient(cfg["url"], cfg["authcfg"])
        self.client.error.connect(self._on_error)
        self.client.reachable.connect(self._on_reachable)
        self.client.commandDone.connect(self._on_command_done)
        self.client.mapReceived.connect(self._on_map)
        self.client.capabilitiesReceived.connect(self._on_capabilities)
        self.client.restrictionsReceived.connect(self._on_restrictions)
        self.client.attributesReceived.connect(self._on_attributes)
        if self.panel is not None:
            self.panel.attach(self.client)
        self.client.fetch_capabilities(quiet=True)   # retried once the robot answers
        self._ensure_robot_survey()   # started again if the robot has rebooted
        self._start_history()
        return self.client

    def _drop_client(self):
        if self.history is not None:
            self.history.stop()   # closes the outing under way and writes it
        if getattr(self, "goto_emulator", None) is not None:
            self.goto_emulator.stop()
        if getattr(self, "quiet_travel", None) is not None:
            self.quiet_travel.forget()   # the robot keeps the quiet settings
        if self.survey is not None and self.survey.is_running():
            self.survey.stop()
        if "wifi_survey" in self.act:
            self.act["wifi_survey"].setChecked(False)
        if self.client:
            self.client.close()   # stops polling, cancels requests under way
            self.client.deleteLater()
            self.client = None
            if self.panel is not None:
                self.panel.attach(None)
        self._reachable = None
        self._dock_state = {}
        if "live" in self.act:
            self.act["live"].setChecked(False)
        self._on_capabilities(None)  # unknown robot: re-enable everything

    def _on_capabilities(self, capabilities):
        self.capabilities = set(capabilities) if capabilities is not None else None
        if self.history is not None:
            self.history.set_capabilities(self.capabilities)
        self._apply_capabilities()

    def _apply_capabilities(self):
        """Grey out actions the robot does not support (all enabled while unknown)."""
        for key, capability in REQUIRED_CAPABILITY.items():
            action = self.act.get(key)
            if action is None:
                continue
            needed = [capability] + ALTERNATIVE_CAPABILITIES.get(key, [])
            ok = self.capabilities is None or any(c in self.capabilities for c in needed)
            if not ok and action.isChecked():
                self.iface.actionPan().trigger()   # leave a map tool that became unsupported
            action.setEnabled(ok)
            hint = self._goto_hint() if key == "goto" else command_hints().get(key, action.text())
            action.setToolTip(hint if ok else
                              f"{action.text()} — {tr('Not supported by this robot.')}")

    def _goto_quiet(self):
        """True when "Go to" is emulated by a zone clean and the trip is to be quiet."""
        emulated = self.capabilities is not None and "GoToLocationCapability" not in self.capabilities
        return emulated and QgsSettings().value(KEY_GOTO_QUIET, True, type=bool)

    def _goto_hint(self):
        hint = command_hints()["goto"]
        if self._goto_quiet():
            hint += " " + tr("No cleaning on the way: mops lifted, water off, fan at its lowest, "
                             "then your settings restored.")
        return hint

    def _start_live_at_start(self):
        """At QGIS start-up: connect quietly; _on_reachable() turns "Show on map" on."""
        cfg = load_settings()
        if self._unloaded:
            return
        if not cfg["url"]:
            self._propose_settings()
            return
        if not cfg["live_at_start"]:
            return
        project = QgsProject.instance()
        if not project.fileName() and not project.mapLayers():   # QGIS opened without one
            path = cfg["robot_project"]
            if path and os.path.exists(path):
                project.setDirty(False)   # nothing to save in it: no "save?" question
                self.iface.addProject(path)
            else:
                self._offer_robot_project()
                return
        if not self._is_robot_project():
            return   # another project was opened: left as it is
        self._live_at_start = True
        QTimer.singleShot(LIVE_AT_START_WINDOW_MS,
                          lambda: setattr(self, "_live_at_start", False))
        if self._get_client(prompt=False) is not None and self._reachable:
            self._on_reachable(True)   # already connected (panel or dock watch)

    def _on_reachable(self, ok):
        """Report only changes, so an offline robot does not flood the message bar."""
        if ok and self._live_at_start and not self._unloaded:
            self._live_at_start = False   # once per QGIS session
            live = self.act.get("live")
            # Only in the robot project: never add the robot's map to another one.
            if live is not None and live.isEnabled() and not live.isChecked() \
                    and self._is_robot_project():
                live.trigger()   # same as a click: checked, then toggle_live(True)
        previous, self._reachable = self._reachable, ok
        if ok and self.capabilities is None and self.client is not None:
            self.client.fetch_capabilities(quiet=True)   # robot was off when we connected
        if ok and previous is False:
            self._message(tr("Robot reachable again."), Qgis.MessageLevel.Success)
        elif not ok and previous is True:
            self._message(tr("Robot unreachable."), Qgis.MessageLevel.Warning)

    # -- dock station watch -----------------------------------------------------

    def _watch_tick(self):
        if self._unloaded:
            return
        if not load_settings()["notify_dock"]:
            return
        client = self._get_client(prompt=False)
        if client is not None:
            client.fetch_attributes(quiet=True)

    def _on_attributes(self, attributes):
        """Notify when a dock component becomes empty/full/missing, or OK again."""
        if not load_settings()["notify_dock"]:
            return
        names, values, advice = (dock_component_labels(), dock_component_values(),
                                 dock_component_advice())
        for attr in attributes:
            if attr.get("__class") != "DockComponentStateAttribute":
                continue
            component, value = attr.get("type"), attr.get("value")
            previous = self._dock_state.get(component)
            self._dock_state[component] = value
            if value == previous:
                continue
            name = names.get(component, component)
            if value in DOCK_COMPONENT_PROBLEMS:
                text = tr("{component}: {state}. {advice}").format(
                    component=name, state=values.get(value, value), advice=advice[value])
                self.iface.messageBar().pushMessage(
                    PLUGIN_NAME, text, level=Qgis.MessageLevel.Warning, duration=0)
            elif value == "ok" and previous in DOCK_COMPONENT_PROBLEMS:
                self._message(tr("{component}: OK again.").format(component=name),
                              Qgis.MessageLevel.Success)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def configure(self, *_):
        """Open Settings › Options on the Valetudo page; True if a robot is then set."""
        if self._unloaded or self.options_factory is None:
            return False
        # Runs once the (modal) Options dialog is open and its pages exist.
        QTimer.singleShot(0, self.options_factory.select_page)
        self.iface.showOptionsDialog(self.iface.mainWindow(), currentPage=OPTIONS_PAGE)
        return bool(load_settings()["url"])

    def _on_settings_applied(self):
        """Our Options page saved changed values: reconnect with them."""
        if self._unloaded:
            return
        self._drop_client()
        # Reconnect at once (as at start-up): the history records without the panel.
        self._get_client(prompt=False)
        if self.panel is not None:
            self.panel.camera.restart_if_running()
            self.panel.settings_changed()   # e.g. Pi address: show or hide its console
        self._update_pi_actions()
        self._apply_advanced()
        self._build_toolbar()

    # -- history ---------------------------------------------------------------------

    def _start_history(self):
        if not load_settings()["history"] or self.client is None:
            return
        if self.history is None:
            self.history = HistoryRecorder()
            self.history.statusChanged.connect(self._on_history_status)
        self.history.start(self.client, self.capabilities)

    def _on_history_status(self, status, detail):
        if self._unloaded:
            return
        bar = self.iface.messageBar()
        if status == "unsaved":
            if self._history_bar is not None:
                return
            item = bar.createMessage(
                PLUGIN_NAME, tr("The robot is out: save the project to record its history "
                                "(kept in memory until then)."))
            button = QPushButton(tr("Save project…"))
            button.clicked.connect(self._save_project_for_history)
            item.layout().addWidget(button)
            self._history_bar = bar.pushWidget(item, Qgis.MessageLevel.Info, 0)
        elif status == "error":
            bar.pushMessage(PLUGIN_NAME, tr("History not written: {error}").format(error=detail),
                            level=Qgis.MessageLevel.Warning, duration=8)
        else:   # written
            self._hide_history_bar()   # the project has been saved
            if self.panel is not None:
                self.panel.history_tab.written(detail)

    def _save_project_for_history(self):
        self._hide_history_bar()
        self.iface.actionSaveProject().trigger()

    def _hide_history_bar(self):
        if self._history_bar is not None:
            try:
                self.iface.messageBar().popWidget(self._history_bar)
            except RuntimeError:
                pass
            self._history_bar = None

    def _center_on_robot(self, map_json, force=False):
        """Recentre on the robot when it leaves the middle of the view (no constant jitter)."""
        if not map_json:
            return
        for ent in map_json.get("entities", []):
            pts = ent.get("points") or []
            if ent.get("type") == "robot_position" and len(pts) >= 2:
                point = v2q(pts[0], pts[1])
                canvas = self.iface.mapCanvas()
                inner = canvas.extent().buffered(-0.2 * min(canvas.extent().width(),
                                                            canvas.extent().height()))
                if force or not inner.contains(point):
                    canvas.setCenter(point)
                    canvas.refresh()
                return

    # -- the robot project ------------------------------------------------------------

    @staticmethod
    def _is_robot_project():
        path = load_settings()["robot_project"]
        current = QgsProject.instance().fileName()
        return bool(path and current) and \
            os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(current))

    def _offer_robot_project(self):
        """QGIS started without a project and no robot project is set: say how to get
        the map shown at start-up (never a dialog at start-up)."""
        bar = self.iface.messageBar()
        item = bar.createMessage(PLUGIN_NAME, tr(
            "To show the robot on the map when QGIS starts, choose its project: the map, "
            "history and Wi-Fi maps are kept next to it."))
        button = QPushButton(tr("Robot project…"))
        button.clicked.connect(lambda: (bar.popWidget(widget), self._show_on_map()))
        item.layout().addWidget(button)
        widget = bar.pushWidget(item, Qgis.MessageLevel.Info, 0)

    def _show_on_map(self):
        live = self.act.get("live")
        if live is not None and live.isEnabled() and not live.isChecked():
            live.trigger()

    def _ensure_project(self):
        """True when the project has a file, so that the robot's layers can be kept
        next to it. Otherwise offer to open the robot project, or to save this one as
        the robot project."""
        if QgsProject.instance().fileName():
            return True
        path = load_settings()["robot_project"]
        box = QMessageBox(self.iface.mainWindow())
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(PLUGIN_NAME)
        box.setText(tr("This project has never been saved. The robot's map, history and "
                       "Wi-Fi maps are kept in folders next to the project."))
        open_button = None
        if path and os.path.exists(path):
            box.setInformativeText(tr("Open the robot project ({name}), or save this "
                                      "project as the robot project?")
                                   .format(name=os.path.basename(path)))
            open_button = box.addButton(tr("Open the robot project"),
                                        QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setInformativeText(tr("Save this project as the robot project?"))
        save_button = box.addButton(tr("Save as the robot project…"),
                                    QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(open_button or save_button)
        box.exec()
        if open_button is not None and box.clickedButton() is open_button:
            return self._open_robot_project(path)
        if box.clickedButton() is save_button:
            return self._save_as_robot_project(path)
        return False

    def _open_robot_project(self, path):
        project = QgsProject.instance()
        if not project.fileName() and not project.mapLayers():
            project.setDirty(False)   # an empty project: nothing worth saving
        # Changes to the current project: QGIS asks whether to save them first
        elif project.isDirty() and not self.iface.newProject(True):
            return False
        return bool(self.iface.addProject(path)) and bool(QgsProject.instance().fileName())

    def _save_as_robot_project(self, current=""):
        # A folder of its own: map/, history/ and wifi/ are created next to the project
        start = current or os.path.join(os.path.expanduser("~"), "DomotiQGIS", "robot.qgz")
        folder = os.path.dirname(start)
        made = not os.path.isdir(folder)
        if made:
            try:
                os.makedirs(folder)
            except OSError:
                made = False
        path, _filter = QFileDialog.getSaveFileName(
            self.iface.mainWindow(), tr("Save the robot project"), start,
            tr("QGIS projects (*.qgz *.qgs)"))
        used = bool(path) and os.path.dirname(os.path.abspath(path)) == os.path.abspath(folder)
        if made and not used and not os.listdir(folder):
            try:
                os.rmdir(folder)   # not used after all
            except OSError:
                pass
        if not path:
            return False
        if not path.lower().endswith((".qgz", ".qgs")):
            path += ".qgz"
        project = QgsProject.instance()
        project.setFileName(path)
        if not project.write():
            self._message(tr("Project not saved: {error}").format(error=project.error()),
                          Qgis.MessageLevel.Warning)
            return False
        QgsSettings().setValue(KEY_ROBOT_PROJECT, path)
        return True

    def toggle_live(self, checked):
        client = self._get_client()
        if not client or (checked and not self._ensure_project()):
            self.act["live"].setChecked(False)
            return
        if checked:
            client.start_polling(load_settings()["interval_s"] * 1000)
        else:
            client.stop_polling()

    # -- Wi-Fi survey -------------------------------------------------------------

    def toggle_wifi_survey(self, checked):
        if not checked:
            self.survey.stop()
            layer = self.survey.layer()
            if layer is not None and layer.featureCount() >= 3:
                self.build_wifi_map()
            return
        client = self._get_client()
        if not client or not self._ensure_project():   # its layers go next to the project
            self.act["wifi_survey"].setChecked(False)
            return
        if not self.layers.exists():
            client.fetch_map()   # points are only meaningful on top of the robot's map
        self._prepare_project()
        self.survey.start(client, load_settings())
        self._message(tr("Recording the Wi-Fi signal: start a cleaning, then click "
                         "“Record Wi-Fi survey” again when done."), Qgis.MessageLevel.Info)

    def _on_wifi_sample(self, count):
        if self.panel is not None:
            self.panel.show_feedback(tr("Wi-Fi survey: {n} point(s)").format(n=count))

    def build_wifi_map(self, *_):
        points = self.survey.layer() if self.survey is not None else None
        if points is None:
            self._message(tr("Record a Wi-Fi survey first."), Qgis.MessageLevel.Info)
            return
        cfg = load_settings()
        if not cfg["wifi_bad_dbm"] < cfg["wifi_fair_dbm"] < cfg["wifi_good_dbm"]:
            self._message(tr("Wi-Fi thresholds must be in order: bad < fair < good "
                             "(see the settings)."), Qgis.MessageLevel.Warning)
            return
        project = QgsProject.instance()
        for lyr in project.mapLayersByName(wifi_layer_names()["map"]):
            project.removeMapLayer(lyr.id())   # replace the previous map
        try:
            _raster, clipped = build_wifi_map(points, self.layers.layer("rooms"), cfg, project)
        except ValueError:
            self._message(tr("At least 3 Wi-Fi points are needed to build the map."),
                          Qgis.MessageLevel.Warning)
            return
        except RuntimeError as exc:
            QgsMessageLog.logMessage(str(exc), LOG_TAG, Qgis.MessageLevel.Warning)
            self._message(tr("Could not build the Wi-Fi map (details in the log)."),
                          Qgis.MessageLevel.Critical)
            return
        if cfg["wifi_clip_rooms"] and not clipped:
            self._message(tr("Wi-Fi map built, but it could not be clipped to the rooms."),
                          Qgis.MessageLevel.Warning)
        else:
            self._message(tr("Wi-Fi map built."), Qgis.MessageLevel.Success)

    def control(self, action):
        client = self._get_client()
        if client:
            client.basic_control(action)

    # -- no-go zones and virtual walls ---------------------------------------------

    def edit_restrictions(self, *_):
        """Load the robot's restrictions into two editable layers."""
        client = self._get_client()
        if not client or not self._ensure_project():   # its layers go next to the project
            return
        if not self.layers.exists():
            client.fetch_map()   # show the map too: zones are drawn on top of it
        client.fetch_restrictions()

    def _on_restrictions(self, data):
        if not self.layers.exists():
            self._prepare_project()
        zones, _walls = self.restrictions.load(data)
        if self._reload_quietly:   # after sending or discarding: just show the robot's state
            self._reload_quietly = False
            return
        zones.startEditing()
        self.iface.setActiveLayer(zones)
        self._show_edit_bar()

    def _propose_settings(self):
        """No robot set yet (first start): offer the setup assistant, once."""
        bar = self.iface.messageBar()
        item = bar.createMessage(PLUGIN_NAME, tr("No robot is set yet."))
        button = QPushButton(tr("Set up…"), item)

        def open_setup():
            try:
                bar.popWidget(item)
            except RuntimeError:   # already closed
                pass
            self.run_setup()

        button.clicked.connect(open_setup)
        item.layout().addWidget(button)
        bar.pushWidget(item, Qgis.MessageLevel.Info, 0)

    def _apply_advanced(self):
        """Show or hide the advanced tools (menus, toolbar, panel)."""
        on = load_settings()["advanced_tools"]
        for key in ADVANCED_ACTIONS:
            self.act[key].setVisible(on)
        self._update_map_tool_entries()
        if self.panel is not None:
            self.panel.set_advanced(on)

    # -- the app ------------------------------------------------------------------------

    def create_app_launcher(self, *_):
        from .app_launcher_dialog import AppLauncherDialog
        dialog = AppLauncherDialog(self.iface.mainWindow())
        if not dialog.exec():
            return
        values = dialog.values()
        try:
            result = app_launcher.create(**values)
        except ValueError:
            self._message(tr("Choose another profile than the one in use."),
                          Qgis.MessageLevel.Warning)
            return
        except OSError as exc:
            self._message(tr("App launcher not created: {error}").format(error=exc),
                          Qgis.MessageLevel.Critical)
            return
        lines = [tr("Profile: {folder}").format(folder=result["profile"])]
        if result["plugin"] == "copy":
            lines.append(tr("The plugin was copied into it (no link possible here): run "
                            "this again after updating the plugin."))
        if result["secrets"]:
            lines.append(tr("Tokens and passwords copied. At the first start, QGIS asks for "
                            "its master password (the same as here): tick the box that "
                            "stores it in your wallet, so that it is not asked again."))
        lines += [tr("Launcher: {path}").format(path=path) for path in result["launchers"]]
        if not result["launchers"]:
            lines.append(tr("No launcher: start it with {command}").format(
                command=" ".join(app_launcher.launch_command(values["profile"],
                                                             values["project"]))))
        QMessageBox.information(self.iface.mainWindow(), tr("DomotiQGIS as an app"),
                                "\n".join(lines))

    def _on_app_mode(self, checked):
        QgsSettings().setValue(KEY_APP_MODE, checked)
        self._enter_app_mode() if checked else self._leave_app_mode()

    def _main_window_parts(self):
        """The toolbars and panels of QGIS's window itself (not those inside panels)."""
        win = self.iface.mainWindow()
        bars = [b for b in win.findChildren(QToolBar) if b.parentWidget() is win]
        docks = [d for d in win.findChildren(QDockWidget) if d.parentWidget() is win]
        return bars, docks

    def _enter_app_mode(self, *_):
        if self._unloaded or self.act.get("app_mode") is None \
                or not self.act["app_mode"].isChecked():
            return
        bars, docks = self._main_window_parts()
        for bar in bars:
            if bar.objectName() not in APP_TOOLBARS:
                bar.hide()
        for dock in docks:
            if dock is not self.panel:
                dock.hide()
        if self.panel is not None:
            self.panel.show()
            self.panel.raise_()

    def _leave_app_mode(self):
        bars, docks = self._main_window_parts()
        for bar in bars:
            bar.show()
        for dock in docks:
            if dock.objectName() in ("Layers", "Browser"):
                dock.show()

    def run_setup(self, *_):
        """The setup assistant: robot address, other servers; then show the robot."""
        from .setup_wizard import SetupWizard
        wizard = SetupWizard(self.iface.mainWindow())
        if not wizard.exec():
            return
        wizard.save()
        self._on_settings_applied()
        if self.panel is not None:
            self.panel.show()

    def _show_edit_bar(self):
        """Persistent bar while editing: what to do, Send to robot…, Discard changes."""
        self._hide_edit_bar()
        names = restriction_layer_names()
        bar = self.iface.messageBar()
        item = bar.createMessage(
            tr("No-go zones and walls"),
            tr("Edit the “{zones}” (polygons) and “{walls}” (lines) layers.").format(
                zones=names["zones"], walls=names["walls"]))
        send = QPushButton(tr("Send to robot…"), item)
        send.clicked.connect(self.send_restrictions)
        discard = QPushButton(tr("Discard changes"), item)
        discard.clicked.connect(self.discard_restrictions)
        item.layout().addWidget(send)
        item.layout().addWidget(discard)
        bar.pushWidget(item, Qgis.MessageLevel.Info, 0)
        self._edit_bar = item

    def _hide_edit_bar(self):
        if self._edit_bar is not None:
            try:
                self.iface.messageBar().popWidget(self._edit_bar)
            except RuntimeError:   # already closed by the user
                pass
            self._edit_bar = None

    def discard_restrictions(self, *_):
        """Drop the edits and reload what the robot currently has."""
        self._hide_edit_bar()
        for role in ("zones", "walls"):
            lyr = self.restrictions.layer(role)
            if lyr is not None and lyr.isEditable():
                lyr.rollBack()
        client = self._get_client()
        if client:
            self._reload_quietly = True
            client.fetch_restrictions()

    def send_restrictions(self, *_):
        if not self.restrictions.exists():
            self._message(tr("Use “Edit no-go zones and walls” first."), Qgis.MessageLevel.Info)
            return
        client = self._get_client()
        if not client:
            return
        payload, warnings = self.restrictions.to_payload()
        text = tr("Send {zones} no-go zone(s) and {walls} virtual wall(s) to the robot?\n"
                  "They replace all the restrictions currently on the robot.").format(
            zones=len(payload["restrictedZones"]), walls=len(payload["virtualWalls"]))
        notes = []
        if warnings["zones_approximated"]:
            notes.append(tr("{n} zone(s) without exactly 4 corners are replaced by their "
                            "bounding rectangle.").format(n=warnings["zones_approximated"]))
        if warnings["walls_simplified"]:
            notes.append(tr("{n} wall(s) with more than 2 points become straight "
                            "lines between their ends.").format(n=warnings["walls_simplified"]))
        if warnings["skipped"]:
            notes.append(tr("{n} empty or invalid shape(s) are ignored.").format(
                n=warnings["skipped"]))
        if notes:
            text += "\n\n" + "\n".join(notes)
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Send no-go zones and walls"), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._hide_edit_bar()
            self._reload_quietly = True   # the reload after sending shows, not edits
            client.set_restrictions(payload)

    def simple_command(self, key):
        client = self._get_client()
        if client:
            client.simple_command(key)

    # -- map tools --------------------------------------------------------------

    def _activate_tool(self, tool, key, checked, hint):
        canvas = self.iface.mapCanvas()
        action = self.act[key]
        if not checked:  # clicking the active tool again turns it off
            if canvas.mapTool() is tool:
                self.iface.actionPan().trigger()
            return
        if not self._get_client():
            action.setChecked(False)
            return
        if not self.layers.exists():
            # Coordinates are only meaningful in the robot's frame, i.e. once its map is shown.
            action.setChecked(False)
            self._message(tr("Show the map first."), Qgis.MessageLevel.Info)
            return
        canvas.setMapTool(tool)
        self._message(hint, Qgis.MessageLevel.Info)

    def activate_zone_tool(self, checked):
        self._activate_tool(self.zone_tool, "zone", checked,
                            tr("Drag a rectangle on the map to clean that zone."))

    def activate_pick_tool(self, checked):
        self._activate_tool(self.pick_tool, "pick_rooms", checked,
                            tr("Click rooms on the map to tick them in the Clean tab; "
                               "right-click a room for its menu."))

    def activate_sensor_tool(self, checked):
        self._activate_tool(self.sensor_tool, "place_sensor", checked,
                            tr("Click the map to place a Home Assistant sensor; "
                               "right-click a sensor to remove it."))

    def _on_place_sensor(self, point):
        self.iface.actionPan().trigger()   # one placement per click, like "Go to"
        if self.sensors is None:
            return
        if not has_ha_token():
            self._message(tr("Set the Home Assistant address and token first, in the "
                             "settings."), Qgis.MessageLevel.Warning)
            return
        x, y = q2v(point)
        self._message(tr("Loading the sensor list from Home Assistant…"),
                      Qgis.MessageLevel.Info)

        def ready(entities):
            if not entities:
                self._message(tr("No sensor found in Home Assistant."),
                              Qgis.MessageLevel.Warning)
                return
            choices = [tr("{name}  ({entity})").format(name=name, entity=eid)
                       for eid, name in entities]
            choice, accepted = QInputDialog.getItem(
                self.iface.mainWindow(), tr("Place a sensor"),
                tr("Sensor to show at this point:"), choices, 0, False)
            if not accepted:
                return
            entity_id, name = entities[choices.index(choice)]
            self.sensors.add_sensor(entity_id, x, y)
            self._message(tr("Sensor “{name}” placed.").format(name=name),
                          Qgis.MessageLevel.Success)

        def failed(message):
            self._message(tr("Could not reach Home Assistant: {error}").format(error=message),
                          Qgis.MessageLevel.Warning)

        self.sensors.fetch_entities(ready, failed)

    def _on_remove_sensor(self, point):
        if self.sensors is None:
            return
        x, y = q2v(point)
        entity_id = self.sensors.nearest(x, y, SENSOR_REMOVE_TOLERANCE_CM)
        if not entity_id:
            self._message(tr("No sensor here to remove."), Qgis.MessageLevel.Info)
            return
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Remove sensor"),
            tr("Remove “{entity}” from the map?").format(entity=entity_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.sensors.remove_sensor(entity_id)
            self._message(tr("Sensor removed."), Qgis.MessageLevel.Success)

    def _on_sensors_updated(self, items):
        if getattr(self, "_unloaded", False):
            return
        if self.layers.exists():
            self.layers.update_sensors(items)

    def _on_room_clicked(self, seg_id, name, right_button, global_pos):
        if self.panel is None:
            return
        if right_button:
            self.panel.room_menu(seg_id, name, global_pos)
        else:
            self.panel.toggle_room(seg_id)
            if not self.panel.isVisible():
                self.panel.show()
            self.panel.show_tab("clean")   # see the room ticked, and clean it

    def _build_toolbar(self):
        """The commands chosen in the settings (UI configuration tab). The map tools
        come last, as buttons (hiding them there leaves the menus alone), shown while
        "Show on map" is on."""
        if self.toolbar is None:
            return
        for _entry, button in self._map_tool_entries:
            if button is not None:
                button.deleteLater()
        self.toolbar.clear()
        chosen = toolbar_keys()
        for key in TOOLBAR_CHOICES:
            if key in chosen and key not in MAP_TOOLS and key in self.act:
                self.toolbar.addAction(self.act[key])
        tools = [key for key in MAP_TOOLS if key in chosen and key in self.act]
        # [(toolbar entry, its button or None for the separator)]
        self._map_tool_entries = [(self.toolbar.addSeparator(), None)] if tools else []
        for key in tools:
            button = QToolButton(self.toolbar)
            button.setDefaultAction(self.act[key])
            button.setAutoRaise(True)
            self._map_tool_entries.append((self.toolbar.addWidget(button), button))
        self._update_map_tool_entries()

    def _update_map_tool_entries(self):
        """The map tools in the toolbar: while "Show on map" is on, and only those whose
        command is available (e.g. the advanced ones while Advanced tools is on)."""
        live = self.act.get("live")
        shown = live is not None and live.isChecked()
        for entry, button in getattr(self, "_map_tool_entries", []):
            entry.setVisible(shown and (button is None or button.defaultAction().isVisible()))

    def _on_live_toggled(self, checked):
        """The map tools and the status card come with "Show on map"."""
        self._update_map_tool_entries()
        if self.overlay is not None:
            self.overlay.set_visible(checked)
        if self.sensors is not None:
            # Poll Home Assistant for sensor values only while the map is shown.
            self.sensors.start(SENSOR_POLL_MS) if checked else self.sensors.stop()

    def activate_goto_tool(self, checked):
        self._activate_tool(self.goto_tool, "goto", checked,
                            tr("Click on the map to send the robot there."))

    def _on_zone(self, rect):
        self.iface.actionPan().trigger()  # one zone per activation: no accidental resend
        if rect.width() < MIN_ZONE_SIZE_CM or rect.height() < MIN_ZONE_SIZE_CM:
            self._message(tr("Zone too small."), Qgis.MessageLevel.Warning)
            return
        client = self._get_client()
        if client:
            client.clean_zone_qgis(rect, self.panel.passes() if self.panel is not None else 1)

    # -- room split -----------------------------------------------------------------

    def _start_split(self, seg_id, name):
        """From the rooms list: draw the cut line on the map (two clicks)."""
        client = self._get_client()
        if not client or not (self.layers.exists() or self._ensure_project()):
            return
        if not self.layers.exists():
            client.fetch_map()   # the line is drawn on the robot's map
        self._split_room = (seg_id, name)
        self.iface.mapCanvas().setMapTool(self.split_tool)
        self._message(tr("Split “{room}”: click the two ends of the cut line on the map "
                         "(from wall to wall). Right-click or Esc to cancel.").format(room=name),
                      Qgis.MessageLevel.Info)

    def _on_split_line(self, point_a, point_b):
        self.iface.actionPan().trigger()
        room, self._split_room = self._split_room, None
        client = self._get_client()
        if room is None or not client:
            return
        seg_id, name = room
        length = point_a.distance(point_b) / 100
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Split room"),
            tr("Split “{room}” along this {length} m line?\n\n"
               "The robot only accepts a line that crosses the room from wall to wall.")
            .format(room=name, length=f"{length:.1f}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            client.split_segment_qgis(seg_id, point_a, point_b)

    def _on_goto(self, point):
        self.iface.actionPan().trigger()
        client = self._get_client()
        if not client:
            return
        if self.capabilities is None or "GoToLocationCapability" in self.capabilities:
            client.go_to_qgis(point)
            return
        # No native go-to: tiny zone clean towards the point, then pause on arrival.
        if not QgsSettings().value(KEY_GOTO_ZONE_OK, False, type=bool):
            if QgsSettings().value(KEY_GOTO_QUIET, True, type=bool):
                text = tr("This robot cannot simply drive to a point. The plugin will "
                          "send it to clean a small zone ({size} cm) at that point, "
                          "then pause it as soon as it arrives.\n\n"
                          "“Without cleaning” is ticked: for the trip, the mops are "
                          "lifted (vacuum-only mode), the water is turned off and the fan set "
                          "to its lowest; your settings are restored on arrival. If the robot "
                          "has no “off” fan speed, it still vacuums gently.\n\n"
                          "Continue?").format(size=GOTO_ZONE_SIZE_CM)
            else:
                text = tr("This robot cannot simply drive to a point. The plugin will "
                          "send it to clean a small zone ({size} cm) at that point, "
                          "then pause it as soon as it arrives.\n\n"
                          "It vacuums on its way, and mops if mopping is on.\n\n"
                          "Continue?").format(size=GOTO_ZONE_SIZE_CM)
            box = QMessageBox(QMessageBox.Icon.Question, tr("Go here"), text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                              self.iface.mainWindow())
            box.setDefaultButton(QMessageBox.StandardButton.No)
            dont_ask = QCheckBox(tr("Don't ask again"))
            box.setCheckBox(dont_ask)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            if dont_ask.isChecked():
                QgsSettings().setValue(KEY_GOTO_ZONE_OK, True)
        if self.goto_emulator.is_running() or self.quiet_travel.is_active():
            self.goto_emulator.stop()
            self.quiet_travel.restore(client)   # previous trip: back to the user's settings
        if QgsSettings().value(KEY_GOTO_QUIET, True, type=bool):
            caps = self.capabilities
            if caps is not None and not any(cap in caps for cap, _kind, _prefs in QUIET_PRESETS):
                self._message(tr("This robot's fan, water and mode cannot be changed: "
                                 "it will clean on its way."), Qgis.MessageLevel.Warning)
            else:
                # Quiet settings first; the trip starts once they are applied.
                self._goto_point = point
                self.quiet_travel.prepare(client, caps)
                return
        self._start_goto(client, point)

    def _start_goto(self, client, point):
        self.goto_emulator.start(client, point)
        if self.history is not None:
            self.history.expect("go_to")   # not the zone cleaning that emulates it
        self._message(tr("Robot on its way; it will be paused on arrival."),
                      Qgis.MessageLevel.Info)

    def _on_quiet_ready(self, applied):
        point, self._goto_point = getattr(self, "_goto_point", None), None
        if self._unloaded or point is None or self.client is None:
            self.quiet_travel.restore()
            return
        labels = preset_labels()
        names = {"OperationModeControlCapability": tr("Mode"),
                 "WaterUsageControlCapability": tr("Water usage"),
                 "FanSpeedControlCapability": tr("Fan speed")}
        changes = ", ".join(f"{names.get(cap, cap)}: {labels.get(value, value)}"
                            for cap, value in applied)
        self.goto_emulator.start(self.client, point)
        if self.history is not None:
            self.history.expect("go_to")
        self._message(tr("Robot on its way without cleaning ({changes}); it will be paused on "
                         "arrival, then your settings restored.").format(
                             changes=changes or tr("settings already at their lowest")),
                      Qgis.MessageLevel.Info)

    def _on_quiet_failed(self, error):
        self._goto_point = None
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME, tr("“Go to” cancelled: the robot's settings could not be changed for "
                           "a trip without cleaning ({error}). Untick “Without cleaning” "
                           "to go anyway.").format(error=error),
            level=Qgis.MessageLevel.Warning, duration=0)

    def _on_goto_finished(self, result, detail):
        if self.quiet_travel.is_active() and self.client is not None:
            # After the pause on arrival (sent just before this signal).
            QTimer.singleShot(1000, lambda: self.client and self.quiet_travel.restore(self.client))
        if result == "arrived":
            self._message(tr("Robot arrived ({distance} cm from the point) and paused. "
                             "Use “Return to dock” to send it back.").format(distance=detail),
                          Qgis.MessageLevel.Success)
        elif result == "gave_up":
            self._message(tr("The robot stopped before reaching the point (state: {state}).")
                          .format(state=dock_state_label(detail)), Qgis.MessageLevel.Warning)
        elif result == "timeout":
            self._message(tr("The robot did not reach the point within {minutes} min.")
                          .format(minutes=detail), Qgis.MessageLevel.Warning)

    # -- reboot over SSH --------------------------------------------------------

    def reboot_robot(self, *_):
        cfg = load_settings()
        if not cfg["url"] and not self.configure():
            return
        cfg = load_settings()
        host = QUrl(cfg["url"]).host()
        if not host:
            return
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Reboot robot"),
            tr("Reboot the robot now over SSH ({user}@{host})?\n\n"
               "Any cleaning in progress will be interrupted. The robot will be "
               "unreachable for a minute or two.").format(user=cfg["ssh_user"], host=host),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.act["reboot"].setEnabled(False)   # one reboot at a time
        self._reboot.start(host, cfg["ssh_user"], cfg["ssh_port"])

    def _on_reboot_finished(self, result, detail):
        if "reboot" in self.act:
            self.act["reboot"].setEnabled(True)
        if result == "sent":
            self._message(tr("Reboot command sent. The robot will be back in a minute or two."),
                          Qgis.MessageLevel.Success)
            self._start_boot_monitor(expect_offline=True)
        elif result == "ssh_missing":
            self._message(tr("ssh not found: install an SSH client."), Qgis.MessageLevel.Critical)
        else:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME, tr("SSH reboot failed: {detail}").format(detail=detail),
                level=Qgis.MessageLevel.Critical, duration=0)

    # -- Wi-Fi survey recorded on the robot ------------------------------------------

    def _ssh_target(self):
        """(host, user, port, settings) or None when no robot address is set."""
        cfg = load_settings()
        host = QUrl(cfg["url"]).host() if cfg["url"] else ""
        return (host, cfg["ssh_user"], cfg["ssh_port"], cfg) if host else None

    def _update_robot_survey_actions(self):
        """Install only when not installed; import and remove only when installed.
        Nothing while an SSH operation runs."""
        directory = QgsSettings().value(KEY_ROBOT_SURVEY_DIR, "", type=str)
        installed = bool(directory)
        if self.panel is not None:   # Wi-Fi tab: where the recorder stands
            self.panel.set_robot_recorder_status(
                tr("Installed in {dir}: records whenever the robot moves, "
                   "even with QGIS closed.").format(dir=directory) if installed
                else tr("Not installed."))
        robot_survey = getattr(self, "robot_survey", None)
        busy = robot_survey is not None and robot_survey.is_busy()
        install = self.act.get("robot_survey_install")
        if install is not None:
            install.setEnabled(not installed and not busy)
            install.setToolTip(
                tr("Already recording on the robot. To install it again, remove it first.")
                if installed else command_hints()["robot_survey_install"])
        for key in ("robot_survey_import", "robot_survey_remove"):
            if key in self.act:
                self.act[key].setEnabled(installed and not busy)
        if self.panel is not None:
            self.panel.history_tab.set_robot_import(installed, busy)

    def _robot_survey_run(self, operation, command, stdin=b""):
        target = self._ssh_target()
        if target is None:
            return False
        host, user, port, _cfg = target
        if not self.robot_survey.run(operation, host, user, port, command, stdin):
            self._message(tr("Another Wi-Fi recorder operation is running."),
                          Qgis.MessageLevel.Info)
            return False
        self._update_robot_survey_actions()   # greyed out while it runs
        return True

    def install_robot_survey(self, *_):
        if self._ssh_target() is None and not self.configure():
            return
        target = self._ssh_target()
        if target is None:
            return
        host, user, _port, cfg = target
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Record Wi-Fi on the robot"),
            tr("Install the Wi-Fi recorder on the robot ({user}@{host}) and start it?\n\n"
               "From then on, whenever the robot moves (cleaning, returning to its dock…), "
               "it records its Wi-Fi signal and position on the robot itself, every {interval} s, "
               "even when QGIS is closed. Use “Import Wi-Fi from the robot” to bring the "
               "readings into QGIS.\n\n"
               "It uses SSH with your key, as the reboot does. After a robot reboot, the "
               "plugin starts it again the next time it connects.").format(
                user=user, host=host, interval=max(1, round(cfg["wifi_interval_s"]))),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return
        with open(robot_survey.SCRIPT_PATH, "rb") as f:
            script = f.read()
        if self._robot_survey_run("install", robot_survey.install_command(
                cfg["wifi_interval_s"], cfg["wifi_min_step_cm"]), script):
            self._message(tr("Installing the Wi-Fi recorder on the robot…"),
                          Qgis.MessageLevel.Info)

    def _ensure_robot_survey(self):
        directory = QgsSettings().value(KEY_ROBOT_SURVEY_DIR, "", type=str)
        target = self._ssh_target()
        if directory and target is not None and not self.robot_survey.is_busy():
            cfg = target[3]
            self._robot_survey_run("ensure", robot_survey.ensure_command(
                directory, cfg["wifi_interval_s"], cfg["wifi_min_step_cm"]))

    def import_robot_survey(self, *_):
        directory = QgsSettings().value(KEY_ROBOT_SURVEY_DIR, "", type=str)
        if directory and self._robot_survey_run("import", robot_survey.import_command(directory)):
            self._message(tr("Reading the Wi-Fi survey from the robot…"), Qgis.MessageLevel.Info)

    def _import_robot_history(self, auto):
        """The outings recorded on the robot while QGIS was not recording.
        auto: at connection, quiet when there is nothing to do."""
        tab = self.panel.history_tab if self.panel is not None else None
        directory = QgsSettings().value(KEY_ROBOT_SURVEY_DIR, "", type=str)
        if not directory:
            if not auto and tab is not None:
                tab.set_info(tr("Install the Wi-Fi recorder on the robot first (Wi-Fi tab): it "
                                "also records the outings made while QGIS is closed."))
            return
        if self.history is None or history_folder() is None:
            if not auto and tab is not None:
                tab.set_info(tr("Save the project first, and turn on Record the robot's "
                                "outings in the settings."))
            return
        self._history_import_auto = auto
        if self._robot_survey_run("history", robot_survey.history_command(directory)) \
                and not auto and tab is not None:
            tab.set_info(tr("Reading the robot's recorder…"))

    def _on_robot_history(self, ok, output, values, detail):
        auto = getattr(self, "_history_import_auto", True)
        tab = self.panel.history_tab if self.panel is not None else None
        if not ok or self.history is None:
            if not auto and tab is not None:
                tab.set_info(tr("Could not read the robot's recorder: {detail}").format(
                    detail=detail))
            return
        try:
            robot_now = int(values.get("now"))
        except (TypeError, ValueError):
            robot_now = None
        result = self.history.import_robot(robot_survey.parse_rows(output), robot_now)
        if result is None:
            return
        if "error" in result:
            text = tr("History not written: {error}").format(error=result["error"])
        elif result["outings"]:
            text = tr("{n} outing(s) recorded by the robot added to the history.").format(
                n=result["outings"])
        else:
            text = tr("Nothing new on the robot: its outings are already in the history.")
        if result.get("offset_s"):
            text += " " + tr("(Robot clock off by {s} s: corrected.)").format(
                s=result["offset_s"])
        if tab is not None and (not auto or result.get("outings") or "error" in result):
            tab.set_info(text)
        if auto and result.get("outings"):
            self._message(text, Qgis.MessageLevel.Info)

    def remove_robot_survey(self, *_):
        directory = QgsSettings().value(KEY_ROBOT_SURVEY_DIR, "", type=str)
        if not directory:
            return
        answer = QMessageBox.question(
            self.iface.mainWindow(), tr("Remove Wi-Fi recorder from robot"),
            tr("Stop the Wi-Fi recorder on the robot and delete it, with the readings not "
               "imported yet?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._robot_survey_run("remove", robot_survey.remove_command(directory))

    def _on_robot_survey_finished(self, operation, ok, output, detail):
        if self._unloaded:
            return
        self._update_robot_survey_actions()   # the operation is over (and on early returns)
        if detail == "ssh_missing":
            self._message(tr("ssh not found: install an SSH client."), Qgis.MessageLevel.Critical)
            return
        values = robot_survey.parse_keys(output)
        if operation == "ensure":
            if values.get("missing"):   # removed from the robot by other means
                QgsSettings().remove(KEY_ROBOT_SURVEY_DIR)
                self._update_robot_survey_actions()
            elif ok:
                self._import_robot_history(auto=True)   # what it recorded without QGIS
            return   # quiet: runs at each connection
        if operation == "history":
            self._on_robot_history(ok, output, values, detail)
            return
        if not ok and operation != "import":
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME, tr("Wi-Fi recorder: SSH failed: {detail}").format(
                    detail=values.get("error") or detail),
                level=Qgis.MessageLevel.Critical, duration=0)
            return
        if operation == "install":
            QgsSettings().setValue(KEY_ROBOT_SURVEY_DIR, values.get("dir", ""))
            self._update_robot_survey_actions()
            tools = set(values.get("tool", "").split(","))
            problems = []
            if not tools & {"wget", "curl"}:
                problems.append(tr("neither wget nor curl on the robot"))
            if not values.get("position"):
                problems.append(tr("the robot position could not be read"))
            if not values.get("signal"):
                problems.append(tr("the Wi-Fi signal could not be read"))
            if problems:
                self.iface.messageBar().pushMessage(
                    PLUGIN_NAME, tr("Wi-Fi recorder installed in {dir}, but: {problems}. "
                                   "It will not record until this is solved.").format(
                        dir=values.get("dir", "?"), problems="; ".join(problems)),
                    level=Qgis.MessageLevel.Warning, duration=0)
            else:
                self._message(tr("Wi-Fi recorder running on the robot (in {dir}; now: {signal} "
                                 "dBm). It records whenever the robot moves.").format(
                    dir=values.get("dir", "?"), signal=values.get("signal")),
                    Qgis.MessageLevel.Success)
        elif operation == "import":
            rows = robot_survey.parse_rows(output)
            if not rows:
                self._message(tr("No Wi-Fi readings on the robot yet: they are recorded "
                                 "while it moves."), Qgis.MessageLevel.Info)
                return
            self._prepare_project()   # the points are in the robot's own frame
            if not self.layers.exists() and self.client is not None:
                self.client.fetch_map()   # the readings mean more on top of the map
            added = self.survey.add_rows(rows, load_settings())
            sessions = len({r["session"] for r in rows})
            self._message(tr("{added} new point(s) imported ({total} reading(s) in {sessions} "
                             "run(s) on the robot).").format(added=added, total=len(rows),
                                                             sessions=sessions),
                          Qgis.MessageLevel.Success)
            if added and self.survey.layer() is not None \
                    and self.survey.layer().featureCount() >= 3:
                self.build_wifi_map()
        elif operation == "remove":
            QgsSettings().remove(KEY_ROBOT_SURVEY_DIR)
            self._update_robot_survey_actions()
            self._message(tr("Wi-Fi recorder removed from the robot."), Qgis.MessageLevel.Success)

    # -- Wi-Fi maps built on the Raspberry Pi -----------------------------------------

    def _update_pi_actions(self):
        action = self.act.get("pi_wifi_map")
        if action is not None:
            has_pi = bool(load_settings()["pi_host"])
            busy = getattr(self, "pi_ssh", None) is not None and self.pi_ssh.is_busy()
            action.setEnabled(has_pi and not busy)
            action.setToolTip(command_hints()["pi_wifi_map"] if has_pi else
                              tr("Set the Raspberry Pi in Settings › Options › {name} first.").format(name=PLUGIN_NAME))

    def load_pi_wifi_map(self, full=None):
        """full: the map of all runs (None: as last chosen)."""
        if full is not None:
            QgsSettings().setValue(KEY_PI_MAP_FULL, bool(full))
        cfg = load_settings()
        if not cfg["pi_host"]:
            return
        full = QgsSettings().value(KEY_PI_MAP_FULL, False, type=bool)
        if self.pi_ssh.run("pi_map", cfg["pi_host"], cfg["pi_user"], cfg["pi_port"],
                           pi_maps.fetch_command(cfg["pi_wifi_dir"], full)):
            self._update_pi_actions()
            self._message(tr("Reading the full Wi-Fi map from the Pi…") if full else
                          tr("Reading the latest Wi-Fi map from the Pi…"), Qgis.MessageLevel.Info)

    def _on_pi_wifi_map(self, _operation, ok, _text, detail):
        if self._unloaded:
            return
        self._update_pi_actions()
        cfg = load_settings()
        data = self.pi_ssh.output_bytes
        if detail == "ssh_missing":
            self._message(tr("ssh not found: install an SSH client."), Qgis.MessageLevel.Critical)
            return
        problems = {
            "error=no_folder": tr("the folder “{folder}” does not exist on the Pi"),
            "error=no_map": tr("no map in “{folder}” yet (none built by the Pi)"),
            "error=no_full_map": tr("no full map in “{folder}” yet (the Pi builds it after "
                                    "its next run; update its script if needed)"),
        }
        if not data:
            text = problems.get(detail, tr("SSH failed: {detail}")).format(
                folder=cfg["pi_wifi_dir"], detail=detail)
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME, tr("No Wi-Fi map loaded: {problem}.").format(problem=text),
                level=Qgis.MessageLevel.Warning, duration=0)
            return
        try:
            run, tif, csv_path, png = pi_maps.unpack(data)
            if self.panel is not None:
                self.panel.set_pi_thumbnail(png)
            self._prepare_project()   # the map is in the robot's own frame
            raster, points = pi_maps.add_to_project(QgsProject.instance(), run, tif, csv_path,
                                                    cfg)
        except Exception as exc:   # damaged archive, unreadable GeoTIFF…
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME, tr("No Wi-Fi map loaded: {problem}.").format(problem=str(exc)),
                level=Qgis.MessageLevel.Warning, duration=0)
            return
        if not self.layers.exists():   # nothing else on the map yet: show the Wi-Fi map
            canvas = self.iface.mapCanvas()
            canvas.setExtent(raster.extent())
            canvas.refresh()
        count = points.featureCount() if points is not None else 0
        self._message(tr("Wi-Fi map of {run} loaded ({n} reading(s)).").format(
            run=pi_maps.run_label(run), n=count), Qgis.MessageLevel.Success)

    # -- boot monitor -------------------------------------------------------------

    def watch_boot(self, *_):
        """Follow a boot started elsewhere (power button…), or check that all is up."""
        self._start_boot_monitor(expect_offline=False)

    def _start_boot_monitor(self, expect_offline):
        client = self._get_client()
        if not client:
            return
        cfg = load_settings()
        host = QUrl(cfg["url"]).host()
        camera_port = QUrl(cfg["camera_url"]).port() if cfg["camera_url"] else -1
        self.panel.clear_boot_log()
        self.boot.start(client, host, cfg["ssh_port"],
                        camera_port if camera_port > 0 else None, expect_offline)

    def _boot_text(self, key, detail):
        if key == "started":
            return tr("Watching the robot boot…")
        if key == "offline":
            return tr("Robot went offline (rebooting).")
        if key == "no_offline":
            return tr("The robot did not go offline: the reboot may not have happened.")
        if key == "network_up":
            return tr("Network up: the robot's SSH port answers (system booted).")
        if key == "valetudo_up":
            return tr("Valetudo answers (version {version}).").format(version=detail)
        if key == "robot_ready":
            state, _, battery = detail.partition(";")
            state = dock_state_label(state)
            return tr("Robot firmware ready: {state}, battery {battery} %.").format(
                state=state, battery=battery)
        if key == "camera_up":
            return tr("Camera stream available.")
        if key == "camera_missing":
            return tr("Camera stream still not available after {seconds} s.").format(
                seconds=detail)
        if key == "done":
            return tr("Robot fully back after {seconds} s.").format(seconds=detail)
        if key == "timeout":
            return tr("The robot is still not back after {minutes} min.").format(minutes=detail)
        return key

    def _on_boot_stage(self, key, seconds, detail):
        text = self._boot_text(key, detail)
        line = f"[+{seconds:5.1f} s] {text}"
        problem = key in ("no_offline", "camera_missing", "timeout")
        QgsMessageLog.logMessage(line, LOG_TAG, Qgis.MessageLevel.Warning if problem
                                 else Qgis.MessageLevel.Info)
        self.panel.add_boot_log(line)
        if key == "done":
            self._message(text, Qgis.MessageLevel.Success)
        elif problem:
            self._message(text, Qgis.MessageLevel.Warning)

    def _on_boot_log_tail(self, lines):
        if not lines:
            note = tr("Valetudo's log is not available.")
            QgsMessageLog.logMessage(note, LOG_TAG, Qgis.MessageLevel.Info)
            self.panel.add_boot_log(note)
            return
        header = tr("End of Valetudo's log:")
        QgsMessageLog.logMessage(header + "\n" + "\n".join(lines), LOG_TAG,
                                 Qgis.MessageLevel.Info)
        self.panel.add_boot_log(header)
        for line in lines:
            self.panel.add_boot_log("  " + line)

    # ------------------------------------------------------------------
    # Incoming data
    # ------------------------------------------------------------------

    def _on_map(self, map_json):
        self._last_map = map_json
        self.panel.update_map(map_json)
        if not QgsProject.instance().fileName():
            return   # no folder to keep the layers in (Show on map asks for a project)
        if not self.layers.exists():
            self._prepare_project()
        try:
            created = self.layers.update(map_json)
        except OSError as exc:   # layers updated, but the map file not written
            created = False
            if not getattr(self, "_map_file_error", False):
                self._map_file_error = True
                self._message(tr("Robot map not saved: {error}").format(error=exc),
                              Qgis.MessageLevel.Warning)
        if created:
            canvas = self.iface.mapCanvas()
            canvas.setExtent(self.layers.layer("rooms").extent())
            canvas.refresh()
        if self.sensors is not None:   # draw the sensors with their latest known values
            self.layers.update_sensors(self.sensors.items())
        if (self.act.get("live") is not None and self.act["live"].isChecked()
                and follow_robot()):
            self._center_on_robot(map_json)   # keep the robot in view, if asked

    def _prepare_project(self):
        """Switch the project to "No CRS", silently: we work in the robot's own frame."""
        project = QgsProject.instance()
        if project.crs().isValid():
            project.setCrs(QgsCoordinateReferenceSystem())

    def _on_error(self, msg):
        self._message(msg, Qgis.MessageLevel.Warning)

    def _on_command_done(self, key):
        if key == "restrictions" and self.client is not None:
            self.client.fetch_map()          # show what the robot now uses
            self.client.fetch_restrictions()  # and reload the editable layers from it
        if key in ("rename_room", "join_rooms", "split_room") and self.client is not None:
            self.client.fetch_segments(quiet=True)   # new names / rooms in the list
            if self.layers.exists():
                # The robot may need a moment to rebuild its map: reload now and soon.
                self.client.fetch_map()
                QTimer.singleShot(3000, lambda: self.client and self.client.fetch_map())
        label = command_labels().get(key, key)
        self._message(tr("Command “{command}” sent.").format(command=label),
                      Qgis.MessageLevel.Success)

    def _message(self, text, level):
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, level=level, duration=4)
        if self.panel is not None:   # echo it under the command list
            kind = {Qgis.MessageLevel.Success: "success", Qgis.MessageLevel.Warning: "warning",
                    Qgis.MessageLevel.Critical: "critical"}.get(level, "info")
            self.panel.show_feedback(text, kind)
