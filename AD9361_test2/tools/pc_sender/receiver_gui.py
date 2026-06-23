#!/usr/bin/env python3
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from receiver_core import (
    DEFAULT_BOARD_IP,
    DEFAULT_BOARD_PORT,
    DEFAULT_IDLE_FINISH_S,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RECEIVER_PORT,
    DEFAULT_SOCKET_BUFFER_BYTES,
    LoopbackReceiver,
    ReceiverConfig,
)
from sender_gui import Sparkline


class ReceiverGui:
    def __init__(self, root):
        self.root = root
        self.root.title("AD9361_test2 UDP Receiver")
        self.root.geometry("1040x720")
        self.root.minsize(960, 640)

        self.event_queue = queue.Queue()
        self.receiver_thread = None
        self.receiver = None
        self.last_summary_log_time = 0.0

        self.bind_ip_var = tk.StringVar(value="0.0.0.0")
        self.bind_port_var = tk.StringVar(value=str(DEFAULT_RECEIVER_PORT))
        self.board_ip_var = tk.StringVar(value=DEFAULT_BOARD_IP)
        self.board_port_var = tk.StringVar(value=str(DEFAULT_BOARD_PORT))
        self.register_var = tk.BooleanVar(value=True)
        self.socket_buffer_var = tk.StringVar(value=str(DEFAULT_SOCKET_BUFFER_BYTES))
        self.output_dir_var = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        self.output_name_var = tk.StringVar(value="")
        self.expected_bytes_var = tk.StringVar(value="0")
        self.idle_finish_var = tk.StringVar(value=str(DEFAULT_IDLE_FINISH_S))
        self.progress_ms_var = tk.StringVar(value="500")

        self.status_var = tk.StringVar(value="Idle")
        self.register_var_text = tk.StringVar(value="N/A")
        self.rx_bytes_var = tk.StringVar(value="0")
        self.highest_var = tk.StringVar(value="0")
        self.packet_var = tk.StringVar(value="0")
        self.block_var = tk.StringVar(value="0")
        self.rate_var = tk.StringVar(value="0.00 KiB/s")
        self.crc_var = tk.StringVar(value="0")
        self.len_var = tk.StringVar(value="0")
        self.gap_var = tk.StringVar(value="0")
        self.air_var = tk.StringVar(value="0")
        self.air_missing_var = tk.StringVar(value="0")
        self.air_error_var = tk.StringVar(value="0 / 0 / 0")
        self.file_crc_var = tk.StringVar(value="N/A")
        self.output_path_var = tk.StringVar(value="-")

        self.rate_chart = None
        self.packet_chart = None

        self._build_ui()
        self.root.after(100, self._drain_event_queue)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root_frame, text="AD9361_test2 Host Receiver",
            font=("Microsoft YaHei", 18, "bold")).pack(anchor=tk.W)

        split = ttk.Panedwindow(root_frame, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        left = ttk.Frame(split, padding=(0, 0, 8, 0))
        right = ttk.Frame(split, padding=(8, 0, 0, 0))
        split.add(left, weight=3)
        split.add(right, weight=2)

        self._build_config(left)
        self._build_metrics(right)
        self._build_charts(root_frame)
        self._build_log(root_frame)

    def _build_config(self, parent):
        net_box = ttk.LabelFrame(parent, text="Network", padding=12)
        net_box.pack(fill=tk.X)

        fields = [
            ("Bind IP", self.bind_ip_var),
            ("Bind Port", self.bind_port_var),
            ("Board IP", self.board_ip_var),
            ("Board Port", self.board_port_var),
            ("Socket Buffer", self.socket_buffer_var),
        ]
        for label_text, variable in fields:
            row = ttk.Frame(net_box)
            row.pack(fill=tk.X, pady=(0, 8))
            ttk.Label(row, text=label_text, width=14).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=variable, width=20).pack(side=tk.LEFT)

        ttk.Checkbutton(net_box, text="Register RX target", variable=self.register_var).pack(anchor=tk.W)

        output_box = ttk.LabelFrame(parent, text="Output", padding=12)
        output_box.pack(fill=tk.X, pady=(12, 0))

        row = ttk.Frame(output_box)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="Directory", width=14).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.output_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse", command=self._browse_output_dir).pack(side=tk.LEFT, padx=(8, 0))

        row = ttk.Frame(output_box)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="File Name", width=14).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.output_name_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row = ttk.Frame(output_box)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="Expected Bytes", width=14).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.expected_bytes_var, width=20).pack(side=tk.LEFT)

        row = ttk.Frame(output_box)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="Idle Finish(s)", width=14).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.idle_finish_var, width=20).pack(side=tk.LEFT)

        row = ttk.Frame(output_box)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Progress ms", width=14).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.progress_ms_var, width=20).pack(side=tk.LEFT)

        action_box = ttk.LabelFrame(parent, text="Control", padding=12)
        action_box.pack(fill=tk.X, pady=(12, 0))
        self.start_button = ttk.Button(action_box, text="Start", command=self._start_receiver)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(action_box, text="Stop", command=self._stop_receiver, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(action_box, text="Clear Log", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))

    def _build_metrics(self, parent):
        metrics_box = ttk.LabelFrame(parent, text="Metrics", padding=12)
        metrics_box.pack(fill=tk.BOTH, expand=True)

        metrics = [
            ("Status", self.status_var),
            ("Register", self.register_var_text),
            ("Contiguous", self.rx_bytes_var),
            ("Highest", self.highest_var),
            ("Packets", self.packet_var),
            ("Blocks", self.block_var),
            ("Rate", self.rate_var),
            ("CRC Errors", self.crc_var),
            ("Length Errors", self.len_var),
            ("Gaps", self.gap_var),
            ("AIR0 Packets", self.air_var),
            ("AIR0 Missing", self.air_missing_var),
            ("AIR0 Errors", self.air_error_var),
            ("File CRC", self.file_crc_var),
            ("Saved", self.output_path_var),
        ]
        for label_text, variable in metrics:
            row = ttk.Frame(metrics_box)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=label_text, width=14).pack(side=tk.LEFT)
            ttk.Label(row, textvariable=variable, font=("Consolas", 10),
                wraplength=300).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_charts(self, parent):
        chart_box = ttk.LabelFrame(parent, text="Charts", padding=12)
        chart_box.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        grid = ttk.Frame(chart_box)
        grid.pack(fill=tk.BOTH, expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)

        rate_frame = ttk.Frame(grid)
        rate_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(rate_frame, text="RX KiB/s").pack(anchor=tk.W)
        self.rate_chart = Sparkline(rate_frame, height=150, line_color="#2E7D32", unit="KiB/s")
        self.rate_chart.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        packet_frame = ttk.Frame(grid)
        packet_frame.grid(row=0, column=1, sticky="nsew")
        ttk.Label(packet_frame, text="Packets/s").pack(anchor=tk.W)
        self.packet_chart = Sparkline(packet_frame, height=150, line_color="#1976D2", unit="pkt/s")
        self.packet_chart.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

    def _build_log(self, parent):
        log_box = ttk.LabelFrame(parent, text="Event Log", padding=12)
        log_box.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_box, height=12, wrap="none")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y = ttk.Scrollbar(log_box, orient=tk.VERTICAL, command=self.log_text.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll_y.set)

    def _browse_output_dir(self):
        directory = filedialog.askdirectory(title="Select output directory")
        if directory:
            self.output_dir_var.set(directory)

    def _append_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _build_config_object(self) -> ReceiverConfig:
        progress_ms = int(self.progress_ms_var.get().strip())
        return ReceiverConfig(
            bind_ip=self.bind_ip_var.get().strip(),
            bind_port=int(self.bind_port_var.get().strip()),
            board_ip=self.board_ip_var.get().strip(),
            board_port=int(self.board_port_var.get().strip()),
            register_with_board=bool(self.register_var.get()),
            socket_buffer_bytes=int(self.socket_buffer_var.get().strip()),
            output_dir=self.output_dir_var.get().strip(),
            output_name=self.output_name_var.get().strip(),
            expected_bytes=int(self.expected_bytes_var.get().strip()),
            idle_finish_s=float(self.idle_finish_var.get().strip()),
            progress_interval_s=max(progress_ms, 50) / 1000.0,
        )

    def _start_receiver(self):
        try:
            config = self._build_config_object()
        except Exception as exc:
            messagebox.showerror("Parameter Error", str(exc))
            return

        self._reset_runtime_state()
        self.receiver = LoopbackReceiver(config)
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_var.set("Listening")
        self._append_log(
            f"Start bind={config.bind_ip}:{config.bind_port} board={config.board_ip}:{config.board_port} "
            f"register={config.register_with_board} expected={config.expected_bytes} output={config.output_dir}"
        )
        self.receiver_thread = threading.Thread(target=self._worker_run, daemon=True)
        self.receiver_thread.start()

    def _stop_receiver(self):
        if self.receiver is not None:
            self.receiver.stop()
            self.status_var.set("Stopping")
            self._append_log("Stop requested")

    def _worker_run(self):
        try:
            self.receiver.run(callback=self._receiver_callback)
        except Exception as exc:
            self.event_queue.put(("error", {"message": str(exc)}))

    def _receiver_callback(self, event_name: str, payload: dict):
        self.event_queue.put((event_name, payload))

    def _reset_runtime_state(self):
        self.register_var_text.set("N/A")
        self.rx_bytes_var.set("0")
        self.highest_var.set("0")
        self.packet_var.set("0")
        self.block_var.set("0")
        self.rate_var.set("0.00 KiB/s")
        self.crc_var.set("0")
        self.len_var.set("0")
        self.gap_var.set("0")
        self.air_var.set("0")
        self.air_missing_var.set("0")
        self.air_error_var.set("0 / 0 / 0")
        self.file_crc_var.set("N/A")
        self.output_path_var.set("-")
        self.rate_chart.reset()
        self.packet_chart.reset()
        self.last_summary_log_time = 0.0

    def _on_done(self):
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.receiver = None
        self.receiver_thread = None

    def _drain_event_queue(self):
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                self._handle_event(event_name, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_event_queue)

    def _update_stats(self, stats):
        self.rx_bytes_var.set(str(stats.contiguous_bytes))
        self.highest_var.set(str(stats.highest_end))
        self.packet_var.set(str(stats.packets))
        self.block_var.set(str(stats.blocks))
        self.rate_var.set(f"{stats.rate_kib_s:.2f} KiB/s")
        self.crc_var.set(str(stats.crc_errors))
        self.len_var.set(str(stats.length_errors))
        self.gap_var.set(str(stats.gap_count))
        self.air_var.set(
            f"{stats.air_packets}/{stats.air_total_packets}" if stats.air_mode else "off"
        )
        if stats.air_missing_ranges:
            self.air_missing_var.set(f"{stats.air_missing_packets} ({stats.air_missing_ranges})")
        else:
            self.air_missing_var.set(str(stats.air_missing_packets))
        self.air_error_var.set(
            f"{stats.air_bad_header} / {stats.air_bad_payload_crc} / {stats.air_duplicates}"
        )
        self.file_crc_var.set("OK" if stats.air_file_crc_ok else ("pending" if stats.air_mode else "N/A"))
        self.rate_chart.add_point(stats.rate_kib_s)
        self.packet_chart.add_point(stats.packet_rate_s)

    def _handle_event(self, event_name: str, payload: dict):
        if event_name == "start":
            self.status_var.set("Listening")
            return

        if event_name == "register_attempt":
            self.register_var_text.set(f"attempt {payload['attempt']}")
            return

        if event_name == "registered":
            self.register_var_text.set("OK")
            self._append_log(
                f"RX target registered at board {payload['board_ip']}:{payload['board_port']} "
                f"for port {payload['bind_port']}"
            )
            return

        if event_name == "progress":
            stats = payload["stats"]
            self._update_stats(stats)
            now = time.time()
            if now - self.last_summary_log_time >= 0.5:
                self.last_summary_log_time = now
                self._append_log(
                    f"PROGRESS rx={stats.contiguous_bytes} high={stats.highest_end} "
                    f"pkt={stats.packets} blk={stats.blocks} rate={stats.rate_kib_s:.2f}KiB/s "
                    f"crc={stats.crc_errors} len={stats.length_errors} gaps={stats.gap_count} "
                    f"air={int(stats.air_mode)} air_rx={stats.air_packets}/{stats.air_total_packets} "
                    f"miss={stats.air_missing_packets} bad_hdr={stats.air_bad_header} "
                    f"bad_payload={stats.air_bad_payload_crc} dup={stats.air_duplicates}"
                )
            return

        if event_name == "packet":
            stats = payload["stats"]
            self._update_stats(stats)
            if payload["status"] != "OK":
                self._append_log(
                    f"PACKET {payload['status']} block={payload['block_id']} "
                    f"off={payload['stream_offset']}+{payload['chunk_offset']} len={payload['payload_len']}"
                )
            return

        if event_name == "ack":
            self._append_log(f"ACK seq={payload['seq']} status={payload['status_name']}")
            return

        if event_name == "saved":
            stats = payload["stats"]
            self._update_stats(stats)
            self.output_path_var.set(payload["path"])
            self.status_var.set("Saved")
            self._append_log(f"SAVED {payload['path']}")
            return

        if event_name == "incomplete":
            stats = payload["stats"]
            self._update_stats(stats)
            self.status_var.set("Incomplete")
            missing_ranges = (
                f" missing_seq={stats.air_missing_ranges}"
                if stats.air_missing_ranges else ""
            )
            self._append_log(f"INCOMPLETE {payload['reason']}{missing_ranges}")
            return

        if event_name == "done":
            stats = payload["stats"]
            self._update_stats(stats)
            self.status_var.set("Done" if stats.saved_path else "Incomplete")
            missing_ranges = (
                f" missing_seq={stats.air_missing_ranges}"
                if stats.air_missing_ranges else ""
            )
            self._append_log(
                f"DONE rx={stats.contiguous_bytes} high={stats.highest_end} "
                f"pkt={stats.packets} blk={stats.blocks} gaps={stats.gap_count} "
                f"air={int(stats.air_mode)} air_rx={stats.air_packets}/{stats.air_total_packets} "
                f"miss={stats.air_missing_packets} bad_hdr={stats.air_bad_header} "
                f"bad_payload={stats.air_bad_payload_crc} dup={stats.air_duplicates} "
                f"file_crc={int(stats.air_file_crc_ok)} saved={stats.saved_path} "
                f"reason={stats.incomplete_reason}{missing_ranges}"
            )
            self._on_done()
            return

        if event_name == "unknown":
            self._append_log(f"UNKNOWN {payload}")
            return

        if event_name == "error":
            self.status_var.set("Error")
            self._append_log(f"ERROR {payload['message']}")
            messagebox.showerror("Receiver Failed", payload["message"])
            self._on_done()


def main():
    root = tk.Tk()
    ReceiverGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
