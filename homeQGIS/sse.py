"""Server-sent events: Valetudo pushes the robot's state and map as they change
(GET /api/v2/robot/state/attributes/sse and /robot/state/map/sse).

An EventStream keeps one such request open, splits what arrives into events
("event: <name>" / "data: <json>" blocks, separated by a blank line) and emits
them. Valetudo writes a comment line (": sse-keep-alive") every 5 s, so a
stream silent for longer than STALE_S is considered dead and opened again. A
closed or refused stream is opened again after RETRY_S (growing up to the last
value); meanwhile the client keeps polling as before (see client.py).
"""

import time

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

STALE_S = 15
RETRY_S = (2, 5, 10, 30, 60)
MAX_EVENT_BYTES = 32 * 1024 * 1024   # a map can be large; anything beyond is dropped


def split_events(buffer):
    """(events, rest): complete events [(name, data)] in buffer (bytes), and what
    is left of an incomplete one."""
    buffer = buffer.replace(b"\r\n", b"\n")
    *blocks, rest = buffer.split(b"\n\n")
    events = []
    for block in blocks:
        name, data = "message", []
        for line in block.split(b"\n"):
            if not line or line.startswith(b":"):
                continue   # keep-alive comment
            field, _, value = line.partition(b":")
            value = value[1:] if value.startswith(b" ") else value
            if field == b"event":
                name = value.decode("utf-8", "replace")
            elif field == b"data":
                data.append(value)
        if data:
            events.append((name, b"\n".join(data).decode("utf-8", "replace")))
    return events, rest


class EventStream(QObject):
    eventReceived = pyqtSignal(str, str)   # event name, data (text)

    def __init__(self, nam, make_request, parent=None):
        """make_request(): the QNetworkRequest to open (authentication included)."""
        super().__init__(parent)
        self.nam, self.make_request = nam, make_request
        self._reply = None
        self._buffer = b""
        self._last = 0.0          # time.monotonic() of the last bytes received
        self._failures = 0
        self._running = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._open)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(STALE_S * 1000)
        self._watchdog.timeout.connect(self._check)

    def alive(self):
        """True while the stream is open and has said something recently."""
        return (self._reply is not None and not self._reply.isFinished()
                and time.monotonic() - self._last < STALE_S)

    def start(self):
        self._running = True
        if self._reply is None and not self._retry.isActive():
            self._open()
        self._watchdog.start()

    def stop(self):
        self._running = False
        self._retry.stop()
        self._watchdog.stop()
        self._drop()

    # -- inside --------------------------------------------------------------------

    def _open(self):
        if not self._running:
            return
        request = self.make_request()
        request.setRawHeader(b"Accept", b"text/event-stream")
        request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                             QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        request.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
        self._buffer, self._last = b"", time.monotonic()
        reply = self._reply = self.nam.get(request)
        reply.readyRead.connect(self._read)
        reply.finished.connect(self._closed)

    def _read(self):
        reply = self._reply
        if reply is None:
            return
        chunk = bytes(reply.readAll())
        if not chunk:
            return
        self._last = time.monotonic()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and int(status) != 200:
            return   # an error page: _closed() will try again later
        self._failures = 0
        self._buffer += chunk
        if len(self._buffer) > MAX_EVENT_BYTES:
            self._buffer = b""
            return
        events, self._buffer = split_events(self._buffer)
        for name, data in events:
            self.eventReceived.emit(name, data)

    def _closed(self):
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.deleteLater()
        if not self._running:
            return
        delay = RETRY_S[min(self._failures, len(RETRY_S) - 1)]
        self._failures += 1
        self._retry.start(delay * 1000)

    def _check(self):
        """Silent for too long (network gone, robot rebooted): open it again."""
        if self._running and self._reply is not None and not self.alive():
            self._drop()
            self._closed()

    def _drop(self):
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            reply.readyRead.disconnect(self._read)
            reply.finished.disconnect(self._closed)
        except (TypeError, RuntimeError):
            pass
        if not reply.isFinished():
            reply.abort()
        reply.deleteLater()
