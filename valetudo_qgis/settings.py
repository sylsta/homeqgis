"""Plugin settings, stored in QgsSettings (edited in Settings › Options › Valetudo).

Passwords are never stored in clear text: credentials go through the QGIS
authentication manager (QgsAuthConfigSelect), which encrypts them.
"""

from qgis.PyQt.QtCore import QUrl
from qgis.core import QgsSettings

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


def load_settings():
    s = QgsSettings()
    url = s.value(KEY_URL, "", type=str)
    return {
        "url": url,
        "authcfg": s.value(KEY_AUTH, "", type=str),
        "interval_s": s.value(KEY_INTERVAL, 2, type=int),
        "camera_url": s.value(KEY_CAMERA_URL, "", type=str) or default_camera_url(url),
        "ffmpeg": s.value(KEY_FFMPEG, "", type=str),
        "camera_width": s.value(KEY_CAMERA_WIDTH, 640, type=int),
        "notify_dock": s.value(KEY_NOTIFY_DOCK, True, type=bool),
        "live_at_start": s.value(KEY_LIVE_AT_START, True, type=bool),
        "ssh_user": s.value(KEY_SSH_USER, "root", type=str) or "root",
        "ssh_port": s.value(KEY_SSH_PORT, 22, type=int),
        "pi_host": s.value(KEY_PI_HOST, "", type=str).strip(),
        "pi_user": s.value(KEY_PI_USER, "pi", type=str).strip() or "pi",
        "pi_port": s.value(KEY_PI_PORT, 22, type=int),
        "pi_wifi_dir": s.value(KEY_PI_WIFI_DIR, "valetudo_wifi", type=str).strip()
                       or "valetudo_wifi",
        "ha_url": s.value(KEY_HA_URL, DEFAULT_HA_URL, type=str).strip() or DEFAULT_HA_URL,
        "ha_ssh_host": s.value(KEY_HA_SSH_HOST, "", type=str).strip(),
        "ha_ssh_user": s.value(KEY_HA_SSH_USER, "root", type=str).strip() or "root",
        "ha_ssh_port": s.value(KEY_HA_SSH_PORT, 22, type=int),
        "ha_log_command": s.value(KEY_HA_LOG_COMMAND, DEFAULT_HA_LOG_COMMAND,
                                  type=str).strip() or DEFAULT_HA_LOG_COMMAND,
        **{key: s.value(f"valetudo/{key}", default, type=kind)
           for key, (default, kind) in WIFI_DEFAULTS.items()},
    }


def has_ha_token():
    """True if a Home Assistant token is stored (nothing is decrypted)."""
    try:
        from qgis.core import QgsApplication
        return bool(QgsApplication.authManager().existsAuthSetting(HA_TOKEN_SETTING))
    except Exception:
        return False


def ha_token():
    """The Home Assistant access token ("" if none, or if it cannot be decrypted)."""
    try:
        from qgis.core import QgsApplication
        manager = QgsApplication.authManager()
        # Without a stored token, do not decrypt anything: that would ask for
        # the master password for nothing.
        if not manager.existsAuthSetting(HA_TOKEN_SETTING):
            return ""
        value = manager.authSetting(HA_TOKEN_SETTING, "", True)
    except Exception:   # authentication database unavailable
        return ""
    return str(value or "").strip()


def set_ha_token(token):
    """Store the token encrypted (QGIS asks for the master password if needed).

    Returns False if it could not be stored. An empty token removes it.
    """
    from qgis.core import QgsApplication
    manager = QgsApplication.authManager()
    token = (token or "").strip()
    try:
        if not token:
            if manager.existsAuthSetting(HA_TOKEN_SETTING):
                return bool(manager.removeAuthSetting(HA_TOKEN_SETTING))
            return True
        if not manager.setMasterPassword(True):   # asks once, if not yet set or verified
            return False
        return bool(manager.storeAuthSetting(HA_TOKEN_SETTING, token, True))
    except Exception:
        return False
