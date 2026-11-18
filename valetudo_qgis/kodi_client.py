"""Minimal Kodi JSON-RPC client (https://kodi.wiki/view/JSON-RPC_API), over HTTP.

Kodi side: Settings › Services › Control › "Allow remote control via HTTP"
(port 8080 by default), with a username and password (HTTP Basic auth).

No user-facing text here except error messages passed to callbacks.
"""

import base64
import json

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QByteArray, QObject, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from .i18n import tr

# What the Status tab asks Kodi (labels are formatted by Kodi itself)
INFO_LABELS = ["System.Uptime", "System.CPUTemperature", "Network.IPAddress",
               "System.OSVersionInfo", "System.FriendlyName"]
ITEM_PROPERTIES = ["title", "showtitle", "season", "episode", "year", "artist", "album"]
PLAYER_PROPERTIES = ["time", "totaltime", "percentage", "speed"]


def rpc_url(base_url):
    """http://host:8080/ -> http://host:8080/jsonrpc"""
    url = base_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url if url.endswith("/jsonrpc") else url + "/jsonrpc"


class KodiClient(QObject):
    def __init__(self, base_url, user, password, parent=None):
        super().__init__(parent)
        self.url = rpc_url(base_url)
        self.user, self.password = user, password
        self.nam = QgsNetworkAccessManager.instance()
        self._replies = set()
        self._next_id = 1

    def call(self, method, params=None, on_success=None, on_error=None, timeout_ms=5000):
        req = QNetworkRequest(QUrl(self.url))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if self.user or self.password:
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            req.setRawHeader(b"Authorization", f"Basic {token}".encode())
        if hasattr(req, "setTransferTimeout"):
            req.setTransferTimeout(timeout_ms)
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            body["params"] = params
        self._next_id += 1
        reply = self.nam.post(req, QByteArray(json.dumps(body).encode()))
        self._track(reply, on_success, on_error)

    def close(self):
        """Abort the requests under way (their callbacks are not called)."""
        for reply in list(self._replies):
            if not sip.isdeleted(reply):
                reply.abort()
        self._replies.clear()

    def _track(self, reply, on_success, on_error):
        self._replies.add(reply)

        def finished():
            if sip.isdeleted(self) or reply not in self._replies:
                if not sip.isdeleted(reply):
                    reply.deleteLater()
                return
            self._replies.discard(reply)
            try:
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    if on_error:
                        on_error(error_message(status, reply.errorString()))
                    return
                raw = bytes(reply.readAll()) if reply.isOpen() else b""
                try:
                    data = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    if on_error:
                        on_error(tr("no Kodi JSON-RPC at this address"))
                    return
                if isinstance(data, dict) and "error" in data:
                    if on_error:
                        error = data["error"]
                        on_error(error.get("message", str(error))
                                 if isinstance(error, dict) else str(error))
                    return
                if on_success:
                    on_success(data.get("result") if isinstance(data, dict) else None)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)


def error_message(status, fallback):
    if status == 401:
        return tr("the username or password was refused")
    if status == 404:
        return tr("no Kodi JSON-RPC at this address")
    return fallback


def seconds(kodi_time):
    """Kodi time dict {hours, minutes, seconds, milliseconds} -> seconds (float)."""
    if not isinstance(kodi_time, dict):
        return None
    return (kodi_time.get("hours", 0) * 3600 + kodi_time.get("minutes", 0) * 60
            + kodi_time.get("seconds", 0) + kodi_time.get("milliseconds", 0) / 1000)


def clock(total_seconds):
    """3725 -> "01:02:05"; under an hour -> "02:05"."""
    total = int(max(0, total_seconds or 0))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def item_title(item):
    """A player item -> "Show S02E05 · Title", "Title (1998)", "Artist · Title", label."""
    if not isinstance(item, dict):
        return ""
    title = item.get("title") or item.get("label") or ""
    if item.get("showtitle"):
        season, episode = item.get("season", -1), item.get("episode", -1)
        number = f" S{season:02d}E{episode:02d}" if season >= 0 and episode >= 0 else ""
        return f"{item['showtitle']}{number} · {title}"
    artist = item.get("artist")
    if artist:
        names = ", ".join(artist) if isinstance(artist, list) else str(artist)
        return f"{names} · {title}" if names else title
    year = item.get("year")
    return f"{title} ({year})" if year and item.get("type") == "movie" else title
