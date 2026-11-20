"""Plugin settings, stored in QgsSettings (edited in Settings › Options › DomotiQGIS).

Passwords are never stored in clear text: credentials go through the QGIS
authentication manager (QgsAuthConfigSelect), which encrypts them.
"""

from qgis.PyQt.QtCore import QUrl
from qgis.core import QgsSettings

from . import servers as servers_model
from .servers import on_host, ssh_address  # noqa: F401  (imported from here elsewhere)

PLUGIN_NAME = "DomotiQGIS"   # shown in menus, titles and messages (not translated)
KEY_URL = "valetudo/url"
KEY_AUTH = "valetudo/authcfg"
KEY_INTERVAL = "valetudo/interval_s"
KEY_CAMERA_URL = "valetudo/camera_url"
KEY_FFMPEG = "valetudo/ffmpeg"
KEY_CAMERA_WIDTH = "valetudo/camera_width"
KEY_NOTIFY_DOCK = "valetudo/notify_dock"
KEY_LIVE_AT_START = "valetudo/live_at_start"   # "Show on map" when QGIS starts
KEY_SSH_USER = "valetudo/ssh_user"
KEY_SSH_PORT = "valetudo/ssh_port"
KEY_PI_HOST = "valetudo/pi_host"   # Raspberry Pi (or other Linux machine): empty = none
KEY_PI_USER = "valetudo/pi_user"
KEY_PI_PORT = "valetudo/pi_port"
KEY_PI_WIFI_DIR = "valetudo/pi_wifi_dir"   # output folder of pi/valetudo_wifi_collect.py
KEY_HA_URL = "valetudo/ha_url"   # Home Assistant server
KEY_NUC_HOST = "valetudo/nuc_host"   # empty = no NUC block in the Status tab
KEY_NUC_USER = "valetudo/nuc_user"
KEY_NUC_PORT = "valetudo/nuc_port"
KEY_NUC_WEB_URL = "valetudo/nuc_web_url"   # optional web interface (e.g. Cockpit)
KEY_PI_WEB_URL = "valetudo/pi_web_url"     # optional web interface (e.g. Uptime Kuma)
KEY_NUC_LOG_COMMAND = "valetudo/nuc_log_command"   # empty = NUC_AUTO_LOG_COMMAND
# The system log, wherever it is: the journal under systemd, else syslog
# (sysvinit, e.g. MX Linux by default).
NUC_AUTO_LOG_COMMAND = ("if [ -d /run/systemd/system ] && command -v journalctl >/dev/null; "
                        "then journalctl -n 200 -f; else tail -n 200 -F /var/log/syslog; fi")
KEY_ADVANCED = "valetudo/advanced_tools"   # Terminal, robot Wi-Fi recorder, boot watch, restrictions
KEY_HA_ON_NUC = "valetudo/ha_on_nuc"       # Home Assistant's address uses the NUC's host
KEY_KODI_ON_NUC = "valetudo/kodi_on_nuc"   # Kodi's address uses the NUC's host
KEY_VNC_COMMAND = "valetudo/vnc_command"   # remote desktop programs: empty = found
KEY_RDP_COMMAND = "valetudo/rdp_command"
KEY_TAB_ORDER = "valetudo/panel_tab_order"   # the panel's side tabs, comma-separated keys
PANEL_TABS = ("clean", "schedule", "history", "camera", "wifi", "status", "maintenance",
              "terminal")   # their default order
KEY_STRIP_DOTS = "valetudo/strip_dots"   # servers in the strip: a dot instead of a label
KEY_TOOLBAR = "valetudo/toolbar"   # the commands in the plugin's toolbar, comma-separated
# The commands the toolbar can show, in its order; the map tools (last four) only
# while "Show on map" is on.
TOOLBAR_CHOICES = ("status_panel", "live", "start", "home", "zone", "goto", "settings",
                   "pick_rooms", "place_sensor", "edit_restrictions", "send_restrictions")
DEFAULT_TOOLBAR = ("status_panel", "pick_rooms", "place_sensor", "edit_restrictions",
                   "send_restrictions")
KEY_HISTORY = "valetudo/history"   # record the robot's outings in <project folder>/history
KEY_KODI_URL = "valetudo/kodi_url"   # empty = no Kodi block in the Status tab
KEY_KODI_USER = "valetudo/kodi_user"
DEFAULT_HA_URL = "http://localhost:8123/"
KEY_HA_SSH_HOST = "valetudo/ha_ssh_host"   # empty = no Home Assistant terminal
KEY_HA_SSH_USER = "valetudo/ha_ssh_user"
KEY_HA_SSH_PORT = "valetudo/ha_ssh_port"
KEY_HA_LOG_COMMAND = "valetudo/ha_log_command"
# Home Assistant OS keeps its log in the system journal, not in a file.
DEFAULT_HA_LOG_COMMAND = "ha core logs -n 200 -f"
# The Home Assistant token is not a QgsSettings value: it is stored encrypted
# in the QGIS authentication database under this key (see ha_token()).
HA_TOKEN_SETTING = "valetudo/ha_token"
HA_SSH_PASSWORD_SETTING = "valetudo/ha_ssh_password"   # same: encrypted, optional
KODI_PASSWORD_SETTING = "valetudo/kodi_password"         # same
# Home Assistant sensors shown on the map: a JSON list of {entity_id, x, y},
# x and y in the robot's frame (cm, Valetudo convention). Values come live from HA.
KEY_HA_SENSORS = "valetudo/ha_sensors"

# Wi-Fi survey: setting key -> (default value, type). Read by load_settings().
WIFI_DEFAULTS = {
    "wifi_interval_s": (2.0, float),      # time between two readings
    "wifi_min_step_cm": (20, int),        # ignore a reading closer than this to the last one
    "wifi_max_pos_age_s": (3.0, float),   # ignore a reading if the position is older
    "wifi_pixel_cm": (10, int),           # raster cell size
    "wifi_idw_power": (2.0, float),       # IDW distance coefficient
    "wifi_bad_dbm": (-80, int),           # red
    "wifi_fair_dbm": (-67, int),          # yellow
    "wifi_good_dbm": (-50, int),          # green
    "wifi_opacity": (70, int),            # raster opacity, in %
    "wifi_clip_rooms": (True, bool),      # clip the raster to the rooms
}

DEFAULT_CAMERA_PORT = 8555


def default_camera_url(robot_url):
    """tcp://<robot host>:8555, derived from the robot address."""
    host = QUrl(robot_url).host() if robot_url else ""
    return f"tcp://{host}:{DEFAULT_CAMERA_PORT}" if host else ""


def server_list():
    """The servers (see servers.py). The first time, built from the settings of
    earlier versions and stored."""
    s = QgsSettings()
    if s.contains(servers_model.KEY_SERVERS):
        return servers_model.parse(s.value(servers_model.KEY_SERVERS, "", type=str))
    migrated = servers_model.migrate({**_legacy_stored(), "has_ha_token": has_ha_token_legacy()})
    save_servers(migrated)
    return migrated


def save_servers(servers):
    QgsSettings().setValue(servers_model.KEY_SERVERS, servers_model.dumps(servers))


def active_robot_id():
    return QgsSettings().value(servers_model.KEY_ACTIVE_ROBOT, "", type=str)


def toolbar_keys():
    """The commands chosen for the plugin's toolbar (the defaults until chosen)."""
    s = QgsSettings()
    if not s.contains(KEY_TOOLBAR):
        return list(DEFAULT_TOOLBAR)
    stored = str(s.value(KEY_TOOLBAR, "", type=str))
    return [key for key in stored.split(",") if key in TOOLBAR_CHOICES]


def tab_order():
    """The panel's side tabs in the order chosen in the settings (tabs not in the stored
    order, e.g. added by a later version, keep their default place at the end)."""
    stored = QgsSettings().value(KEY_TAB_ORDER, "", type=str)
    order = [key for key in str(stored).split(",") if key in PANEL_TABS]
    return order + [key for key in PANEL_TABS if key not in order]


def load_settings():
    """The settings: the plugin's options, and the servers' values under the names
    the plugin has always read (robot address, Pi host…; see servers.legacy_config),
    from the active robot and the first server of each type."""
    cfg = _stored_settings()
    servers = server_list()
    cfg.update(servers_model.legacy_config(servers, active_robot_id()))
    cfg["servers"] = servers
    # The panel's tab order and the toolbar: here too, so that a change of them alone
    # counts as a change of the settings (the plugin applies them when OK is pressed)
    cfg["tab_order"] = tab_order()
    cfg["toolbar"] = toolbar_keys()
    url = cfg["url"]
    cfg["camera_url"] = cfg["camera_url"] or default_camera_url(url)
    return cfg


def _stored_settings():
    """The plugin's own options (the servers are in server_list())."""
    s = QgsSettings()
    return {
        "interval_s": s.value(KEY_INTERVAL, 2, type=int),
        "camera_url": s.value(KEY_CAMERA_URL, "", type=str),
        "ffmpeg": s.value(KEY_FFMPEG, "", type=str),
        "camera_width": s.value(KEY_CAMERA_WIDTH, 640, type=int),
        "notify_dock": s.value(KEY_NOTIFY_DOCK, True, type=bool),
        "live_at_start": s.value(KEY_LIVE_AT_START, True, type=bool),
        "history": s.value(KEY_HISTORY, True, type=bool),
        "advanced_tools": s.value(KEY_ADVANCED, False, type=bool),
        "strip_dots": s.value(KEY_STRIP_DOTS, False, type=bool),
        "vnc_command": s.value(KEY_VNC_COMMAND, "", type=str).strip(),
        "rdp_command": s.value(KEY_RDP_COMMAND, "", type=str).strip(),
        **{key: s.value(f"valetudo/{key}", default, type=kind)
           for key, (default, kind) in WIFI_DEFAULTS.items()},
    }


def _legacy_stored():
    """The server settings of earlier versions, for servers.migrate()."""
    s = QgsSettings()
    return {
        "url": s.value(KEY_URL, "", type=str).strip(),
        "authcfg": s.value(KEY_AUTH, "", type=str),
        "ssh_user": s.value(KEY_SSH_USER, "root", type=str) or "root",
        "ssh_port": s.value(KEY_SSH_PORT, 22, type=int),
        "pi_host": s.value(KEY_PI_HOST, "", type=str).strip(),
        "pi_user": s.value(KEY_PI_USER, "pi", type=str).strip() or "pi",
        "pi_port": s.value(KEY_PI_PORT, 22, type=int),
        "pi_wifi_dir": s.value(KEY_PI_WIFI_DIR, "valetudo_wifi", type=str).strip(),
        "pi_web_url": s.value(KEY_PI_WEB_URL, "", type=str).strip(),
        "ha_url": s.value(KEY_HA_URL, "", type=str).strip(),
        "ha_on_nuc": s.value(KEY_HA_ON_NUC, False, type=bool),
        "ha_ssh_host": s.value(KEY_HA_SSH_HOST, "", type=str).strip(),
        "ha_ssh_user": s.value(KEY_HA_SSH_USER, "root", type=str).strip(),
        "ha_ssh_port": s.value(KEY_HA_SSH_PORT, 22, type=int),
        "ha_log_command": s.value(KEY_HA_LOG_COMMAND, "", type=str).strip(),
        "nuc_host": s.value(KEY_NUC_HOST, "", type=str).strip(),
        "nuc_user": s.value(KEY_NUC_USER, "root", type=str).strip(),
        "nuc_port": s.value(KEY_NUC_PORT, 22, type=int),
        "nuc_log_command": s.value(KEY_NUC_LOG_COMMAND, "", type=str).strip(),
        "nuc_web_url": s.value(KEY_NUC_WEB_URL, "", type=str).strip(),
        "kodi_url": s.value(KEY_KODI_URL, "", type=str).strip(),
        "kodi_on_nuc": s.value(KEY_KODI_ON_NUC, False, type=bool),
        "kodi_user": s.value(KEY_KODI_USER, "kodi", type=str).strip(),
    }


# -- secrets: stored encrypted in the QGIS authentication database ----------------

def has_secret(key):
    """True if a secret is stored under key (nothing is decrypted)."""
    try:
        from qgis.core import QgsApplication
        return bool(QgsApplication.authManager().existsAuthSetting(key))
    except Exception:
        return False


def secret(key):
    """The secret stored under key ("" if none, or if it cannot be decrypted)."""
    try:
        from qgis.core import QgsApplication
        manager = QgsApplication.authManager()
        # Without a stored secret, do not decrypt anything: that would ask for
        # the master password for nothing.
        if not manager.existsAuthSetting(key):
            return ""
        value = manager.authSetting(key, "", True)
    except Exception:   # authentication database unavailable
        return ""
    return str(value or "")


def set_secret(key, value):
    """Store value encrypted (QGIS asks for the master password if needed).

    Returns False if it could not be stored. An empty value removes it.
    """
    from qgis.core import QgsApplication
    manager = QgsApplication.authManager()
    try:
        if not value:
            if manager.existsAuthSetting(key):
                return bool(manager.removeAuthSetting(key))
            return True
        if not manager.setMasterPassword(True):   # asks once, if not yet set or verified
            return False
        return bool(manager.storeAuthSetting(key, value, True))
    except Exception:
        return False


def has_ha_token_legacy():
    return has_secret(HA_TOKEN_SETTING)


def has_ha_token():
    """A token is stored for the (first) Home Assistant server."""
    return has_secret(load_settings()["ha_token_key"])


def ha_token():
    """The Home Assistant access token ("" if none)."""
    return secret(load_settings()["ha_token_key"]).strip()


# -- Home Assistant sensors on the map ------------------------------------------

def ha_sensors():
    """The sensors placed on the map: a list of {"entity_id", "x", "y"}.

    Positions are integers in the robot's frame (cm). A malformed or missing
    setting yields an empty list rather than an error.
    """
    import json
    raw = QgsSettings().value(KEY_HA_SENSORS, "", type=str)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    sensors = []
    for item in data if isinstance(data, list) else []:
        try:
            entity_id = str(item["entity_id"]).strip()
            x, y = int(round(item["x"])), int(round(item["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if entity_id:
            sensors.append({"entity_id": entity_id, "x": x, "y": y})
    return sensors


def set_ha_sensors(sensors):
    """Store the list of sensors (replacing the previous one)."""
    import json
    cleaned = [{"entity_id": str(s["entity_id"]).strip(),
                "x": int(round(s["x"])), "y": int(round(s["y"]))}
               for s in sensors if str(s.get("entity_id", "")).strip()]
    QgsSettings().setValue(KEY_HA_SENSORS, json.dumps(cleaned))
