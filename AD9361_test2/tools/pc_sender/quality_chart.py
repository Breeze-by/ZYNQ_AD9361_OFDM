"""Time-based quality plots with explicit unavailable samples (not zero)."""
import math
import tkinter as tk
from collections import deque


class QualityChart(tk.Canvas):
    def __init__(self, master, unit="%", color="#1976D2", **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.unit = unit
        self.color = color
        self.points = deque(maxlen=2400)
        self.message = "Waiting for data"
        self.bind("<Configure>", lambda _event: self.redraw())

    def reset(self):
        self.points.clear()
        self.message = "Waiting for data"
        self.redraw()

    def add_point(self, timestamp, value, message=""):
        timestamp = float(timestamp)
        if not math.isfinite(timestamp):
            return
        if self.points and timestamp <= self.points[-1][0]:
            return
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                value = None
        self.points.append((timestamp, value))
        self.message = message
        while len(self.points) > 1 and self.points[0][0] < timestamp - 60.0:
            self.points.popleft()
        self.redraw()

    def redraw(self):
        self.delete("all")
        width, height = max(self.winfo_width(), 100), max(self.winfo_height(), 90)
        left, right, top, bottom = 56, width - 10, 23, height - 23
        self.create_rectangle(0, 0, width, height, fill="#FCFCFD", outline="#D0D7DE")
        values = [v for _t, v in self.points if v is not None]
        latest = self.points[-1][1] if self.points else None
        text = f"{latest:.4f} {self.unit}" if latest is not None else "N/A"
        self.create_text(right, 8, text=text, anchor="ne", fill=self.color)
        if not values:
            self.create_text(width / 2, height / 2, text=self.message or "No samples",
                             width=max(width - 20, 80), fill="#666666", justify="center")
            return
        low = min(0.0, min(values))
        high = max(values)
        if high <= low:
            high = low + (1.0 if self.unit == "dB" else 0.01)
        for index in range(3):
            y = bottom - (bottom - top) * index / 2
            v = low + (high - low) * index / 2
            self.create_line(left, y, right, y, fill="#E5E7EB")
            self.create_text(left - 4, y, text=f"{v:.3g}", anchor="e", fill="#6B7280")
        end = self.points[-1][0]
        start = max(self.points[0][0], end - 60.0)
        span = max(end - start, 1.0)
        segment = []

        def draw_segment():
            if len(segment) >= 4:
                self.create_line(*segment, fill=self.color, width=2)
            elif segment:
                x, y = segment
                self.create_oval(x - 2, y - 2, x + 2, y + 2, fill=self.color, outline="")

        for timestamp, value in self.points:
            if value is None:
                draw_segment()
                segment.clear()
                continue
            x = left + (timestamp - start) / span * (right - left)
            y = bottom - (value - low) / (high - low) * (bottom - top)
            segment.extend((x, y))
        draw_segment()
        self.create_text(left, height - 7, text=f"-{end - start:.1f}s", anchor="sw", fill="#6B7280")
        self.create_text(right, height - 7, text="now", anchor="se", fill="#6B7280")
