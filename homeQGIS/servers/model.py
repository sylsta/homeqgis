"""The servers the plugin works with: a list built in Settings › Options ›
HomeQGIS, tab Servers. Each has a type, which says what the plugin can do
with it:

    valetudo   a robot running Valetudo (one is active at a time)
    rpi        a Raspberry Pi (a Linux computer, plus the Wi-Fi maps folder)
    ha         Home Assistant
    kodi       Kodi (JSON-RPC)
    linux      a Linux computer, read over SSH
    windows    a Windows computer (remote desktop, optional OpenSSH)
    web        a web service: its address answers or not, and opens in the browser

Computers (Pi, Linux, Windows) can have a remote desktop: VNC, RDP or both,
directly or through an SSH tunnel (see servers/remote_desktop.py).

A server is a dict: id, type, name, strip (shown in the panel's status strip)
and the fields of its type (TYPE_FIELDS). "runs_on" (Home Assistant, Kodi, web
services) is the id of the Linux computer or Pi it runs on: its address then
takes that computer's host, keeping its own port.

Tokens and passwords are not in the list: they are stored encrypted in the QGIS
authentication database, under secret_key(server, field).

The list is stored as JSON under KEY_SERVERS. When it is not there yet, it is
built from the settings of earlier versions (migrate()). legacy_config() gives
the rest of the plugin the values it reads (robot address, Pi host, …), taken
from the first server of each type.
"""

import json
import uuid
from urllib.parse import urlsplit, urlunsplit

KEY_SERVERS = "valetudo/servers"
KEY_ACTIVE_ROBOT = "valetudo/active_robot"   # id of the robot in use
TYPES = ("valetudo", "rpi", "ha", "kodi", "linux", "windows", "web")
HOST_TYPES = ("rpi", "linux", "windows")    # what a server can "run on"
RD_PROTOCOLS = ("none", "vnc", "rdp", "both")


def _remote_desktop(protocol, through_ssh):
    return [("rd_protocol", "choice", protocol), ("vnc_port", "port", 5900),
            ("rdp_port", "port", 3389), ("rd_user", "text", ""),
            ("rd_ssh", "bool", through_ssh)]


DEFAULT_HA_LOG_COMMAND = "ha core logs -n 200 -f"
SECRET_PREFIX = "valetudo/server"           # valetudo/server/<id>/<field>

# type -> [(field, kind, default)]; kind: url, text, port, secret, authcfg, server
# ("mac": the MAC address that wakes the machine with Wake-on-LAN)
TYPE_FIELDS = {
    "valetudo": [("url", "url", ""), ("authcfg", "authcfg", ""),
                 ("ssh_user", "text", "root"), ("ssh_port", "port", 22)],
    "rpi": [("host", "text", ""), ("mac", "text", ""), ("user", "text", "pi"),
            ("port", "port", 22), ("wifi_dir", "text", "valetudo_wifi"), ("web_url", "url", ""),
            *_remote_desktop("none", True)],
    "ha": [("url", "url", "http://localhost:8123/"), ("runs_on", "server", ""),
           ("mac", "text", ""),
           ("token", "secret", ""), ("ssh_host", "text", ""), ("ssh_user", "text", "root"),
           ("ssh_password", "secret", ""), ("ssh_port", "port", 22),
           ("log_command", "text", DEFAULT_HA_LOG_COMMAND)],
    "kodi": [("url", "url", "http://localhost:8080/"), ("runs_on", "server", ""),
             ("mac", "text", ""),
             ("user", "text", "kodi"), ("password", "secret", "")],
    "linux": [("host", "text", ""), ("mac", "text", ""), ("user", "text", "root"),
              ("port", "port", 22),
              ("log_command", "text", ""), ("web_url", "url", ""),
              *_remote_desktop("none", True)],
    "windows": [("host", "text", ""), ("mac", "text", ""), ("ssh", "bool", False),
                ("user", "text", ""), ("port", "port", 22), ("web_url", "url", ""),
                *_remote_desktop("rdp", False)],
    "web": [("url", "url", ""), ("runs_on", "server", "")],
}
DEFAULT_PORTS = {"ha": 8123, "kodi": 8080}
LEGACY_SECRETS = {("ha", "token"): "valetudo/ha_token",
                  ("ha", "ssh_password"): "valetudo/ha_ssh_password",
                  ("kodi", "password"): "valetudo/kodi_password"}


def new_id():
    return uuid.uuid4().hex[:8]


def new_server(kind, name="", **fields):
    """A server of a type, with its defaults (secrets excluded)."""
    server = {"id": new_id(), "type": kind, "name": name, "strip": True}
    for field, field_kind, default in TYPE_FIELDS[kind]:
        if field_kind != "secret":
            server[field] = default
    server.update(fields)
    return server


def value(server, field):
    """A field's value, its default when missing or empty."""
    for name, kind, default in TYPE_FIELDS.get(server.get("type"), []):
        if name == field:
            got = server.get(field)
            if kind == "port":
                try:
                    return int(got) if got else default
                except (TypeError, ValueError):
                    return default
            if kind == "bool":
                return default if got is None or got == "" else bool(got)
            if kind == "choice":
                return got if got in RD_PROTOCOLS else default
            return got.strip() if isinstance(got, str) and got.strip() else default
    return server.get(field)


def secret_fields(kind):
    return [f for f, k, _ in TYPE_FIELDS.get(kind, []) if k == "secret"]


def secret_key(server, field):
    """Where a server's token or password is stored (authentication database)."""
    keys = server.get("secret_keys") or {}
    return keys.get(field) or f"{SECRET_PREFIX}/{server['id']}/{field}"


def all_secret_keys(servers):
    return [secret_key(s, f) for s in servers for f in secret_fields(s.get("type"))]


# -- addresses ----------------------------------------------------------------------

def on_host(url, host, default_port):
    """url with its host replaced (its port, else default_port, kept):
    on_host("http://localhost:8123/", "192.168.50.2", 8123) -> http://192.168.50.2:8123/"""
    if not host:
        return url
    parts = urlsplit(url if "://" in (url or "") else "http://" + (url or ""))
    port = parts.port or default_port
    return urlunsplit((parts.scheme or "http", f"{host}:{port}", parts.path or "/",
                       parts.query, parts.fragment))


def url_host(url):
    if not url:
        return ""
    return urlsplit(url if "://" in url else "http://" + url).hostname or ""


def find(servers, server_id):
    return next((s for s in servers if s.get("id") == server_id), None) if server_id else None


def host_server(servers, server):
    """The computer a server runs on (or None)."""
    target = find(servers, server.get("runs_on"))
    return target if target is not None and target.get("type") in HOST_TYPES else None


def address(servers, server):
    """A server's address as used: its URL (on its computer's host when it runs on
    one), or the host of an SSH server."""
    if server["type"] in HOST_TYPES:
        return value(server, "host")
    url = value(server, "url")
    target = host_server(servers, server)
    if target is not None and value(target, "host"):
        return on_host(url, ssh_address(value(target, "host"), "", 22)[0],
                       DEFAULT_PORTS.get(server["type"], 80))
    return url


def wake_target(servers, server):
    """(MAC address, host) to wake a server with Wake-on-LAN: its own MAC, else that
    of the computer it runs on; None when there is none."""
    for machine in (server, host_server(servers, server)):
        if machine is not None and value(machine, "mac"):
            if machine["type"] in HOST_TYPES:
                host = ssh_address(value(machine, "host"), "", 22)[0]
            else:
                host = url_host(address(servers, machine))
            return value(machine, "mac"), host
    return None


def ssh_address(text, user, port):
    """An SSH address as typed, tidied: "ssh://root@ha.lan:2222" -> ("ha.lan", "root",
    2222). A user or port written in it wins over the separate fields."""
    text = (text or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    if "@" in text:
        typed_user, text = text.rsplit("@", 1)
        user = typed_user or user
    if text.startswith("["):   # [IPv6]:port
        host, _, rest = text[1:].partition("]")
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
        return host, user, port
    if text.count(":") == 1:
        host, typed_port = text.split(":")
        if typed_port.isdigit():
            return host, user, int(typed_port)
        return host, user, port
    return text, user, port


def ssh_target(servers, server):
    """(host, user, port) for SSH on a server, or None. Home Assistant: its SSH address,
    else its own host; Kodi and web services: the computer they run on."""
    kind = server["type"]
    if kind == "windows" and not value(server, "ssh"):
        return None   # no OpenSSH server
    if kind in HOST_TYPES:
        host = value(server, "host")
        return ssh_address(host, value(server, "user"), value(server, "port")) if host else None
    if kind == "valetudo":
        host = url_host(value(server, "url"))
        return (host, value(server, "ssh_user"), value(server, "ssh_port")) if host else None
    if kind == "ha":
        host = value(server, "ssh_host") or url_host(address(servers, server))
        return ssh_address(host, value(server, "ssh_user"),
                           value(server, "ssh_port")) if host else None
    target = host_server(servers, server)
    if target is not None:
        return ssh_target(servers, target)
    host = url_host(value(server, "url"))
    if not host or kind != "kodi":
        return None
    linux = first(servers, "linux")   # as earlier versions: the NUC's SSH login
    return (host, value(linux, "user"), value(linux, "port")) if linux else (host, "root", 22)


def remote_desktops(servers, server):
    """[(protocol, host, port, user, ssh or None)] of a server's remote desktops: its
    own (computers), else those of the computer it runs on (Kodi, web services).
    ssh: (host, user, port) of the tunnel when it goes through SSH."""
    if server["type"] not in HOST_TYPES:
        target = host_server(servers, server)
        return remote_desktops(servers, target) if target is not None else []
    host = ssh_address(value(server, "host"), "", 22)[0]
    protocol = value(server, "rd_protocol")
    if not host or protocol == "none":
        return []
    ssh = ssh_target(servers, server) if value(server, "rd_ssh") else None
    out = []
    for name in ("vnc", "rdp"):
        if protocol in (name, "both"):
            out.append((name, host, value(server, f"{name}_port"), value(server, "rd_user"),
                        ssh))
    return out


# -- the robot in use, the first of each type ---------------------------------------

def first(servers, kind):
    return next((s for s in servers if s.get("type") == kind), None)


def active_robot(servers, active_id=""):
    robots = [s for s in servers if s.get("type") == "valetudo"]
    return find(robots, active_id) or (robots[0] if robots else None)


def legacy_config(servers, active_id=""):
    """The values the rest of the plugin reads (names of earlier versions' settings),
    from the active robot and the first server of each type."""
    cfg = {"url": "", "authcfg": "", "ssh_user": "root", "ssh_port": 22,
           "pi_host": "", "pi_user": "pi", "pi_port": 22, "pi_wifi_dir": "valetudo_wifi",
           "pi_web_url": "", "ha_url": "", "ha_on_nuc": False, "ha_ssh_host": "",
           "ha_ssh_user": "root", "ha_ssh_port": 22, "ha_log_command": DEFAULT_HA_LOG_COMMAND,
           "nuc_host": "", "nuc_user": "root", "nuc_port": 22, "nuc_log_command": "",
           "nuc_web_url": "", "kodi_url": "", "kodi_on_nuc": False, "kodi_user": "kodi",
           "kodi_ssh": None,
           "ha_token_key": LEGACY_SECRETS[("ha", "token")],
           "ha_ssh_password_key": LEGACY_SECRETS[("ha", "ssh_password")],
           "kodi_password_key": LEGACY_SECRETS[("kodi", "password")]}
    robot = active_robot(servers, active_id)
    if robot:
        cfg.update(url=value(robot, "url"), authcfg=value(robot, "authcfg"),
                   ssh_user=value(robot, "ssh_user"), ssh_port=value(robot, "ssh_port"))
    pi = first(servers, "rpi")
    if pi:
        host, user, port = ssh_address(value(pi, "host"), value(pi, "user"), value(pi, "port"))
        cfg.update(pi_host=host, pi_user=user, pi_port=port, pi_wifi_dir=value(pi, "wifi_dir"),
                   pi_web_url=value(pi, "web_url"))
    nuc = first(servers, "linux")
    if nuc:
        host, user, port = ssh_address(value(nuc, "host"), value(nuc, "user"),
                                       value(nuc, "port"))
        cfg.update(nuc_host=host, nuc_user=user, nuc_port=port,
                   nuc_log_command=value(nuc, "log_command"), nuc_web_url=value(nuc, "web_url"))
    ha = first(servers, "ha")
    if ha:
        ssh = ssh_target(servers, ha)
        cfg.update(ha_url=address(servers, ha), ha_ssh_host=value(ha, "ssh_host"),
                   ha_ssh_user=ssh[1] if ssh else "root", ha_ssh_port=ssh[2] if ssh else 22,
                   ha_log_command=value(ha, "log_command"),
                   ha_token_key=secret_key(ha, "token"),
                   ha_ssh_password_key=secret_key(ha, "ssh_password"))
        if value(ha, "ssh_host"):
            cfg["ha_ssh_host"] = ssh[0]
    kodi = first(servers, "kodi")
    if kodi:
        cfg.update(kodi_url=address(servers, kodi), kodi_user=value(kodi, "user"),
                   kodi_ssh=ssh_target(servers, kodi),
                   kodi_password_key=secret_key(kodi, "password"))
    return cfg


# -- storage --------------------------------------------------------------------------

def parse(raw):
    """The stored JSON -> list of servers (malformed entries left out)."""
    if not isinstance(raw, str):
        return []
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        return []
    servers = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("type") in TYPES and item.get("id"):
            item.setdefault("name", "")
            item.setdefault("strip", True)
            servers.append(item)
    return servers


def dumps(servers):
    return json.dumps(servers, ensure_ascii=False)


def migrate(old):
    """Servers from the settings of earlier versions (old: dict of their values, see
    settings._legacy_stored()); their tokens and passwords stay where they are."""
    servers = []
    if old.get("url"):
        servers.append(new_server("valetudo", "", url=old["url"],
                                  authcfg=old.get("authcfg", ""),
                                  ssh_user=old.get("ssh_user") or "root",
                                  ssh_port=old.get("ssh_port") or 22))
    if old.get("pi_host"):
        servers.append(new_server("rpi", "Raspberry Pi", host=old["pi_host"],
                                  user=old.get("pi_user") or "pi",
                                  port=old.get("pi_port") or 22,
                                  wifi_dir=old.get("pi_wifi_dir") or "valetudo_wifi",
                                  web_url=old.get("pi_web_url", "")))
    nuc = None
    if old.get("nuc_host"):
        nuc = new_server("linux", "NUC", host=old["nuc_host"],
                         user=old.get("nuc_user") or "root", port=old.get("nuc_port") or 22,
                         log_command=old.get("nuc_log_command", ""),
                         web_url=old.get("nuc_web_url", ""))
        servers.append(nuc)
    ha_url = (old.get("ha_url") or "").strip()
    if (ha_url and ha_url.rstrip("/") != "http://localhost:8123") or old.get("ha_on_nuc") \
            or old.get("ha_ssh_host") or old.get("has_ha_token"):
        ha = new_server("ha", "Home Assistant", url=ha_url or "http://localhost:8123/",
                        runs_on=nuc["id"] if nuc and old.get("ha_on_nuc") else "",
                        ssh_host=old.get("ha_ssh_host", ""),
                        ssh_user=old.get("ha_ssh_user") or "root",
                        ssh_port=old.get("ha_ssh_port") or 22,
                        log_command=old.get("ha_log_command") or DEFAULT_HA_LOG_COMMAND)
        ha["secret_keys"] = {"token": LEGACY_SECRETS[("ha", "token")],
                             "ssh_password": LEGACY_SECRETS[("ha", "ssh_password")]}
        servers.append(ha)
    if old.get("kodi_url"):
        kodi = new_server("kodi", "Kodi", url=old["kodi_url"],
                          runs_on=nuc["id"] if nuc and old.get("kodi_on_nuc") else "",
                          user=old.get("kodi_user", "kodi"))
        kodi["secret_keys"] = {"password": LEGACY_SECRETS[("kodi", "password")]}
        servers.append(kodi)
    return servers
