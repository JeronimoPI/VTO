from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

import app
from desktop import DesktopAPI, recording_close_guard
from media_runtime import ffmpeg_path
from recording import ClipRecorder, RecordingError


def jpeg(bgr):
    ok, frame = cv2.imencode('.jpg', np.full((36, 64, 3), bgr, dtype=np.uint8))
    assert ok
    return frame.tobytes()


RED, BLUE, GREEN = jpeg([0, 0, 255]), jpeg([255, 0, 0]), jpeg([0, 255, 0])


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 10.0
        self.recorder = ClipRecorder(self.root / 'clips', self.root / 'settings.json', clock=lambda: self.now)
        self.recorder.select_source('camera', 'Camera / Studio')

    def tearDown(self):
        self.recorder.shutdown()
        self.temp.cleanup()

    def fill_buffer(self):
        # Deliberately uneven capture cadence: the clip must use time, not count.
        stamp = 6.0
        for index in range(61):
            stamp += [.05, .09, .06][index % 3]
            if stamp >= 10:
                break
            self.recorder.push('camera', GREEN if stamp < 6.9 else RED, 64, 36, stamp)

    def test_actual_mp4_has_three_seconds_before_click_and_seven_after(self):
        self.fill_buffer()
        clip = self.recorder.trigger('camera')
        for index in range(105):
            self.recorder.push('camera', BLUE, 64, 36, 10 + index / 15)
        self.now = 17
        self.recorder.finish(clip['id'])
        worker = self.recorder.jobs[clip['id']].worker
        worker.join(timeout=15)
        result = self.recorder.status()['items'][0]
        self.assertEqual(result['state'], 'saved', result)
        path = Path(result['path'])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.root / 'clips')
        self.assertNotIn('/', result['filename'])
        self.assertFalse(list(path.parent.glob('*.partial.mp4')))
        capture = cv2.VideoCapture(str(path))
        try:
            self.assertTrue(capture.isOpened())
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT), 150)
            self.assertEqual(capture.get(cv2.CAP_PROP_FPS), 15)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS), 10)
            codec = int(capture.get(cv2.CAP_PROP_FOURCC))
            self.assertIn(''.join(chr((codec >> (8 * i)) & 255) for i in range(4)).lower(), ['avc1', 'h264'])
        finally:
            capture.release()
        data = subprocess.check_output([ffmpeg_path(), '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        pixels = np.frombuffer(data, dtype=np.uint8).reshape(150, 36, 64, 3)
        for index in [0, 44]:
            self.assertGreater(pixels[index, :, :, 0].mean(), 240, f'frame {index} must be pre-click red')
            self.assertLess(pixels[index, :, :, 2].mean(), 15)
        for index in [45, 149]:
            self.assertGreater(pixels[index, :, :, 2].mean(), 240, f'frame {index} must be post-click blue')
            self.assertLess(pixels[index, :, :, 0].mean(), 15)

    def test_warmup_and_stale_video_do_not_create_incomplete_clips(self):
        self.recorder.push('camera', RED, 64, 36, 9.9)
        with self.assertRaises(RecordingError):
            self.recorder.trigger('camera')
        self.fill_buffer()
        self.now = 12
        with self.assertRaises(RecordingError):
            self.recorder.trigger('camera')
        self.assertFalse(self.recorder.status()['items'])

    def test_source_change_double_click_and_folder_change_are_blocked_during_capture(self):
        self.fill_buffer()
        self.recorder.trigger('camera')
        for action in [lambda: self.recorder.select_source('other', 'Other'),
                       lambda: self.recorder.trigger('camera'),
                       lambda: self.recorder.set_directory(self.root)]:
            with self.assertRaises(RecordingError):
                action()
        self.assertEqual(self.recorder.source_id, 'camera')

    def test_signal_loss_and_shutdown_never_save_a_partial_clip(self):
        self.fill_buffer()
        self.recorder.trigger('camera')
        self.recorder.push('camera', BLUE, 64, 36, 11)
        self.assertEqual(self.recorder.status()['items'][0]['state'], 'error')
        self.assertFalse(list(self.root.rglob('*.mp4')))
        self.recorder.shutdown()
        self.assertFalse(self.recorder.buffer)

    def test_selected_folder_is_remembered_without_changing_the_buffer(self):
        self.fill_buffer()
        self.recorder.set_directory(self.root)
        self.assertTrue(self.recorder.status()['buffer']['ready'])
        restored = ClipRecorder(preferences=self.root / 'settings.json')
        self.assertEqual(restored.directory, self.root)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_folder_picker_uses_native_dialog_and_cancel_keeps_the_previous_folder(self):
        api = DesktopAPI()
        api._window = Mock()
        fake_webview = SimpleNamespace(FileDialog=SimpleNamespace(FOLDER='folder'))
        with patch.object(app, 'recordings', self.recorder), patch.dict('sys.modules', {'webview': fake_webview}):
            api._window.create_file_dialog.return_value = None
            self.assertTrue(api.choose_recording_folder()['cancelled'])
            self.assertEqual(self.recorder.directory, self.root / 'clips')
            api._window.create_file_dialog.return_value = (str(self.root),)
            self.assertEqual(api.choose_recording_folder()['folder'], str(self.root))
            self.assertTrue((self.root / 'settings.json').is_file())
            self.assertEqual(api._window.create_file_dialog.call_args.args[0], 'folder')

    def test_api_creates_clip_and_rejects_source_switch_until_postroll_finishes(self):
        self.fill_buffer()
        current = SimpleNamespace(id='camera', state='live', close=Mock())
        with patch.object(app, 'recordings', self.recorder), patch.object(app, 'current', current):
            client = app.app.test_client()
            result = client.post('/api/preview/camera/recordings')
            self.assertEqual(result.status_code, 202)
            self.assertEqual(result.json['duration'], 10)
            self.assertEqual(client.post('/api/preview/camera/recordings').status_code, 409)
            self.assertEqual(client.delete('/api/preview/camera').status_code, 409)
            self.assertEqual(client.post('/api/preview', json={'source_id': app.DEMO['id']}).status_code, 409)
            current.close.assert_not_called()
            self.assertEqual(client.get('/api/recordings').json['active']['state'], 'collecting')

    def test_write_failure_removes_partial_output(self):
        self.fill_buffer()
        clip = self.recorder.trigger('camera')
        for index in range(105):
            self.recorder.push('camera', BLUE, 64, 36, 10 + index / 15)
        self.now = 17
        with patch('recording.os.replace', side_effect=OSError('disk full')):
            self.recorder.finish(clip['id'])
            self.recorder.jobs[clip['id']].worker.join(timeout=15)
        self.assertEqual(self.recorder.status()['items'][0]['state'], 'error')
        self.assertFalse(list((self.root / 'clips').iterdir()))

    def test_close_guard_returns_before_waiting_for_native_confirmation(self):
        self.fill_buffer()
        self.recorder.trigger('camera')
        window = Mock()
        released = threading.Event()
        destroyed = threading.Event()
        window.create_confirmation_dialog.side_effect = lambda *_: released.wait(timeout=2)
        window.destroy.side_effect = destroyed.set
        guard = recording_close_guard(window)
        with patch.object(app, 'recordings', self.recorder):
            self.assertFalse(guard())
            self.assertFalse(guard())  # A second click must not open another dialog.
            released.set()
            self.assertTrue(destroyed.wait(timeout=2))
            self.assertTrue(guard())
        window.create_confirmation_dialog.assert_called_once()

    def test_native_50_60_and_100_fps_are_written_without_preview_resampling(self):
        for fps in [50, 60, 100]:
            with self.subTest(fps=fps):
                self.recorder.select_source('native', 'NDI camera', fps=None, native=True)
                self.recorder.configure_native('native', fps)
                for index in range(4 * fps):
                    stamp = 6 + index / fps
                    self.recorder.push('native', RED, 64, 36, stamp)
                clip = self.recorder.trigger('native')
                for index in range(7 * fps):
                    stamp = 10 + index / fps
                    self.recorder.push('native', BLUE, 64, 36, stamp)
                self.now = 17
                self.recorder.finish(clip['id'])
                self.recorder.jobs[clip['id']].worker.join(timeout=15)
                saved = self.recorder.status()['items'][0]
                self.assertEqual(saved['state'], 'saved', saved)
                capture = cv2.VideoCapture(saved['path'])
                try:
                    self.assertEqual(capture.get(cv2.CAP_PROP_FPS), fps)
                    self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT), fps * 10)
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 3 * fps - 1)
                    ok, red = capture.read()
                    self.assertTrue(ok)
                    self.assertGreater(red[:,:,2].mean(), 240)
                    ok, blue = capture.read()
                    self.assertTrue(ok)
                    self.assertGreater(blue[:,:,0].mean(), 240)
                finally:
                    capture.release()
                self.now = 10

    def test_missing_native_frames_are_not_filled_with_duplicates(self):
        self.recorder.select_source('native', 'NDI', fps=None, native=True)
        self.recorder.configure_native('native', 50)
        for index in range(200):
            self.recorder.push('native', RED, 64, 36, 6 + index / 50)
        clip = self.recorder.trigger('native')
        for index in range(349):  # One frame short; no interpolation is allowed.
            self.recorder.push('native', BLUE, 64, 36, 10 + index / 50)
        self.now = 17
        self.recorder.finish(clip['id'])
        self.recorder.jobs[clip['id']].worker.join(timeout=15)
        result = self.recorder.status()['items'][0]
        self.assertEqual(result['state'], 'error')
        self.assertIn('bronframes', result['message'])
        self.assertFalse(Path(result['path']).exists())
