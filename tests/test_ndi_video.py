from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

import app
from ndi_video import NDIReceiveError, read_bgr


class PaddedFrame:
    def __init__(self):
        self.xres, self.yres = 4, 2
        # Four red RGBX pixels plus padding on each row.
        self.data = np.array(([255, 0, 0, 255] * 4 + [33] * 4) * 2, dtype=np.uint8)

    def get_fourcc(self):
        return SimpleNamespace(name='RGBX')

    def get_line_stride(self):
        return 20

    def get_array(self):
        copy = self.data.copy()
        # A released SDK frame must no longer be used for its metadata.
        self.xres = self.yres = 0
        return copy


class NDIFrameTests(unittest.TestCase):
    def test_rgbx_padding_and_released_metadata(self):
        frame = read_bgr(PaddedFrame())
        self.assertEqual(frame.shape, (2, 4, 3))
        np.testing.assert_array_equal(frame, np.full((2, 4, 3), [0, 0, 255], dtype=np.uint8))

    def test_incomplete_frame_is_diagnosed(self):
        frame = PaddedFrame()
        frame.data = np.zeros(5, dtype=np.uint8)
        with self.assertRaises(NDIReceiveError) as caught:
            read_bgr(frame)
        self.assertEqual(caught.exception.code, 'NDI_FRAME_SIZE')

    def test_unsupported_format_is_diagnosed(self):
        frame = PaddedFrame()
        frame.get_fourcc = lambda: SimpleNamespace(name='P216')
        with self.assertRaises(NDIReceiveError) as caught:
            read_bgr(frame)
        self.assertEqual(caught.exception.code, 'NDI_PIXEL_FORMAT')


class NDIReceiverTests(unittest.TestCase):
    source = dict(id='ndi-regression', name='Local test source', kind='NDI', ndi_source=SimpleNamespace(valid=True))

    def test_framesync_video_reaches_jpeg_preview_and_disconnects(self):
        receiver = Mock()
        receiver.get_num_connections.return_value = 1
        video = PaddedFrame()
        # Each capture delivers new owned frame storage and valid metadata.
        receiver.frame_sync.capture_video.side_effect = lambda: video.__init__()
        with patch.object(app, 'NDI_READY', True), patch.object(app, 'Receiver', return_value=receiver), patch.object(app, 'VideoFrameSync', return_value=video):
            preview = app.Preview(self.source)
            try:
                deadline = time.monotonic() + 3
                while preview.frame is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertIsNotNone(preview.frame, preview.message)
                decoded = cv2.imdecode(np.frombuffer(preview.frame, dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertEqual(decoded.shape, (2, 4, 3))
                self.assertGreater(int(decoded[0, 0, 2]), 240)
                self.assertLess(int(decoded[0, 0, 0]), 10)
                self.assertEqual(preview.status()['ndi']['connections'], 1)
            finally:
                preview.close()
            receiver.frame_sync.set_video_frame.assert_called_once_with(video)
            receiver.disconnect.assert_called_once()
            self.assertFalse(preview.thread.is_alive())

    def test_connection_timeout_differs_from_video_timeout(self):
        for connections, code in [(0, 'NDI_CONNECT_TIMEOUT'), (1, 'NDI_VIDEO_TIMEOUT')]:
            with self.subTest(connections=connections):
                receiver = Mock()
                receiver.get_num_connections.return_value = connections
                with patch.object(app, 'NDI_READY', True), patch.object(app, 'Receiver', return_value=receiver), patch.object(app, 'VideoFrameSync'), patch.object(app, 'time', wraps=time) as clock:
                    clock.monotonic.side_effect = [0, 16]
                    preview = app.Preview(self.source)
                    try:
                        preview.thread.join(timeout=2)
                        self.assertEqual(preview.state, 'error')
                        self.assertEqual(preview.status()['error_code'], code)
                        self.assertIn(code, preview.message)
                        self.assertEqual(preview.status()['ndi']['connections'], connections)
                    finally:
                        preview.close()
                receiver.disconnect.assert_called_once()

    def test_unexpected_error_does_not_expose_arbitrary_exception_text(self):
        with patch.object(app, 'NDI_READY', True), patch.object(app, 'Receiver', side_effect=RuntimeError('rtsp://user:password@private-host/stream')):
            preview = app.Preview(self.source)
            preview.thread.join(timeout=2)
            self.assertEqual(preview.status()['error_code'], 'NDI_RECEIVE_ERROR')
            self.assertNotIn('password', str(preview.status()))
            preview.close()
