"""Minimal Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/).

Every request carries ``Authorization: Bearer <long-lived access token>``.
"""

import json

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QByteArray, QObject, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from .i18n import tr


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

    def _request(self, path, timeout_ms):
        req = QNetworkRequest(QUrl(api_url(self.base_url, path)))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
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
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                try:
                    data = json.loads(raw) if raw.strip() else None
                except ValueError:
                    data = raw
                if on_success:
                    on_success(data)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)


def error_message(status, fallback):
    if status == 401:
        return tr("the access token was refused")
    if status == 404:
        return tr("no Home Assistant API at this address")
    return fallback
