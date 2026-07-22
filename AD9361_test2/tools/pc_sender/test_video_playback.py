#!/usr/bin/env python3
import unittest
from unittest import mock

from video_playback import VideoPreviewDecoder
from video_protocol import AIRV_FRAME_DELTA


class _FakeAv:
    @staticmethod
    def Packet(payload):
        return payload


class VideoPlaybackRecoveryTests(unittest.TestCase):
    def _decoder(self):
        decoder = object.__new__(VideoPreviewDecoder)
        decoder.available = True
        decoder.unavailable_reason = ""
        decoder.decoded_frames = 0
        decoder.displayed_frames = 0
        decoder.decoder_errors = 0
        decoder.consecutive_errors = 0
        decoder.waiting_keyframe = False
        decoder._av = _FakeAv()
        decoder._codec = mock.Mock()
        decoder._reset_decoder = mock.Mock()
        return decoder

    def test_single_delta_decode_error_does_not_wait_for_keyframe(self):
        decoder = self._decoder()
        decoder._codec.parse.side_effect = RuntimeError("damaged delta")

        result = decoder.decode(b"bad", frame_type=AIRV_FRAME_DELTA)

        self.assertTrue(result.error)
        self.assertFalse(result.waiting_keyframe)
        decoder._reset_decoder.assert_not_called()

    def test_three_consecutive_errors_trigger_keyframe_recovery(self):
        decoder = self._decoder()
        decoder._codec.parse.side_effect = RuntimeError("damaged delta")

        results = [
            decoder.decode(b"bad", frame_type=AIRV_FRAME_DELTA)
            for _ in range(VideoPreviewDecoder.MAX_CONSECUTIVE_ERRORS)
        ]

        self.assertFalse(results[0].waiting_keyframe)
        self.assertFalse(results[1].waiting_keyframe)
        self.assertTrue(results[2].waiting_keyframe)
        decoder._reset_decoder.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
