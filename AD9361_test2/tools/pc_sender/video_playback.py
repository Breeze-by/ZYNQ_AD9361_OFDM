#!/usr/bin/env python3
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from video_protocol import AIRV_FRAME_KEY


@dataclass
class VideoPlaybackResult:
    images: List[object] = field(default_factory=list)
    decoded_count: int = 0
    displayed_count: int = 0
    decoder_errors: int = 0
    waiting_keyframe: bool = False
    skipped_waiting_keyframe: bool = False
    error: str = ""


class VideoPreviewDecoder:
    def __init__(self):
        self.available = False
        self.unavailable_reason = ""
        self.decoded_frames = 0
        self.displayed_frames = 0
        self.decoder_errors = 0
        self.consecutive_errors = 0
        self.waiting_keyframe = True
        self._av = None
        self._codec = None

        try:
            import av
        except ImportError:
            self.unavailable_reason = (
                "PyAV is not installed for this Python; run "
                f"`{sys.executable} -m pip install av pillow` to enable AIRV preview"
            )
            return

        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.unavailable_reason = (
                "Pillow is not installed for this Python; run "
                f"`{sys.executable} -m pip install pillow` to display decoded AIRV frames"
            )
            return

        self._av = av
        self.available = True
        self._reset_decoder()

    def status_text(self) -> str:
        if self.available:
            return "Ready"
        return self.unavailable_reason or "AIRV preview decoder is unavailable"

    def _reset_decoder(self):
        if self._av is None:
            return
        self._codec = self._av.CodecContext.create("h264", "r")

    def wait_for_keyframe(self):
        self.waiting_keyframe = True
        self.consecutive_errors = 0
        self._reset_decoder()

    def decode(
        self,
        encoded_frame: bytes,
        *,
        frame_type: int,
        bad_fragment_crc: bool = False,
        bad_frame_crc: bool = False,
    ) -> VideoPlaybackResult:
        result = VideoPlaybackResult(
            decoder_errors=self.decoder_errors,
            waiting_keyframe=self.waiting_keyframe,
        )
        if not self.available:
            result.error = self.unavailable_reason
            return result

        if frame_type == AIRV_FRAME_KEY:
            if self.waiting_keyframe:
                self._reset_decoder()
            self.waiting_keyframe = False
        elif self.waiting_keyframe:
            result.skipped_waiting_keyframe = True
            return result

        try:
            packets = list(self._codec.parse(encoded_frame))
            if not packets:
                packets = [self._av.Packet(encoded_frame)]
            decoded = []
            for packet in packets:
                decoded.extend(self._codec.decode(packet))
        except Exception as exc:
            self.decoder_errors += 1
            self.consecutive_errors += 1
            if frame_type != AIRV_FRAME_KEY or self.consecutive_errors >= 3:
                self.waiting_keyframe = True
                self._reset_decoder()
            result.decoder_errors = self.decoder_errors
            result.waiting_keyframe = self.waiting_keyframe
            result.error = str(exc)
            return result

        images = []
        for frame in decoded:
            try:
                images.append(frame.to_image().convert("RGB"))
            except Exception as exc:
                self.decoder_errors += 1
                result.error = str(exc)

        if images:
            self.consecutive_errors = 0
            self.decoded_frames += len(images)
            self.displayed_frames += 1
            if bad_fragment_crc or bad_frame_crc:
                self.waiting_keyframe = False

        result.images = images
        result.decoded_count = self.decoded_frames
        result.displayed_count = self.displayed_frames
        result.decoder_errors = self.decoder_errors
        result.waiting_keyframe = self.waiting_keyframe
        return result
