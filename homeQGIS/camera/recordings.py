"""The Camera tab's recordings: videos, snapshots, camera views and obstacle photos,
as thumbnails, newest first. A double-click opens one (the system's player or image
viewer); the context menu shows it in its folder or deletes it.

Where they are:
- videos: videos/ next to the project (recordings of the robot), and the folder of
  the last recording made by hand (*.mp4);
- snapshots: photos/ next to the project, and the folder of the last snapshot;
- camera views: views/<date>/ next to the project (camera/views.py);
- obstacle photos: map/obstacles/ next to the project (map/obstacle_diary.py).

A video's thumbnail is an image taken by ffmpeg 1 s in, kept in a cache folder of
the QGIS profile (by path, size and date of the file).
"""

import glob
import hashlib
import os

from qgis.PyQt.QtCore import QDateTime, QProcess, QSize, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (QComboBox, QHBoxLayout, QListWidget, QListWidgetItem,
                                 QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)
from qgis.core import QgsApplication, QgsSettings
from qgis.gui import QgsCollapsibleGroupBox

from .stream import find_ffmpeg
from .widget import JOB_VIDEOS, KEY_RECORD_DIR, KEY_SNAPSHOT_DIR, SNAPSHOTS
from ..core.i18n import tr
from .views import VIEWS_FOLDER
from ..map.obstacle_diary import FOLDER as OBSTACLE_FOLDER, PHOTOS as OBSTACLE_PHOTOS
from ..core.project_layers import project_folder
from ..core.settings import load_settings

MAX_ITEMS = 300            # newest first; older ones are in their folders
THUMB = QSize(160, 90)
BATCH = 12                 # images turned into thumbnails per step (stays smooth)
KINDS = ("videos", "snapshots", "views", "obstacles")
VIDEO_EXT = (".mp4", ".mkv", ".mov")
IMAGE_EXT = (".png", ".jpg", ".jpeg")


def kind_labels():
    return {"videos": tr("Videos"), "snapshots": tr("Snapshots"),
            "views": tr("Camera views"), "obstacles": tr("Obstacle photos")}


def _files(folders, extensions, recursive=False):
    seen, found = set(), []
    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        pattern = os.path.join(folder, "**", "*") if recursive else os.path.join(folder, "*")
        for path in glob.glob(pattern, recursive=recursive):
            real = os.path.realpath(path)
            if real in seen or not path.lower().endswith(extensions) or not os.path.isfile(path):
                continue
            seen.add(real)
            found.append(path)
    return sorted(found, key=lambda p: os.path.getmtime(p), reverse=True)[:MAX_ITEMS]


def files(kind):
    """The files of a kind, newest first."""
    settings = QgsSettings()
    if kind == "videos":
        return _files([project_folder(JOB_VIDEOS), settings.value(KEY_RECORD_DIR, "", type=str)],
                      VIDEO_EXT)
    if kind == "snapshots":
        return _files([project_folder(SNAPSHOTS),
                       settings.value(KEY_SNAPSHOT_DIR, "", type=str)], IMAGE_EXT)
    if kind == "views":
        return _files([project_folder(VIEWS_FOLDER)], IMAGE_EXT, recursive=True)
    if kind == "obstacles":
        folder = project_folder(OBSTACLE_FOLDER)
        return _files([os.path.join(folder, OBSTACLE_PHOTOS) if folder else None], IMAGE_EXT)
    return []


def thumbs_folder():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), "homeqgis_thumbnails")
    os.makedirs(path, exist_ok=True)
    return path


def thumb_path(video):
    stat = os.stat(video)
    key = f"{os.path.realpath(video)}|{stat.st_size}|{int(stat.st_mtime)}"
    return os.path.join(thumbs_folder(), hashlib.sha1(key.encode()).hexdigest() + ".jpg")


def describe(path):
    when = QDateTime.fromSecsSinceEpoch(int(os.path.getmtime(path)))
    size = os.path.getsize(path)
    text = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} kB"
    return f"{when.toString('dd/MM HH:mm')}\n{text}"


class RecordingsBox(QgsCollapsibleGroupBox):
    def __init__(self, parent=None):
        super().__init__(tr("Recordings"), parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for key, label in kind_labels().items():
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(lambda *_: self.refresh())
        row.addWidget(self.kind, 1)
        self.btn_folder = QPushButton(tr("Folder"))
        self.btn_folder.setToolTip(tr("Open the folder of the newest one"))
        self.btn_folder.clicked.connect(self._open_folder)
        row.addWidget(self.btn_folder)
        self.btn_refresh = QPushButton(tr("Refresh"))
        self.btn_refresh.clicked.connect(lambda *_: self.refresh())
        row.addWidget(self.btn_refresh)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(220)
        self.list.setUniformItemSizes(True)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemActivated.connect(lambda item: self._open(item))
        layout.addWidget(self.list)
        self._pending = []        # items still without their thumbnail
        self._thumbs = QTimer(self)
        self._thumbs.setInterval(30)
        self._thumbs.timeout.connect(self._next_thumbs)
        self._ffmpeg = None       # the QProcess making a video's thumbnail
        self._ffmpeg_item = None
        self._shown = []          # paths now in the list (no reload if unchanged)

    # -- the list ------------------------------------------------------------------

    def refresh(self, force=True):
        if self.isCollapsed() or not self.isVisible():
            return
        kind = self.kind.currentData()
        paths = files(kind)
        if not force and paths == self._shown:
            return
        self._shown = paths
        self.list.clear()
        self._pending = []
        placeholder = QIcon(QgsApplication.getThemeIcon(
            "/temporal_navigation/forward.svg" if kind == "videos" else "/mIconRasterLayer.svg"))
        for path in paths:
            item = QListWidgetItem(placeholder, describe(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            item.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 44))
            self.list.addItem(item)
            self._pending.append(item)
        self.btn_folder.setEnabled(bool(paths))
        if not paths:
            empty = QListWidgetItem(tr("Nothing yet."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        self._thumbs.start()

    def _next_thumbs(self):
        if self._ffmpeg is not None:
            return   # one video at a time
        for _ in range(BATCH):
            if not self._pending:
                self._thumbs.stop()
                return
            item = self._pending.pop(0)
            try:
                path = item.data(Qt.ItemDataRole.UserRole)
            except RuntimeError:   # the list was cleared meanwhile
                continue
            if path.lower().endswith(VIDEO_EXT):
                cached = thumb_path(path) if os.path.exists(path) else None
                if cached and os.path.exists(cached):
                    self._set_icon(item, cached)
                elif cached:
                    self._make_video_thumb(item, path, cached)
                    return
            else:
                self._set_icon(item, path)

    def _set_icon(self, item, image):
        pixmap = QPixmap(image)
        if pixmap.isNull():
            return
        try:
            item.setIcon(QIcon(pixmap.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)))
        except RuntimeError:
            pass

    def _make_video_thumb(self, item, video, target):
        program = find_ffmpeg(load_settings()["ffmpeg"])
        if not program:
            return
        process = self._ffmpeg = QProcess(self)
        self._ffmpeg_item = (item, target)
        process.finished.connect(self._video_thumb_done)
        process.errorOccurred.connect(lambda *_: self._video_thumb_done())
        process.start(program, ["-hide_banner", "-loglevel", "error", "-y", "-ss", "1",
                                "-i", video, "-frames:v", "1",
                                "-vf", f"scale={THUMB.width() * 2}:-2", target])

    def _video_thumb_done(self, *_):
        if self._ffmpeg is None:
            return
        self._ffmpeg.deleteLater()
        self._ffmpeg = None
        item, target = self._ffmpeg_item
        if os.path.exists(target):
            self._set_icon(item, target)

    # -- actions ----------------------------------------------------------------------

    def _path(self, item):
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _open(self, item):
        path = self._path(item)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self, *_):
        if self._shown:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._shown[0])))

    def _menu(self, position):
        item = self.list.itemAt(position)
        path = self._path(item)
        if not path:
            return
        menu = QMenu(self)
        menu.addAction(tr("Open"), lambda: self._open(item))
        menu.addAction(tr("Open its folder"), lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(path))))
        menu.addSeparator()
        menu.addAction(tr("Delete…"), lambda: self._delete(path))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _delete(self, path):
        answer = QMessageBox.question(self, tr("Delete"), tr("Delete {name}?").format(
            name=os.path.basename(path)))
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Delete"), str(exc))
        self.refresh()
