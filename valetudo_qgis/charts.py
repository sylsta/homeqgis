"""Charts for the Home section, drawn with QPainter (no chart library needed):

    ChartWidget        curves (one or two units: left and right axes), on/off
                       timelines under them, shaded marks (the robot's cleanings),
                       a crosshair with the values under the mouse
    sparkline_pixmap() a small graph for a list line
"""

import math
import time

from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

PALETTE = ["#1565c0", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f", "#c62828", "#5d4037",
           "#ad1457", "#558b2f", "#283593"]
MARK_COLOR = QColor(46, 125, 50, 40)


def color(index):
    return QColor(PALETTE[index % len(PALETTE)])


def _nice_step(span, count):
    """A round step (1, 2, 5 × 10^n) giving about count ticks over span."""
    if span <= 0:
        return 1
    raw = span / max(1, count)
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 5, 10):
        if raw <= factor * power:
            return factor * power
    return 10 * power


def _time_ticks(start, end):
    """(times, format) for the x axis: hours over a day or so, then days."""
    span = end - start
    steps = [(900, "%H:%M"), (1800, "%H:%M"), (3600, "%H:%M"), (3 * 3600, "%H:%M"),
             (6 * 3600, "%H:%M"), (12 * 3600, "%d/%m %Hh"), (86400, "%d/%m"),
             (2 * 86400, "%d/%m")]
    for step, fmt in steps:
        if span / step <= 8:
            break
    offset = time.localtime(start).tm_gmtoff   # ticks on local round hours
    first = math.ceil((start + offset) / step) * step - offset
    return [first + i * step for i in range(int((end - first) // step) + 1)], fmt


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.start = self.end = 0
        self.series, self.timelines, self.marks = [], [], []
        self.message = ""
        self._mouse = None

    def sizeHint(self):
        return QSize(320, 220)

    def set_message(self, text):
        self.series, self.timelines, self.marks, self.message = [], [], [], text
        self.update()

    def set_data(self, start, end, series=(), timelines=(), marks=()):
        """series: [{name, unit, points [(t, v)], color?}]; timelines: [{name, periods
        [(from, to)], color?}]; marks: [(from, to, label)]."""
        self.start, self.end = start, end
        self.series = [dict(s, color=s.get("color") or color(i)) for i, s in enumerate(series)]
        self.timelines = [dict(t, color=t.get("color") or color(i + len(self.series)))
                          for i, t in enumerate(timelines)]
        self.marks = list(marks)
        self.message = ""
        self.update()

    # -- geometry ---------------------------------------------------------------------

    def _units(self):
        units = []
        for s in self.series:
            if s.get("unit", "") not in units:
                units.append(s.get("unit", ""))
        return units[:2]

    def _plot_rect(self):
        rows = len(self.timelines)
        legend = 16 if self.series else 0
        left = 44
        right = 44 if len(self._units()) > 1 else 10
        bottom = 22 + rows * 14 + (4 if rows else 0)
        return QRectF(left, 6 + legend, max(10, self.width() - left - right),
                      max(10, self.height() - 6 - legend - bottom))

    def _x(self, t, rect):
        span = (self.end - self.start) or 1
        return rect.left() + (t - self.start) / span * rect.width()

    def _range(self, unit):
        values = [v for s in self.series if s.get("unit", "") == unit for _, v in s["points"]
                  if self.start <= _ <= self.end] or \
                 [v for s in self.series if s.get("unit", "") == unit for _, v in s["points"]]
        if not values:
            return 0, 1
        low, high = min(values), max(values)
        if high - low < 1e-9:
            low, high = low - 1, high + 1
        pad = (high - low) * 0.08
        return low - pad, high + pad

    # -- painting ---------------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().color(self.foregroundRole())
        grid = QColor(text_color)
        grid.setAlpha(40)
        font = QFont(self.font())
        font.setPointSizeF(max(6.5, font.pointSizeF() * 0.85))
        painter.setFont(font)
        if self.message or self.end <= self.start:
            painter.setPen(text_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        rect = self._plot_rect()
        # robot marks
        for begin, finish, _label in self.marks:
            x1, x2 = self._x(max(begin, self.start), rect), self._x(min(finish, self.end), rect)
            if x2 > x1:
                painter.fillRect(QRectF(x1, rect.top(), max(1.5, x2 - x1), rect.height()),
                                 MARK_COLOR)
        # x grid and labels
        ticks, fmt = _time_ticks(self.start, self.end)
        painter.setPen(QPen(grid, 1))
        for t in ticks:
            x = self._x(t, rect)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.setPen(text_color)
        bottom_labels = rect.bottom() + 4 + len(self.timelines) * 14 + (4 if self.timelines else 0)
        for t in ticks:
            x = self._x(t, rect)
            painter.drawText(QRectF(x - 40, bottom_labels, 80, 14), Qt.AlignmentFlag.AlignCenter,
                             time.strftime(fmt, time.localtime(t)))
        # y axes
        units = self._units()
        ranges = {unit: self._range(unit) for unit in units}
        for side, unit in enumerate(units):
            low, high = ranges[unit]
            step = _nice_step(high - low, 4)
            value = math.ceil(low / step) * step
            while value <= high:
                y = rect.bottom() - (value - low) / (high - low) * rect.height()
                if side == 0:
                    painter.setPen(QPen(grid, 1))
                    painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                painter.setPen(text_color)
                label = f"{value:g}"
                if side == 0:
                    painter.drawText(QRectF(0, y - 7, rect.left() - 4, 14),
                                     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                     label)
                else:
                    painter.drawText(QRectF(rect.right() + 4, y - 7, 40, 14),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     label)
                value += step
        # curves (steps: a state holds until the next one)
        painter.save()
        painter.setClipRect(rect)
        for s in self.series:
            low, high = ranges.get(s.get("unit", ""), (0, 1))
            path, started = QPainterPath(), False
            previous_y = None
            for t, v in s["points"]:
                x = self._x(t, rect)
                y = rect.bottom() - (v - low) / (high - low) * rect.height()
                if not started:
                    path.moveTo(x, y)
                    started = True
                else:
                    path.lineTo(x, previous_y)
                    path.lineTo(x, y)
                previous_y = y
            if started:
                path.lineTo(self._x(min(self.end, time.time()), rect), previous_y)
                painter.setPen(QPen(s["color"], 1.6))
                painter.drawPath(path)
        painter.restore()
        # timelines (on periods as bars)
        y = rect.bottom() + 4
        for line in self.timelines:
            painter.setPen(text_color)
            painter.drawText(QRectF(0, y, rect.left() - 4, 12),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             line["name"][:8])
            band = QColor(line["color"])
            band.setAlpha(50)
            painter.fillRect(QRectF(rect.left(), y + 2, rect.width(), 8), band)
            for begin, finish in line["periods"]:
                x1, x2 = self._x(max(begin, self.start), rect), self._x(min(finish, self.end), rect)
                painter.fillRect(QRectF(x1, y + 2, max(1.5, x2 - x1), 8), line["color"])
            y += 14
        # legend
        x = rect.left()
        for s in self.series:
            painter.setPen(QPen(s["color"], 3))
            painter.drawLine(QPointF(x, 12), QPointF(x + 12, 12))
            painter.setPen(text_color)
            label = f"{s['name']} ({s['unit']})" if s.get("unit") else s["name"]
            width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(QPointF(x + 16, 16), label)
            x += 28 + width
        # crosshair
        if self._mouse is not None and rect.contains(self._mouse):
            self._draw_crosshair(painter, rect, text_color)

    def _draw_crosshair(self, painter, rect, text_color):
        x = self._mouse.x()
        t = self.start + (x - rect.left()) / rect.width() * (self.end - self.start)
        painter.setPen(QPen(text_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        lines = [time.strftime("%d/%m %H:%M", time.localtime(t))]
        for s in self.series:
            value = next((v for tt, v in reversed(s["points"]) if tt <= t), None)
            if value is not None:
                lines.append(f"{s['name']}: {value:g} {s.get('unit', '')}".strip())
        for line in self.timelines:
            on = any(a <= t <= b for a, b in line["periods"])
            lines.append(f"{line['name']}: {'●' if on else '○'}")
        for begin, finish, label in self.marks:
            if begin <= t <= finish:
                lines.append(label)
        metrics = painter.fontMetrics()
        width = max(metrics.horizontalAdvance(line) for line in lines) + 10
        height = metrics.height() * len(lines) + 6
        left = x + 8 if x + 8 + width < rect.right() else x - 8 - width
        box = QRectF(left, rect.top() + 4, width, height)
        background = self.palette().color(self.backgroundRole())
        background.setAlpha(230)
        painter.fillRect(box, background)
        painter.setPen(QPen(text_color, 0.5))
        painter.drawRect(box)
        for i, line in enumerate(lines):
            painter.drawText(QPointF(box.left() + 5, box.top() + 3 + metrics.ascent()
                                     + i * metrics.height()), line)

    def mouseMoveEvent(self, event):
        self._mouse = event.position() if hasattr(event, "position") else QPointF(event.pos())
        self.update()

    def leaveEvent(self, _event):
        self._mouse = None
        self.update()


def sparkline_pixmap(values, width=80, height=16, line_color="#1565c0", binary=False):
    """A small graph of values (None: no data): a line, or on/off bars when binary."""
    ratio = 2   # drawn at twice the size: sharp on HiDPI screens
    pixmap = QPixmap(width * ratio, height * ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    known = [v for v in values if v is not None]
    if not known:
        pixmap.setDevicePixelRatio(ratio)
        return pixmap
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = width * ratio, height * ratio
    step = w / max(1, len(values))
    pen_color = QColor(line_color)
    if binary:
        for i, v in enumerate(values):
            if v:
                painter.fillRect(QRectF(i * step, h * 0.2, max(ratio, step), h * 0.6), pen_color)
        base = QColor(pen_color)
        base.setAlpha(60)
        painter.fillRect(QRectF(0, h * 0.45, w, h * 0.1), base)
    else:
        low, high = min(known), max(known)
        if high - low < 1e-9:
            low, high = low - 1, high + 1
        path, started = QPainterPath(), False
        for i, v in enumerate(values):
            if v is None:
                continue
            x = i * step + step / 2
            y = h - 2 - (v - low) / (high - low) * (h - 4)
            if started:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                started = True
        painter.setPen(QPen(pen_color, 1.4 * ratio))
        painter.drawPath(path)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap
