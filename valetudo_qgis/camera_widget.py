"""Camera widget: live video from the robot's H.264 stream.

Embedded in the status panel. The panel decides when it plays (panel
visible and camera section open); nothing is decoded or downloaded otherwise.
"""

import time

import os

from qgis.PyQt.QtCore import QDateTime, QStandardPaths, Qt, QTimer
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qgis.core import QgsSettings

from .camera import CameraStream
from .camera_recorder import CameraRecorder
from .i18n import tr
from .project_layers import project_folder
from .settings import load_settings

DEFAULT_ASPECT = 9 / 16   # height / width until the first image tells the real one
KEY_RECORD_DIR = "valetudo/camera_record_dir"   # folder of the last recording
JOB_VIDEOS = "videos"   # the recordings of jobs, next to the project


def job_videos_folder():
    """Where jobs are recorded: <project folder>/videos; while the project has never
    been saved, the folder of the last recording, else the user's videos folder."""
    folder = (project_folder(JOB_VIDEOS)
              or QgsSettings().value(KEY_RECORD_DIR, "", type=str)
              or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
              or os.path.expanduser("~"))
    os.makedirs(folder, exist_ok=True)
    return folder


class CameraWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = None
        self._aspect = DEFAULT_ASPECT
        self._frames = 0
        self._fps_clock = time.monotonic()
        self._error_detail = ""
        self._startup = ""   # seconds to the first image, as text

        self.stream = CameraStream(self)
        self.stream.frameReady.connect(self._on_frame)
        self.stream.stateChanged.connect(self._on_state)
        self.recorder = CameraRecorder(self)
        self.stream.jpegReady.connect(self.recorder.add_jpeg)
        self.recorder.stateChanged.connect(self._on_record_state)
        self._record_clock = QTimer(self)
        self._record_clock.setInterval(1000)
        self._record_clock.timeout.connect(self._show_recording)
        self._record_started = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.video = QLabel()
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.video.setStyleSheet("background-color: black; color: #bdbdbd;")
        layout.addWidget(self.video)

        bar = QHBoxLayout()
        self.btn_play = QPushButton()
        self.btn_play.clicked.connect(self.toggle)
        bar.addWidget(self.btn_play)
        self.btn_snapshot = QPushButton(tr("Save snapshot"))
        self.btn_snapshot.clicked.connect(self.save_snapshot)
        self.btn_snapshot.setEnabled(False)
        bar.addWidget(self.btn_snapshot)
        self.btn_record = QPushButton(tr("Record"))
        self.btn_record.setToolTip(tr("Record the video to an MP4 file, at the size shown"))
        self.btn_record.clicked.connect(self.toggle_recording)
        self.btn_record.setEnabled(False)
        bar.addWidget(self.btn_record)
        layout.addLayout(bar)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._update_fps)
        self._on_state("stopped", "")
        self._fit_height()

    # -- playback -----------------------------------------------------------------

    def play(self):
        cfg = load_settings()
        if not cfg["camera_url"]:
            self.lbl_status.setText(tr("No camera URL: set it in the settings."))
            return
        self._error_detail = ""
        self.stream.start(cfg["camera_url"], cfg["ffmpeg"], cfg["camera_width"])

    def stop(self, by_user=False):
        if by_user and self.recorder.is_recording():
            self.stopped_by_user = True
        self.recorder.stop()   # a recording ends with the video
        if self.stream.is_running():
            self.stream.stop()

    def toggle(self, *_):
        if self.stream.is_running():
            self.stop(by_user=True)
        else:
            self.play()

    def restart_if_running(self):
        """Called when settings change."""
        if self.stream.is_running():
            self.play()

    def shutdown(self):
        self.recorder.shutdown()
        self.stream.stop()

    # -- display ------------------------------------------------------------------

    def _fit_height(self):
        """Video height follows the panel width, with the stream's aspect ratio."""
        self.video.setFixedHeight(max(120, int(self.width() * self._aspect)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()
        self._show_image()

    def _on_frame(self, image):
        if self._image is None and image.width():
            self._aspect = image.height() / image.width()
            self._fit_height()
        self._image = image
        self._frames += 1
        self.btn_snapshot.setEnabled(True)
        self._show_image()

    def _show_image(self):
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image).scaled(
            self.video.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video.setPixmap(pixmap)

    def _update_fps(self):
        now = time.monotonic()
        fps = round(self._frames / max(now - self._fps_clock, 1e-3))
        self._frames, self._fps_clock = 0, now
        self._fps = fps
        if self.recorder.is_recording():
            return   # the status line shows the recording (see _show_recording)
        if self.stream.is_running() and self._image is not None and not self._error_detail:
            text = tr("Playing · {fps} fps").format(fps=fps)
            if self._startup:
                text += " · " + tr("first image after {seconds} s").format(seconds=self._startup)
            self.lbl_status.setText(text)

    def _on_state(self, state, detail):
        running = state not in ("stopped", "ffmpeg_missing")
        self.btn_play.setText(tr("Stop") if running else tr("Play"))
        if state == "playing":
            self.btn_record.setEnabled(True)
        elif not running and not self.recorder.is_recording():
            self.btn_record.setEnabled(False)
        if state == "connecting":
            self.lbl_status.setText(tr("Connecting…"))
        elif state == "playing":
            self._error_detail = ""
            self._startup = detail
            self._fps_clock, self._frames = time.monotonic(), 0
            self._fps_timer.start()
            self.lbl_status.setText(tr("Playing"))
        elif state == "stopped":
            self._fps_timer.stop()
            self.lbl_status.setText(tr("Stopped"))
            self.video.setText(tr("No video"))
            self._image = None
        elif state == "ffmpeg_missing":
            self._fps_timer.stop()
            self.lbl_status.setText(
                tr("ffmpeg not found: install it or set its path in the settings."))
        elif state == "error":
            self._error_detail = detail
        elif state == "reconnecting":
            self._fps_timer.stop()
            text = tr("Stream lost, reconnecting in {seconds} s…").format(seconds=detail)
            if self._error_detail:
                text += "\n" + tr("ffmpeg error: {detail}").format(detail=self._error_detail)
            self.lbl_status.setText(text)

    # -- recording ----------------------------------------------------------------

    def is_recording(self):
        return self.recorder.is_recording()

    # True once the user stopped a recording (Stop recording, or the camera's Stop),
    # until the next automatic one: it is then not started again behind their back.
    stopped_by_user = False

    def stop_recording(self):
        """Stop (the video is finished and saved) when the job is over."""
        if self.recorder.is_recording():
            self.recorder.stop()

    def record_to(self, folder):
        """Record without asking (a job that starts): valetudo_job_<date>.mp4."""
        if self.recorder.is_recording():
            return
        name = "valetudo_job_{}.mp4".format(
            QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss"))
        self.stopped_by_user = False
        self.recorder.start(os.path.join(folder, name), load_settings()["ffmpeg"])

    def toggle_recording(self, *_):
        if self.recorder.is_recording():
            self.stopped_by_user = True   # (the robot's recording is not started again)
            self.recorder.stop()
            return
        settings = QgsSettings()
        folder = settings.value(KEY_RECORD_DIR, "", type=str)
        name = "valetudo_{}.mp4".format(QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss"))
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Record the video"), os.path.join(folder, name) if folder else name,
            tr("MP4 videos (*.mp4)"))
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        settings.setValue(KEY_RECORD_DIR, os.path.dirname(path))
        self.recorder.start(path, load_settings()["ffmpeg"])

    def _on_record_state(self, state, detail):
        if state == "recording":
            self._record_started = time.monotonic()
            self._record_clock.start()
            self.btn_record.setText(tr("Stop recording"))
            self.btn_record.setStyleSheet("color: #c62828; font-weight: bold;")
            self._show_recording()
            return
        self._record_clock.stop()
        self.btn_record.setStyleSheet("")
        self.btn_record.setText(tr("Record"))
        if state == "finishing":
            self.btn_record.setEnabled(False)
            self.lbl_status.setText(tr("Finishing the video…"))
            return
        self.btn_record.setEnabled(self.stream.is_running())
        if state == "saved":
            self.lbl_status.setText(tr("Video saved: {path}").format(path=detail))
        elif state == "failed":
            self.lbl_status.setText(tr("Recording failed: {error}").format(error=detail))
        elif state == "ffmpeg_missing":
            self.lbl_status.setText(
                tr("ffmpeg not found: install it or set its path in the settings."))

    def _show_recording(self):
        seconds = int(time.monotonic() - (self._record_started or time.monotonic()))
        self.lbl_status.setText("<span style='color:#c62828'>●</span> " + tr(
            "Recording {duration} · {file}").format(
                duration=f"{seconds // 60:02d}:{seconds % 60:02d}",
                file=os.path.basename(self.recorder.path()))
            + (f" · {self._fps} fps" if getattr(self, "_fps", None) else ""))

    def save_snapshot(self, *_):
        if self._image is None:
            return
        name = "valetudo_{}.png".format(QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss"))
        path, _ = QFileDialog.getSaveFileName(self, tr("Save snapshot"), name,
                                              tr("PNG images (*.png)"))
        if path:
            self._image.save(path, "PNG")
            self.lbl_status.setText(tr("Snapshot saved: {path}").format(path=path))
