"""Camera recording: the JPEG images already decoded for the live view are fed
to a second ffmpeg process, which encodes them to an H.264 MP4 file.

No second connection to the robot (its stream may accept only one client) and
no interruption of the live view. Each image is stamped with the time it
arrived, so the video plays at the speed it was filmed, even if the frame
rate varied. The picture is the size of the live view (Video width, in the
settings).

Stopping closes ffmpeg's input: it then finishes the file properly. The MP4
is fragmented, so even a recording cut short (QGIS killed) stays readable.

No user-facing text here: states are keys (see STATES).
"""

from qgis.PyQt.QtCore import QObject, QProcess, QTimer, pyqtSignal

from .camera import find_ffmpeg

STATES = ("recording", "finishing", "saved", "failed", "ffmpeg_missing")
STOP_TIMEOUT_MS = 15_000   # then ffmpeg is killed (the file may be unreadable)
MAX_PENDING = 16 * 1024 * 1024   # ffmpeg too slow: drop images rather than fill memory


def recorder_arguments(path):
    """Measured with ffmpeg 6.1 on a 15 fps JPEG stream with a 1 s gap: every image
    kept, real duration (without a tiny probe, the first images share one time
    stamp and are dropped; without passthrough, images are dropped or doubled)."""
    return [
        "-hide_banner", "-loglevel", "error", "-y",
        "-use_wallclock_as_timestamps", "1",       # real arrival times: right speed
        "-probesize", "32", "-analyzeduration", "0",
        "-f", "image2pipe", "-c:v", "mjpeg", "-i", "-",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",                     # plays everywhere
        "-fps_mode", "passthrough",                # one image in, one image out (ffmpeg 5.1+)
        "-force_key_frames", "expr:gte(t,n_forced*2)",   # a fragment every 2 s
        # Fragmented MP4: readable up to its last fragment even if QGIS is killed
        "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
        "-flush_packets", "1",
        path,
    ]


class CameraRecorder(QObject):
    stateChanged = pyqtSignal(str, str)   # state key, detail (path or error)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._path = ""
        self._stderr = b""
        self.frames = 0
        self._kill = QTimer(self)
        self._kill.setSingleShot(True)
        self._kill.setInterval(STOP_TIMEOUT_MS)
        self._kill.timeout.connect(self._force_stop)

    def is_recording(self):
        """True from start() until the file is finished."""
        return self._process is not None

    def path(self):
        return self._path

    def start(self, path, ffmpeg=""):
        if self._process is not None:
            return
        program = find_ffmpeg(ffmpeg)
        if not program:
            self.stateChanged.emit("ffmpeg_missing", ffmpeg or "ffmpeg")
            return
        self._path, self._stderr, self.frames = path, b"", 0
        process = QProcess(self)
        process.readyReadStandardError.connect(self._on_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        process.start(program, recorder_arguments(path))
        self.stateChanged.emit("recording", path)

    def add_jpeg(self, data):
        """One complete JPEG image (bytes), as decoded for the live view."""
        process = self._process
        if process is None or process.state() != QProcess.ProcessState.Running:
            return
        if process.bytesToWrite() > MAX_PENDING:
            return
        process.write(data)
        self.frames += 1

    def stop(self):
        """Finish the file: ffmpeg encodes what it has, then writes the index."""
        process = self._process
        if process is None:
            return
        self.stateChanged.emit("finishing", self._path)
        process.closeWriteChannel()
        self._kill.start()

    def shutdown(self):
        """QGIS is closing: finish the file now (blocking, a few seconds at most)."""
        process = self._process
        if process is None:
            return
        process.closeWriteChannel()
        if not process.waitForFinished(5000):
            process.kill()
            process.waitForFinished(1000)

    def _force_stop(self):
        if self._process is not None:
            self._process.kill()

    def _on_stderr(self):
        if self._process is not None:
            self._stderr = (self._stderr + bytes(self._process.readAllStandardError()))[-2000:]

    def _last_error(self):
        lines = [l.strip() for l in self._stderr.decode("utf-8", "replace").splitlines()]
        return next((l for l in reversed(lines) if l), "")

    def _on_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._finish()
            self.stateChanged.emit("ffmpeg_missing", "ffmpeg")

    def _on_finished(self, exit_code, _status=None):
        frames = self.frames
        if self._finish() is None:
            return
        if exit_code == 0 and frames:
            self.stateChanged.emit("saved", self._path)
        else:
            self.stateChanged.emit("failed", self._last_error() or f"exit code {exit_code}")

    def _finish(self):
        self._kill.stop()
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        return process
