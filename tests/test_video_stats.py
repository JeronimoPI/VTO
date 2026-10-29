from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from video_stats import QUALITY_PROFILES, VideoStats, ndi_metadata, resize_preview


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.stats = VideoStats(clock=lambda: self.now)
        self.receiver = Mock()

    def sample(self, received, dropped):
        self.receiver.get_performance_data.return_value = dict(video=dict(frames_total=received, frames_dropped=dropped))
        return self.stats.poll_sdk(self.receiver)

    def test_sdk_counters_and_measured_fps_are_not_the_preview_rate(self):
        self.sample(100, 2)
        self.now = 2
        self.sample(200, 5)
        for index in range(30):
            self.stats.published(index / 15)
        value = self.stats.snapshot()
        self.assertEqual(value['sdk']['received'], 200)
        self.assertEqual(value['sdk']['dropped'], 5)
        self.assertEqual(value['sdk']['recent_drops'], 3)
        self.assertEqual(value['sdk']['fps'], 50)
        self.assertLess(value['processing_fps'], 16)

    def test_missing_or_stale_counters_are_unknown_not_zero_loss(self):
        self.receiver.get_performance_data.side_effect = RuntimeError('Unavailable')
        self.stats.poll_sdk(self.receiver)
        self.assertFalse(self.stats.snapshot()['sdk']['available'])
        self.assertIsNone(self.stats.snapshot()['sdk']['dropped'])
        self.receiver.get_performance_data.side_effect = None
        self.now = 1
        self.sample(100, 0)
        self.now = 5
        self.assertFalse(self.stats.snapshot()['sdk']['available'])
        self.assertIsNone(self.stats.snapshot()['sdk']['dropped'])

    def test_sdk_counter_reset_starts_new_baseline(self):
        self.sample(100, 4)
        self.now = 1
        self.sample(5, 0)
        value = self.stats.snapshot()['sdk']
        self.assertIsNone(value['fps'])
        self.assertIsNone(value['recent_drops'])
        self.assertEqual(value['received'], 5)

    def test_signal_metadata_describes_source_before_preview_resize(self):
        video = SimpleNamespace(xres=1920, yres=1080, get_frame_rate=lambda: Fraction(50, 1),
            get_fourcc=lambda: SimpleNamespace(name='RGBX'), frame_format=SimpleNamespace(name='progressive'))
        self.stats.set_input(ndi_metadata(video))
        preview = resize_preview(np.zeros((1080,1920,3), dtype=np.uint8), QUALITY_PROFILES['balanced'])
        self.assertEqual(preview.shape[:2], (720,1280))
        self.assertEqual(self.stats.snapshot()['input']['fps'], 50)
        self.assertEqual(self.stats.snapshot()['input']['width'], 1920)

    def test_preview_never_upscales_smaller_sources(self):
        frame = np.zeros((180,320,3), dtype=np.uint8)
        self.assertIs(resize_preview(frame, QUALITY_PROFILES['sharp']), frame)
