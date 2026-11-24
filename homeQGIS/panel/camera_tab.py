"""Camera tab of the panel: live video, recordings, and the automatic
recording of the robot whenever it runs."""

import time

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QKeySequence
from qgis.core import QgsApplication, QgsSettings

try:
    from qgis.PyQt.QtGui import QShortcut   # Qt 6
except ImportError:
    from qgis.PyQt.QtWidgets import QShortcut   # Qt 5

from ..camera.recordings import RecordingsBox
from ..camera.widget import CameraWidget, job_videos_folder
from ..core.i18n import tr
from ..core.settings import load_settings
from .widgets import VideoWindow

KEY_RECORDINGS_COLLAPSED = "valetudo/recordings_collapsed"

# A job starts when the robot goes from one of AT_REST_STATES to one of JOB_STATES
JOB_STATES = ("cleaning", "moving")
RUNNING_STATES = ("cleaning", "moving", "returning", "manual_control")   # recorded
RETRY_RECORDING_S = 60      # an automatic recording that ended by itself: tried again
STOP_IDLE_MS = 10 * 60_000   # paused or idle away from the dock this long: recording ends
AT_REST_STATES = ("docked", "idle", "error")
CAMERA_GRACE_MS = 60_000   # the stream keeps running this long after the tab is left


class CameraMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _build_camera(self):
        """Camera: plays only while this tab is shown and the panel is visible."""
        theme = QgsApplication.getThemeIcon
        self.lbl_position.setText(tr("Waiting for the robot position…"))
        self.camera_page = self.tab_camera
        self.camera = CameraWidget()
        self._away_while_recording = False   # see _follow_recording
        self._auto_recording = False         # the recording under way was started by us
        self._recording_declined = False     # stopped by hand: not again before the dock
        self._last_auto_record = -RETRY_RECORDING_S   # time.monotonic() of the last try
        self._auto_starting = False
        self.camera.recorder.stateChanged.connect(self._on_record_state)
        self._idle_stop = QTimer(self)
        self._idle_stop.setSingleShot(True)
        self._idle_stop.setInterval(STOP_IDLE_MS)
        self._idle_stop.timeout.connect(self._stop_idle_recording)
        self.camera_layout.insertWidget(0, self.camera)
        # The recordings (videos, snapshots, camera views, obstacle photos), above the spacer
        self.recordings = RecordingsBox()
        self.recordings.setCollapsed(QgsSettings().value(KEY_RECORDINGS_COLLAPSED, True, type=bool))
        self.recordings.collapsedStateChanged.connect(self._on_recordings_collapsed)
        self.camera_layout.insertWidget(self.camera_layout.count() - 1, self.recordings)
        self.camera.snapshotSaved.connect(lambda *_: self.recordings.refresh())
        # Coming back to the tab soon after leaving it shows the video at once,
        # instead of reconnecting and waiting for the robot's next full image.
        self._camera_grace = QTimer(self)
        self._camera_grace.setSingleShot(True)
        self._camera_grace.setInterval(CAMERA_GRACE_MS)
        self._camera_grace.timeout.connect(self._camera_grace_over)
        self.camera_light.setVisible(False)    # shown if the robot supports it
        self.camera_light.clicked.connect(self._on_camera_light_clicked)  # user only
        self.video_window = None
        self.btn_camera_full.setIcon(theme("/mActionZoomFullExtent.svg"))
        self.btn_camera_full.clicked.connect(self._show_video_window)
        snapshot = QShortcut(QKeySequence("Ctrl+Shift+S"), self.tab_camera)
        snapshot.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        snapshot.activated.connect(self.camera.save_snapshot)

    def _show_video_window(self, *_):
        if self.video_window is None:
            self.video_window = VideoWindow(self)
            self.camera.stream.frameReady.connect(self.video_window.show_image)
        if not self.camera.stream.is_running():
            self.camera.play()
        self.video_window.showFullScreen()

    def _update_camera(self):
        """Play while the panel is visible and the Camera tab is shown; keep playing
        CAMERA_GRACE_MS after that, so that a quick return is instant."""
        if self.isVisible() and self._page_shown(self.camera_page):
            self._camera_grace.stop()
            self.recordings.refresh(force=False)
            if not self.camera.stream.is_running():
                self.camera.play()
        elif self.camera.stream.is_running() and not self._camera_grace.isActive():
            self._camera_grace.start()

    def _camera_grace_over(self):
        """The Camera tab was left a while ago: stop, unless a recording runs."""
        if self.camera.is_recording():
            return   # stopped with the recording (Stop recording, or the panel closing)
        self.camera.stop()

    def _on_camera_light_clicked(self, checked):
        if self.client is not None:
            self.client.set_toggle("CameraLightControlCapability", checked)

    def _follow_recording(self, state, flag, previous=None, previous_flag=None):
        """While the robot runs (cleaning, going somewhere, returning, driven by hand),
        the camera records, if set: from the first state seen running, QGIS started
        mid-job included. A recording stops once the robot is back on its dock at the
        end of its job, or after STOP_IDLE_MS paused or idle away from it (a new one
        starts when it runs again). A return in the middle of the job (washing the
        mops, clean water: "docked" with the "resumable" flag) does not stop it. One
        stopped by hand while the robot runs is not started again before it docks."""
        if state in JOB_STATES and previous in AT_REST_STATES and previous_flag != "resumable":
            self.jobStarted.emit()   # a new job (the Wi-Fi recorder is checked)
        recording = self.camera.is_recording()
        if self._auto_recording and not recording and state != "docked":
            # Ended under way: by hand (not again before the dock), or by itself
            # (camera lost, ffmpeg error: tried again, at most every RETRY_RECORDING_S)
            self._auto_recording = False
            self._recording_declined = self.camera.stopped_by_user
        if state in RUNNING_STATES:
            self._idle_stop.stop()
            if (not recording and not self._recording_declined
                    and time.monotonic() - self._last_auto_record >= RETRY_RECORDING_S
                    and load_settings()["record_jobs"]):
                self._last_auto_record = time.monotonic()
                self._auto_starting = True   # (a failure at once is said too)
                try:
                    self._record_job()
                finally:
                    self._auto_starting = False
                recording = self._auto_recording = self.camera.is_recording()
        elif state in ("paused", "idle") and recording and self._auto_recording:
            if not self._idle_stop.isActive():
                self._idle_stop.start()   # still not running then: the recording ends
        if not recording:
            self._away_while_recording = False
        elif state != "docked":
            self._away_while_recording = True
        elif flag != "resumable" and self._away_while_recording:
            self._end_recording()
        if state == "docked" and flag != "resumable":
            self._recording_declined = False   # the job is over: the next one is recorded
            self._last_auto_record = -RETRY_RECORDING_S

    def _on_command_sent(self, key):
        """Return to dock: the trip home is always recorded (even with the setting off,
        or a recording stopped by hand earlier); it ends on the dock."""
        if key != "home" or self.camera.is_recording() or self._state in ("docked", None):
            return   # (already home: nothing to film)
        self._recording_declined = False
        self._last_auto_record = time.monotonic()
        self._auto_starting = True
        try:
            self._record_job()
        finally:
            self._auto_starting = False
        self._auto_recording = self.camera.is_recording()
        self._away_while_recording = self._auto_recording   # it stops once docked

    def _on_recordings_collapsed(self, collapsed):
        QgsSettings().setValue(KEY_RECORDINGS_COLLAPSED, collapsed)
        if not collapsed:
            self.recordings.refresh(force=False)

    def _on_record_state(self, state, detail):
        """An automatic recording that fails says so (not only in the Camera tab)."""
        if state == "saved":
            self.recordings.refresh()
        if (self._auto_recording or self._auto_starting) and state in ("failed",
                                                                       "ffmpeg_missing"):
            self.show_feedback(tr("The robot's video could not be recorded: {error}").format(
                error=detail), "warning")

    def _end_recording(self):
        self._away_while_recording = self._auto_recording = False
        self._idle_stop.stop()
        if self.camera.is_recording():
            self.camera.stop_recording()
        self._update_camera()   # the stream stops too if the Camera tab is not shown

    def _stop_idle_recording(self):
        """Paused or idle away from the dock for STOP_IDLE_MS: the recording ends."""
        if self._state in ("paused", "idle") and self._auto_recording:
            self._end_recording()
            self._last_auto_record = -RETRY_RECORDING_S   # a new one when it runs again

    def _record_job(self):
        """Start the camera (if it is not playing) and record into the videos folder."""
        if not self.camera.stream.is_running():
            self.camera.play()
            self._update_camera()   # not shown: stops a while after the recording
        self.camera.record_to(job_videos_folder())
