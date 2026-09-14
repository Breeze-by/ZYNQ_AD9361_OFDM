"""Measured weak-payload time-domain SNR, not BER/RSSI-derived SNR.

The receiver PL supplies unscaled I/Q moments; the PS keeps an explicitly
calibrated quiet reference. The PC subtracts DC and noise in LINEAR power.
Only detected BPSK 1/2 packets contribute; this is not Eb/N0 or calibrated RF
input power. The payload time windows include OFDM pilots, not just data bins.
"""
import binascii
import math
import secrets
import socket
import struct
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

REQUEST_MAGIC = 0x51524E53
RESPONSE_MAGIC = 0x31524E53
QUIET_CONFIRM = 0x51554945
MASK64 = (1 << 64) - 1


def crc32(data):
    return binascii.crc32(data) & 0xFFFFFFFF


def signed64(value):
    return value - (1 << 64) if value & (1 << 63) else value


@dataclass(frozen=True)
class Moments:
    count: int
    power: int
    i: int
    q: int
    clips: int = 0

    @classmethod
    def from_words(cls, words):
        pair = lambda n: words[n] | (words[n + 1] << 32)
        return cls(pair(0), pair(2), signed64(pair(4)), signed64(pair(6)), words[8])

    def variance(self):
        if self.count <= 0:
            return None
        return self.power / self.count - (self.i / self.count) ** 2 - (self.q / self.count) ** 2

    def delta(self, earlier):
        return Moments((self.count - earlier.count) & MASK64,
                       (self.power - earlier.power) & MASK64,
                       signed64((self.i - earlier.i) & MASK64),
                       signed64((self.q - earlier.q) & MASK64),
                       (self.clips - earlier.clips) & 0xFFFFFFFF)


@dataclass(frozen=True)
class Telemetry:
    request_id: int
    flags: int
    epoch: int
    noise_age_ms: int
    context: tuple
    sequence: int
    signal: Moments
    noise: Moments
    ticks: int

    def reason(self):
        if not self.flags & 1:
            return "Board lacks SNR measurement hardware"
        if self.flags & 4:
            return "Quiet noise calibration in progress; keep Sender stopped"
        reasons = ((8, "Traffic detected during noise calibration; recalibrate"),
                   (16, "Noise measurement clipped; check gain and recalibrate"),
                   (32, "RF gain/mode/bandwidth/LO/config changed; recalibrate"),
                   (64, "Invalid hardware snapshot or insufficient noise samples"),
                   (128, "SNR control request rejected"),
                   (512, "Noise reference expired (30 min); recalibrate"))
        for bit, message in reasons:
            if self.flags & bit:
                return message
        if not self.flags & 2:
            return "Calibrate SNR noise with Sender stopped"
        return ""


def parse_response(data, request_id):
    if len(data) != 260:
        raise ValueError("SNR telemetry length mismatch")
    words = struct.unpack('<65I', data)
    if words[0] != RESPONSE_MAGIC or words[1] != 1 or words[15] != 1:
        raise ValueError("Unsupported SNR telemetry version/method")
    if words[2] != request_id or words[64] != crc32(data[:256]):
        raise ValueError("SNR telemetry request ID/CRC mismatch")
    if any(words[44:64]) or words[14] or words[3] & ~0x2FF:
        raise ValueError("Unsupported SNR telemetry fields")
    return Telemetry(words[2], words[3], words[4], words[5], tuple(words[6:13]),
                     words[13], Moments.from_words(words[16:30]),
                     Moments.from_words(words[30:44]), words[28] | (words[29] << 32))


class SNRClient:
    def __init__(self, bind_ip, board_ip, board_port, timeout=0.5):
        self.peer = (socket.gethostbyname(board_ip), int(board_port))
        self.timeout = timeout
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((bind_ip, 0))  # Never steals the video RXCFG target.
        except Exception:
            self.sock.close()
            raise

    def close(self):
        self.sock.close()

    def request(self, operation=0):
        request_id = secrets.randbits(32)
        body = struct.pack('<4I', REQUEST_MAGIC, request_id, operation,
                           QUIET_CONFIRM if operation == 1 else 0)
        self.sock.sendto(body + struct.pack('<I', crc32(body)), self.peer)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No SNR telemetry response; check new receiver bit/ELF")
            self.sock.settimeout(remaining)
            data, peer = self.sock.recvfrom(1024)
            if peer != self.peer:
                continue
            try:
                return parse_response(data, request_id)
            except ValueError:
                continue  # Ignore corrupt, stale or unrelated UDP replies.

    def calibrate(self, stop_event):
        probe = self.request()
        if not probe.flags & 1:
            raise ValueError(probe.reason())
        result = self.request(1)
        deadline = time.monotonic() + 4
        while result.flags & 4:
            if stop_event.wait(0.05):
                raise ValueError("Noise calibration cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Noise calibration timed out")
            result = self.request()
        if result.reason():
            raise ValueError(result.reason())
        if result.noise.variance() is None or result.noise.variance() <= 0:
            raise ValueError("Non-positive measured noise power; calibration invalid")
        return result


@dataclass(frozen=True)
class SNRPoint:
    timestamp: float
    db: Optional[float] = None
    status: str = "Waiting for SNR telemetry"
    signal_plus_noise: Optional[float] = None
    noise_power: Optional[float] = None
    samples: int = 0
    noise_age_ms: int = 0


class SNRTracker:
    """Last ~1 s, in 250 ms telemetry intervals, weighted by I/Q sample count."""
    def __init__(self):
        self.previous = None
        self.samples = deque()

    def observe(self, telemetry, now=None):
        now = time.monotonic() if now is None else now
        reason = telemetry.reason()
        previous = self.previous
        self.previous = telemetry
        if reason:
            self.samples.clear()
            return SNRPoint(now, status=reason)
        same = previous is not None and previous.epoch == telemetry.epoch and previous.context == telemetry.context
        if not same or previous.reason():
            self.samples.clear()
            return SNRPoint(now, status="Noise calibrated; waiting for new weak payload samples")
        if telemetry.ticks <= previous.ticks:
            self.samples.clear()
            return SNRPoint(now, status="Repeated/reset hardware snapshot")
        elapsed = (telemetry.ticks - previous.ticks) / 100000000.0
        delta = telemetry.signal.delta(previous.signal)
        if elapsed > 1.5 or delta.count > elapsed * 100000000 + 1024:
            self.samples.clear()
            return SNRPoint(now, status="Telemetry gap/counter reset; waiting for fresh interval")
        self.samples.append((now, delta))
        while self.samples and self.samples[0][0] <= now - 1:
            self.samples.popleft()
        total = Moments(*(sum(getattr(sample, field) for _, sample in self.samples)
                          for field in ('count', 'power', 'i', 'q', 'clips')))
        noise = telemetry.noise.variance()
        received = total.variance()
        info = dict(timestamp=now, signal_plus_noise=received, noise_power=noise,
                    samples=total.count, noise_age_ms=telemetry.noise_age_ms)
        if total.count < 4096:
            return SNRPoint(**info, status="No/small weak payload sample window")
        if total.clips or telemetry.noise.clips:
            return SNRPoint(**info, status="Measurement point clipped; SNR invalid")
        if noise is None or noise <= 0 or received is None or received <= noise:
            return SNRPoint(**info, status="Measured power <= noise floor; SNR unresolved")
        db = 10 * math.log10((received - noise) / noise)
        return SNRPoint(**info, db=db, status="Measured weak DATA I/Q; ~1s, quiet-noise reference")


def monitor(bind_ip, board_ip, board_port, stop_event, callback):
    """Separate control socket/thread so polling cannot block video reception."""
    client = None
    tracker = SNRTracker()
    failures = 0
    try:
        client = SNRClient(bind_ip, board_ip, board_port)
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                telemetry = client.request()
                failures = 0
                callback(tracker.observe(telemetry))
                if not telemetry.flags & 1:
                    break
            except (OSError, ValueError) as exc:
                callback(SNRPoint(time.monotonic(), status=str(exc)))
                failures += 1
                if failures >= 2:
                    break  # Old firmware: do not spam unknown control commands.
            if stop_event.wait(max(0, 0.25 - (time.monotonic() - started))):
                break
    except (OSError, ValueError) as exc:
        callback(SNRPoint(time.monotonic(), status=str(exc)))
    finally:
        if client is not None:
            client.close()
