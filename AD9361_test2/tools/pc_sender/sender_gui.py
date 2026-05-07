#!/usr/bin/env python3
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from sender_core import (
    ACK_STATUS_NAMES,
    SenderConfig,
    UdpSender,
    load_payload,
)


class Sparkline(tk.Canvas):
    def __init__(self, master, max_points=90, line_color="#1f77b4", unit="", **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.max_points = max_points
        self.line_color = line_color
        self.unit = unit
        self.points = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def add_point(self, value):
        self.points.append(max(0.0, float(value)))
        if len(self.points) > self.max_points:
            self.points = self.points[-self.max_points:]
        self.redraw()

    def reset(self):
        self.points.clear()
        self.redraw()

    def redraw(self):
        self.delete("all")
        width = max(self.winfo_width(), 10)
        height = max(self.winfo_height(), 10)
        left_pad = 48
        right_pad = 12
        top_pad = 16
        bottom_pad = 22
        plot_width = max(width - left_pad - right_pad, 10)
        plot_height = max(height - top_pad - bottom_pad, 10)

        self.create_rectangle(0, 0, width, height, outline="#D0D7DE", fill="#FCFCFD")
        self.create_rectangle(left_pad, top_pad, left_pad + plot_width, top_pad + plot_height,
            outline="#E5E7EB", fill="#FFFFFF")

        if len(self.points) < 2:
            self.create_text(width - 10, 10, anchor="ne", text=f"0 {self.unit}", fill="#555555")
            return

        max_value = max(self.points)
        if max_value <= 0.0:
            max_value = 1.0

        for tick_index in range(4):
            fraction = tick_index / 3.0
            y = top_pad + plot_height - (fraction * plot_height)
            tick_value = max_value * fraction
            self.create_line(left_pad, y, left_pad + plot_width, y, fill="#EEF2F7")
            self.create_text(left_pad - 6, y, anchor="e", text=f"{tick_value:.0f}", fill="#6B7280")

        x_step = plot_width / max(len(self.points) - 1, 1)
        coords = []
        for index, value in enumerate(self.points):
            x = left_pad + index * x_step
            y = top_pad + plot_height - (value / max_value) * plot_height
            coords.extend([x, y])
        self.create_line(*coords, fill=self.line_color, width=2, smooth=True)
        self.create_text(width - 10, 10, anchor="ne",
            text=f"{self.points[-1]:.2f} {self.unit}", fill=self.line_color)
        self.create_text(width - 10, height - 8, anchor="se",
            text=f"max {max_value:.2f}", fill="#6B7280")


class SenderGui:
    def __init__(self, root):
        self.root = root
        self.root.title("AD9361_test2 UDP Sender")
        self.root.geometry("1260x860")
        self.root.minsize(1180, 760)

        self.event_queue = queue.Queue()
        self.sender_thread = None
        self.sender = None

        self.mode_var = tk.StringVar(value="file")
        self.file_path_var = tk.StringVar()
        self.file_info_var = tk.StringVar(value="未选择文件")
        self.ip_var = tk.StringVar(value="192.168.1.50")
        self.port_var = tk.StringVar(value="5001")
        self.chunk_var = tk.StringVar(value="1400")
        self.timeout_var = tk.StringVar(value="1.0")
        self.retries_var = tk.StringVar(value="10")
        self.target_rate_var = tk.StringVar(value="0")
        self.window_var = tk.StringVar(value="4")
        self.test_size_var = tk.StringVar(value="4096")

        self.status_text_var = tk.StringVar(value="空闲")
        self.progress_text_var = tk.StringVar(value="0 / 0")
        self.ack_status_var = tk.StringVar(value="N/A")
        self.seq_var = tk.StringVar(value="-")
        self.window_used_var = tk.StringVar(value="0")
        self.rtt_var = tk.StringVar(value="0.00 ms")
        self.current_rate_var = tk.StringVar(value="0.00 KiB/s")
        self.avg_rate_var = tk.StringVar(value="0.00 KiB/s")
        self.ps_rate_var = tk.StringVar(value="0.00 KiB/s")
        self.ack_ok_var = tk.StringVar(value="0")
        self.timeout_count_var = tk.StringVar(value="0")
        self.retry_count_var = tk.StringVar(value="0")
        self.busy_count_var = tk.StringVar(value="0")
        self.error_count_var = tk.StringVar(value="0")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.last_update_time = time.time()
        self.sent_speed_chart = None
        self.ps_speed_chart = None
        self.rtt_chart = None

        self._build_ui()
        self._update_mode_widgets()
        self.root.after(100, self._drain_event_queue)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            root_frame,
            text="AD9361_test2 上位机发射端",
            font=("Microsoft YaHei", 18, "bold"),
        )
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            root_frame,
            text="支持发送常见二进制源文件（jpg / png / bin / mp4 / ts / txt 等），支持测试数据发送、速率限制、ACK 状态监控和实时吞吐显示。",
        )
        subtitle.pack(anchor=tk.W, pady=(4, 10))

        top_split = ttk.Panedwindow(root_frame, orient=tk.HORIZONTAL)
        top_split.pack(fill=tk.BOTH, expand=False)

        left_config = ttk.Frame(top_split, padding=(0, 0, 8, 0))
        right_metrics = ttk.Frame(top_split, padding=(8, 0, 0, 0))
        top_split.add(left_config, weight=3)
        top_split.add(right_metrics, weight=2)

        self._build_config_panel(left_config)
        self._build_metrics_panel(right_metrics)

        mid_frame = ttk.Frame(root_frame)
        mid_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self._build_chart_panel(mid_frame)

        bottom_frame = ttk.Frame(root_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self._build_log_panel(bottom_frame)

    def _build_config_panel(self, parent):
        source_box = ttk.LabelFrame(parent, text="发送源", padding=12)
        source_box.pack(fill=tk.X)

        mode_frame = ttk.Frame(source_box)
        mode_frame.pack(fill=tk.X)
        ttk.Radiobutton(mode_frame, text="文件发送", value="file", variable=self.mode_var,
            command=self._update_mode_widgets).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="测试数据", value="test", variable=self.mode_var,
            command=self._update_mode_widgets).pack(side=tk.LEFT, padx=(12, 0))

        file_row = ttk.Frame(source_box)
        file_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(file_row, text="文件路径", width=10).pack(side=tk.LEFT)
        self.file_entry = ttk.Entry(file_row, textvariable=self.file_path_var)
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_row, text="浏览", command=self._browse_file).pack(side=tk.LEFT, padx=(8, 0))

        info_row = ttk.Frame(source_box)
        info_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(info_row, text="文件信息", width=10).pack(side=tk.LEFT)
        ttk.Label(info_row, textvariable=self.file_info_var).pack(side=tk.LEFT)

        test_row = ttk.Frame(source_box)
        test_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(test_row, text="测试字节数", width=10).pack(side=tk.LEFT)
        self.test_entry = ttk.Entry(test_row, textvariable=self.test_size_var, width=16)
        self.test_entry.pack(side=tk.LEFT)

        net_box = ttk.LabelFrame(parent, text="网络与发送参数", padding=12)
        net_box.pack(fill=tk.X, pady=(12, 0))

        fields = [
            ("目标 IP", self.ip_var),
            ("目标端口", self.port_var),
            ("Chunk 大小", self.chunk_var),
            ("ACK 超时(s)", self.timeout_var),
            ("最大重试", self.retries_var),
            ("限速(KiB/s)", self.target_rate_var),
            ("窗口大小", self.window_var),
        ]

        for row_index, (label_text, variable) in enumerate(fields):
            row = ttk.Frame(net_box)
            row.pack(fill=tk.X, pady=(0, 8) if row_index < len(fields) - 1 else (0, 0))
            ttk.Label(row, text=label_text, width=12).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=variable, width=18).pack(side=tk.LEFT)

        helper = ttk.Label(
            net_box,
            text="限速=0 表示不主动限速。停止等待协议下，真实吞吐还会受 ACK 往返时间限制。",
            foreground="#555555",
        )
        helper.pack(anchor=tk.W, pady=(8, 0))

        action_box = ttk.LabelFrame(parent, text="控制", padding=12)
        action_box.pack(fill=tk.X, pady=(12, 0))

        button_row = ttk.Frame(action_box)
        button_row.pack(fill=tk.X)
        self.send_button = ttk.Button(button_row, text="一键发送", command=self._start_send)
        self.send_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(button_row, text="停止", command=self._stop_send, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_row, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))

        self.progress_bar = ttk.Progressbar(action_box, variable=self.progress_var, maximum=100.0)
        self.progress_bar.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(action_box, textvariable=self.progress_text_var).pack(anchor=tk.W, pady=(6, 0))

    def _build_metrics_panel(self, parent):
        status_box = ttk.LabelFrame(parent, text="状态概览", padding=12)
        status_box.pack(fill=tk.BOTH, expand=True)

        metrics = [
            ("当前状态", self.status_text_var),
            ("最近 ACK 状态", self.ack_status_var),
            ("最近 Seq", self.seq_var),
            ("当前 Inflight", self.window_used_var),
            ("最近 RTT", self.rtt_var),
            ("当前发送速率", self.current_rate_var),
            ("平均发送速率", self.avg_rate_var),
            ("估计 PS 侧速率", self.ps_rate_var),
            ("ACK OK 数", self.ack_ok_var),
            ("Timeout 数", self.timeout_count_var),
            ("重试次数", self.retry_count_var),
            ("BUSY 次数", self.busy_count_var),
            ("错误 ACK 次数", self.error_count_var),
        ]

        for label_text, variable in metrics:
            row = ttk.Frame(status_box)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=label_text, width=16).pack(side=tk.LEFT)
            ttk.Label(row, textvariable=variable, font=("Consolas", 10)).pack(side=tk.LEFT)

    def _build_chart_panel(self, parent):
        chart_box = ttk.LabelFrame(parent, text="实时可视化", padding=12)
        chart_box.pack(fill=tk.BOTH, expand=True)

        chart_grid = ttk.Frame(chart_box)
        chart_grid.pack(fill=tk.BOTH, expand=True)

        chart_defs = [
            ("发送速率 KiB/s", "#1976D2"),
            ("估计 PS 侧速率 KiB/s", "#2E7D32"),
            ("RTT ms", "#EF6C00"),
        ]

        charts = []
        for index, (title_text, color) in enumerate(chart_defs):
            frame = ttk.Frame(chart_grid)
            frame.grid(row=0, column=index, sticky="nsew", padx=(0, 8) if index < 2 else 0)
            chart_grid.columnconfigure(index, weight=1)
            chart_grid.rowconfigure(0, weight=1)
            ttk.Label(frame, text=title_text).pack(anchor=tk.W)
            unit = "KiB/s" if index < 2 else "ms"
            chart = Sparkline(frame, height=190, bg="white", line_color=color, unit=unit)
            chart.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
            charts.append(chart)

        self.sent_speed_chart, self.ps_speed_chart, self.rtt_chart = charts

    def _build_log_panel(self, parent):
        log_box = ttk.LabelFrame(parent, text="事件日志", padding=12)
        log_box.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_box, height=16, wrap="none")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_y = ttk.Scrollbar(log_box, orient=tk.VERTICAL, command=self.log_text.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll_y.set)

    def _update_mode_widgets(self):
        mode = self.mode_var.get()
        file_state = tk.NORMAL if mode == "file" else tk.DISABLED
        test_state = tk.NORMAL if mode == "test" else tk.DISABLED
        self.file_entry.configure(state=file_state)
        self.test_entry.configure(state=test_state)

    def _browse_file(self):
        file_path = filedialog.askopenfilename(
            title="选择要发送的文件",
            filetypes=[
                ("常见媒体和二进制", "*.jpg *.jpeg *.png *.bmp *.gif *.bin *.mp4 *.mov *.avi *.ts *.txt *.csv *.json"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return

        path = Path(file_path)
        self.file_path_var.set(file_path)
        suffix = path.suffix.lower() if path.suffix else "(无扩展名)"
        self.file_info_var.set(f"{path.name} | {suffix} | {path.stat().st_size} bytes")

    def _append_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _start_send(self):
        try:
            payload = self._build_payload()
            config = SenderConfig(
                ip=self.ip_var.get().strip(),
                port=int(self.port_var.get().strip()),
                chunk_size=int(self.chunk_var.get().strip()),
                timeout=float(self.timeout_var.get().strip()),
                retries=int(self.retries_var.get().strip()),
                target_rate_kib_s=float(self.target_rate_var.get().strip()),
                window_size=int(self.window_var.get().strip()),
            )
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self._reset_runtime_state(len(payload))
        self.sender = UdpSender(config)
        self.send_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_text_var.set("发送中")
        self._append_log(f"开始发送，目标 {config.ip}:{config.port}，总字节 {len(payload)}")

        self.sender_thread = threading.Thread(
            target=self._worker_send,
            args=(payload,),
            daemon=True,
        )
        self.sender_thread.start()

    def _stop_send(self):
        if self.sender is not None:
            self.sender.stop()
            self.status_text_var.set("正在停止")
            self._append_log("收到停止请求")

    def _worker_send(self, payload: bytes):
        try:
            self.sender.send(payload, callback=self._sender_callback)
        except Exception as exc:
            self.event_queue.put(("error", {"message": str(exc)}))

    def _sender_callback(self, event_name: str, payload: dict):
        self.event_queue.put((event_name, payload))

    def _build_payload(self) -> bytes:
        mode = self.mode_var.get()
        if mode == "file":
            file_path = self.file_path_var.get().strip()
            if not file_path:
                raise ValueError("请先选择文件")
            return load_payload(file_path=file_path)
        return load_payload(test_size=int(self.test_size_var.get().strip()))

    def _reset_runtime_state(self, total_size: int):
        self.progress_var.set(0.0)
        self.progress_text_var.set(f"0 / {total_size}")
        self.ack_status_var.set("N/A")
        self.seq_var.set("-")
        self.window_used_var.set("0")
        self.rtt_var.set("0.00 ms")
        self.current_rate_var.set("0.00 KiB/s")
        self.avg_rate_var.set("0.00 KiB/s")
        self.ps_rate_var.set("0.00 KiB/s")
        self.ack_ok_var.set("0")
        self.timeout_count_var.set("0")
        self.retry_count_var.set("0")
        self.busy_count_var.set("0")
        self.error_count_var.set("0")
        self.sent_speed_chart.reset()
        self.ps_speed_chart.reset()
        self.rtt_chart.reset()

    def _on_done(self):
        self.send_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.sender = None
        self.sender_thread = None

    def _drain_event_queue(self):
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                self._handle_event(event_name, payload)
        except queue.Empty:
            pass

        self.root.after(100, self._drain_event_queue)

    def _handle_event(self, event_name: str, payload: dict):
        if event_name == "start":
            self.progress_text_var.set(f"0 / {payload['total_size']}")
            return

        if event_name == "chunk_sent":
            self.seq_var.set(str(payload["seq"]))
            self.status_text_var.set(f"发送 seq={payload['seq']} attempt={payload['attempt']}")
            self.window_used_var.set(str(payload.get("window_used", 0)))
            self._append_log(
                f"TX seq={payload['seq']} payload={payload['payload_len']}B attempt={payload['attempt']} "
                f"inflight={payload.get('window_used', 0)}"
            )
            return

        if event_name == "timeout":
            self.timeout_count_var.set(str(int(self.timeout_count_var.get()) + 1))
            self.status_text_var.set(f"Timeout seq={payload['seq']}")
            self.window_used_var.set(str(payload.get("window_used", 0)))
            self._append_log(
                f"Timeout seq={payload['seq']} payload={payload['payload_len']}B retry={payload['attempt']} "
                f"inflight={payload.get('window_used', 0)}"
            )
            return

        if event_name == "ack_status":
            stats = payload["stats"]
            self.ack_status_var.set(payload["status_name"])
            self.window_used_var.set(str(payload.get("window_used", 0)))
            self.retry_count_var.set(str(stats.retries_used))
            if payload["status_name"] == "BUSY":
                self.busy_count_var.set(str(stats.ack_busy))
            else:
                error_total = (
                    stats.ack_bad_magic + stats.ack_bad_length +
                    stats.ack_bad_checksum + stats.ack_dma_error
                )
                self.error_count_var.set(str(error_total))
            self.status_text_var.set(f"ACK {payload['status_name']} seq={payload['seq']}")
            self.rtt_var.set(f"{payload['rtt_ms']:.2f} ms")
            self._append_log(
                f"ACK {payload['status_name']} seq={payload['seq']} transfer_len={payload['transfer_len']} "
                f"rtt={payload['rtt_ms']:.2f}ms attempt={payload['attempt']} "
                f"inflight={payload.get('window_used', 0)}"
            )
            return

        if event_name == "ack_ok":
            stats = payload["stats"]
            progress = 0.0 if stats.total_size == 0 else (stats.bytes_sent / stats.total_size) * 100.0
            self.progress_var.set(progress)
            self.progress_text_var.set(f"{stats.bytes_sent} / {stats.total_size}")
            self.ack_status_var.set("OK")
            self.seq_var.set(str(payload["seq"]))
            self.window_used_var.set(str(payload.get("window_used", 0)))
            self.rtt_var.set(f"{stats.last_rtt_ms:.2f} ms")
            self.current_rate_var.set(f"{stats.current_rate_kib_s:.2f} KiB/s")
            self.avg_rate_var.set(f"{stats.average_rate_kib_s:.2f} KiB/s")
            self.ps_rate_var.set(f"{stats.estimated_ps_rate_kib_s:.2f} KiB/s")
            self.ack_ok_var.set(str(stats.ack_ok))
            self.timeout_count_var.set(str(stats.timeout_count))
            self.retry_count_var.set(str(stats.retries_used))
            self.busy_count_var.set(str(stats.ack_busy))
            error_total = (
                stats.ack_bad_magic + stats.ack_bad_length +
                stats.ack_bad_checksum + stats.ack_dma_error
            )
            self.error_count_var.set(str(error_total))
            self.status_text_var.set(f"ACK OK seq={payload['seq']}")
            self.sent_speed_chart.add_point(stats.current_rate_kib_s)
            self.ps_speed_chart.add_point(stats.estimated_ps_rate_kib_s)
            self.rtt_chart.add_point(stats.last_rtt_ms)
            self._append_log(
                f"ACK OK seq={payload['seq']} transfer_len={payload['transfer_len']} "
                f"progress={stats.bytes_sent}/{stats.total_size} "
                f"send={stats.current_rate_kib_s:.2f}KiB/s ps={stats.estimated_ps_rate_kib_s:.2f}KiB/s "
                f"rtt={stats.last_rtt_ms:.2f}ms inflight={payload.get('window_used', 0)}"
            )
            return

        if event_name == "done":
            stats = payload["stats"]
            self.status_text_var.set("发送完成")
            self._append_log(
                f"完成，总字节={stats.bytes_sent} avg={stats.average_rate_kib_s:.2f}KiB/s "
                f"ACK_OK={stats.ack_ok} timeout={stats.timeout_count}"
            )
            self._on_done()
            return

        if event_name == "stopped":
            self.status_text_var.set("已停止")
            self._append_log(f"已停止，已发送字节={payload['bytes_sent']}")
            self._on_done()
            return

        if event_name == "error":
            self.status_text_var.set("错误")
            self._append_log(f"错误：{payload['message']}")
            messagebox.showerror("发送失败", payload["message"])
            self._on_done()


def main():
    root = tk.Tk()
    SenderGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
