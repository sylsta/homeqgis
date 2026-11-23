"""Minimal Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/).

With a long-lived access token, every request carries
``Authorization: Bearer <token>``. Without one, Home Assistant answers its API
with 401 only: enough to know it is there, nothing more.
"""

import email.utils
import json
import time

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QByteArray, QObject, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from .i18n import tr


UNAUTHORISED = "401"   # error text of a request made without a token, answered 401


def api_url(base_url, path):
    """http://host:8123/ + /config -> http://host:8123/api/config"""
    return base_url.strip().rstrip("/") + "/api" + path


class HomeAssistantClient(QObject):
    def __init__(self, base_url, token, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.nam = QgsNetworkAccessManager.instance()
        self._replies = set()
        # Home Assistant's own clock, from the Date header of the last answer
        self.server_time = None
        self.received_at = None

    def _request(self, path, timeout_ms):
        req = QNetworkRequest(QUrl(api_url(self.base_url, path)))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if self.token:
            req.setRawHeader(b"Authorization", f"Bearer {self.token}".encode())
        if timeout_ms and hasattr(req, "setTransferTimeout"):
            req.setTransferTimeout(timeout_ms)
        return req

    def get(self, path, on_success, on_error=None, timeout_ms=10000):
        self._track(self.nam.get(self._request(path, timeout_ms)), on_success, on_error)

    def post(self, path, payload, on_success=None, on_error=None, timeout_ms=10000):
        body = QByteArray(json.dumps(payload).encode())
        self._track(self.nam.post(self._request(path, timeout_ms), body), on_success, on_error)

    def close(self):
        """Abort the requests under way (their callbacks are not called)."""
        for reply in list(self._replies):
            # Not one that has already ended (timed out, failed): aborting it would end
            # it a second time (Qt: "this method must only be called once")
            if not sip.isdeleted(reply) and not reply.isFinished():
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
                        on_error(error_message(status, reply.errorString(), self.token))
                    return
                stamp = bytes(reply.rawHeader(QByteArray(b"Date"))).decode("latin-1").strip()
                try:
                    self.server_time = email.utils.parsedate_to_datetime(stamp).timestamp()
                    self.received_at = time.time()
                except (TypeError, ValueError, IndexError):
                    pass
                raw = (bytes(reply.readAll()) if reply.isOpen() else b"").decode("utf-8", "replace")
                try:
                    data = json.loads(raw) if raw.strip() else None
                except ValueError:
                    data = raw
                if on_success:
                    on_success(data)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)


def error_message(status, fallback, token=""):
    if status == 401:
        return tr("the access token was refused") if token else UNAUTHORISED
    if status == 404:
        return tr("no Home Assistant API at this address")
    return fallback


def parse_timestamp(text):
    """ISO 8601 state of a timestamp sensor (e.g. sensor.uptime) -> epoch, or None."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
