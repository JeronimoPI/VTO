import ctypes as C
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ndi_capture import NativeReceiver, Performance, ReceiverSettings, Source, VideoFrame
from ndi_video import read_bgr


class NativeCaptureTests(unittest.TestCase):
    def test_64bit_abi_matches_vendored_ndi_sdk_headers(self):
        if C.sizeof(C.c_void_p) != 8:
            self.skipTest('Desktop targets are 64-bit')
        self.assertEqual([C.sizeof(t) for t in [Source, ReceiverSettings, VideoFrame, Performance]], [16,40,72,24])
        self.assertEqual(ReceiverSettings.name.offset, 32)
        self.assertEqual(VideoFrame.data.offset, 40)
        self.assertEqual(VideoFrame.timestamp.offset, 64)

    def test_native_buffer_is_copied_before_releasing_sdk_frame(self):
        storage = (C.c_uint8 * 16)(255,0,0,255,255,0,0,255,255,0,0,255,255,0,0,255)
        video = VideoFrame()
        video.xres, video.yres = 2,2
        video.fourcc = int.from_bytes(b'RGBX','little')
        video.stride = 8
        video.data = C.cast(storage,C.POINTER(C.c_uint8))
        result = read_bgr(video)
        C.memset(storage,0,16)
        np.testing.assert_array_equal(result, np.full((2,2,3),[0,0,255],dtype=np.uint8))

    def test_video_is_freed_once_before_destroying_receiver(self):
        library = Mock()
        library.NDIlib_recv_create_v3.return_value = 42
        library.NDIlib_recv_capture_v2.side_effect = [1,0]
        with patch('ndi_capture.ndi_library', return_value=library):
            receiver = NativeReceiver('Test source')
            self.assertIsNotNone(receiver.capture_video())
            receiver.free_video()
            receiver.free_video()
            self.assertIsNone(receiver.capture_video())
            receiver.close()
            receiver.close()
        library.NDIlib_recv_free_video_v2.assert_called_once()
        library.NDIlib_recv_destroy.assert_called_once_with(42)
