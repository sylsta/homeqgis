"""Week view of the scheduled cleanings: one column per day, one block per cleaning.

Click a block to select it, double-click it to edit it, double-click an empty
slot to create a cleaning there, or drop a room group (dragged from the rooms
tree of the Clean tab) on a day to schedule it at that time.
"""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from .i18n import tr

FIRST_HOUR, LAST_HOUR = 6, 24     # the visible part of the day
BLOCK_MINUTES = 50                 # drawn length of a cleaning (Valetudo has none)
HEADER = 18                        # day names
GUTTER = 26                        # hours
SNAP_MINUTES = 30


def _pos(event):
    """Event position as a QPointF (Qt 6: position(); Qt 5: pos()/posF())."""
    if hasattr(event, "position"):
        return QPointF(event.position())
    if hasattr(event, "posF"):
        return QPointF(event.posF())
    return QPointF(event.pos())


class WeekView(QWidget):
    timerClicked = pyqtSignal(str)
    timerDoubleClicked = pyqtSignal(str)
    slotDoubleClicked = pyqtSignal(int, int, int)   # Valetudo day (0 = Sunday), hour, minute
    groupDropped = pyqtSignal(int, int, int)        # same, for a drop from the rooms tree

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []      # [(id, label, local days, hour, minute, enabled)]
        self.day_names = {}    # {Valetudo day: short name}
        self.selected = None
        self.drop_source = None   # the rooms tree: drops are accepted from it only
        self._drop_at = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    # -- data ---------------------------------------------------------------------------

    def set_entries(self, entries, day_names):
        self.entries, self.day_names = entries, day_names
        self.update()

    def set_selected(self, timer_id):
        self.selected = timer_id
        self.update()

    # -- geometry -------------------------------------------------------------------------

    def _area(self):
        return QRectF(GUTTER, HEADER, self.width() - GUTTER - 2, self.height() - HEADER - 2)

    @staticmethod
    def _column(dow):
        return (dow - 1) % 7          # Monday first

    def _y(self, hour, minute, area):
        hours = min(max(hour + minute / 60, FIRST_HOUR), LAST_HOUR)
        return area.top() + (hours - FIRST_HOUR) / (LAST_HOUR - FIRST_HOUR) * area.height()

    def _blocks(self):
        """[(rect, id)] of every drawn block, for painting and hit tests."""
        area = self._area()
        width = area.width() / 7
        height = max(14.0, BLOCK_MINUTES / 60 / (LAST_HOUR - FIRST_HOUR) * area.height())
        blocks = []
        for timer_id, label, days, hour, minute, enabled in self.entries:
            top = self._y(hour, minute, area)
            for dow in days:
                left = area.left() + self._column(dow) * width
                blocks.append((QRectF(left + 1, top, width - 2, height), timer_id))
        return blocks

    def _slot_at(self, pos):
        """(Valetudo day, hour, minute) under a point, snapped to SNAP_MINUTES."""
        area = self._area()
        if not area.contains(pos):
            return None
        column = int((pos.x() - area.left()) / (area.width() / 7))
        hours = FIRST_HOUR + (pos.y() - area.top()) / area.height() * (LAST_HOUR - FIRST_HOUR)
        minutes = int(round(hours * 60 / SNAP_MINUTES) * SNAP_MINUTES)
        minutes = min(minutes, 23 * 60 + 30)
        return (column + 1) % 7, minutes // 60, minutes % 60

    def _block_at(self, pos):
        for rect, timer_id in reversed(self._blocks()):
            if rect.contains(pos):
                return timer_id
        return None

    # -- painting -------------------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        width = area.width() / 7
        grid = self.palette().mid().color()
        text = self.palette().windowText().color()
        small = QFont(self.font())
        small.setPointSizeF(max(6.5, small.pointSizeF() * 0.8))
        painter.setFont(small)
        for column in range(7):   # day names, Monday first
            dow = (column + 1) % 7
            rect = QRectF(area.left() + column * width, 0, width, HEADER)
            painter.setPen(text)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.day_names.get(dow, ""))
            painter.setPen(QPen(grid, 0.5))
            painter.drawLine(int(rect.left()), HEADER, int(rect.left()), int(area.bottom()))
        for hour in range(FIRST_HOUR, LAST_HOUR + 1, 3):   # hour lines
            y = self._y(hour, 0, area)
            painter.setPen(QPen(grid, 0.5, Qt.PenStyle.DotLine))
            painter.drawLine(int(area.left()), int(y), int(area.right()), int(y))
            painter.setPen(text)
            painter.drawText(QRectF(0, y - 7, GUTTER - 3, 14),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{hour % 24:02d}")
        labels = {e[0]: (e[1], e[5]) for e in self.entries}
        for rect, timer_id in self._blocks():
            label, enabled = labels[timer_id]
            color = QColor("#1565c0" if enabled else "#9e9e9e")
            fill = QColor(color)
            fill.setAlpha(200 if timer_id == self.selected else 120)
            painter.setPen(QPen(color.darker(130), 2 if timer_id == self.selected else 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(rect.adjusted(2, 0, -1, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        if self._drop_at is not None:   # where a dropped group would go
            dow, hour, minute = self._drop_at
            top = self._y(hour, minute, area)
            painter.setPen(QPen(QColor("#2e7d32"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(area.left() + self._column(dow) * width + 1, top,
                                    width - 2, 16))
        if not self.entries and self._drop_at is None:
            painter.setPen(QColor("#9e9e9e"))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             tr("No scheduled cleaning.\nDouble-click a slot, or drop a "
                                "room group here."))

    # -- mouse ----------------------------------------------------------------------------

    def mousePressEvent(self, event):
        timer_id = self._block_at(_pos(event))
        if timer_id is not None:
            self.timerClicked.emit(timer_id)

    def mouseDoubleClickEvent(self, event):
        pos = _pos(event)
        timer_id = self._block_at(pos)
        if timer_id is not None:
            self.timerDoubleClicked.emit(timer_id)
            return
        slot = self._slot_at(pos)
        if slot is not None:
            self.slotDoubleClicked.emit(*slot)

    def mouseMoveEvent(self, event):
        timer_id = self._block_at(_pos(event))
        label = next((e[1] for e in self.entries if e[0] == timer_id), "")
        self.setToolTip(label)

    # -- drop of a room group -------------------------------------------------------------

    def _accepts(self, event):
        return self.drop_source is not None and event.source() is self.drop_source

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not self._accepts(event):
            return
        pos = _pos(event)
        self._drop_at = self._slot_at(pos)
        self.update()
        if self._drop_at is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, _event):
        self._drop_at = None
        self.update()

    def dropEvent(self, event):
        slot, self._drop_at = self._drop_at, None
        self.update()
        if self._accepts(event) and slot is not None:
            event.acceptProposedAction()
            self.groupDropped.emit(*slot)
