import threading
import functools
import http.server
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_local_access_and_cross_site_protection(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/sources', json={'url': 'http://camera/live'}, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_source_validation_and_credentials_redaction(self):
        for url in ['file:///etc/passwd', 'http://', 'ftp://camera/file', 'rtsp://host:bad/stream', 'http://host/\nfoo']:
            self.assertEqual(self.client.post('/api/sources', json={'url': url}).status_code, 400, url)
        result = self.client.post('/api/sources', json={'url': 'rtsp://user:secret@camera.local:554/live', 'name': '<script>alert(1)</script>'})
        self.assertEqual(result.status_code, 201)
        self.assertNotIn('secret', result.get_data(as_text=True))
        self.assertEqual(result.json['source']['address'], 'camera.local:554')
        duplicate = self.client.post('/api/sources', json={'url': 'rtsp://user:secret@camera.local:554/live'})
        self.assertEqual(duplicate.json['source']['id'], result.json['source']['id'])

    def test_unknown_preview(self):
        self.assertEqual(self.client.post('/api/preview', json={'source_id':'missing'}).status_code, 404)
        self.assertEqual(self.client.get('/api/preview/missing').status_code, 404)


class ReceiverTests(unittest.TestCase):
    def wait_frame(self, preview, timeout=12):
        deadline = time.monotonic() + timeout
        while preview.frame is None and preview.state != 'error' and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertIsNotNone(preview.frame, preview.message)
        self.assertTrue(preview.frame.startswith(b'\xff\xd8'))
        self.assertGreater(preview.width, 0)

    def test_ffmpeg_demo_receives_frames_and_stops(self):
        preview = app.Preview(app.DEMO)
        try:
            self.wait_frame(preview)
            self.assertEqual((preview.width, preview.height), (1280,720))
            first = preview.sequence
            time.sleep(.4)
            self.assertGreater(preview.sequence, first)
            part = next(preview.frames())
            self.assertIn(b'Content-Type: image/jpeg', part)
        finally:
            preview.close()
        self.assertFalse(preview.thread.is_alive())
        self.assertEqual(preview.state, 'stopped')

    def test_failed_stream_reports_error(self):
        source = app.register('unreachable', 'HTTP', 'Handmatig', '127.0.0.1:1', url='http://127.0.0.1:1/missing')
        preview = app.Preview(source)
        try:
            preview.thread.join(timeout=8)
            self.assertEqual(preview.state, 'error')
            self.assertIsNone(preview.frame)
        finally:
            preview.close()

    def test_http_and_hls_video_reception(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([app.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15', '-t', '3', '-threads', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '15', '-f', 'hls', '-hls_time', '1', '-hls_list_size', '0', str(Path(directory) / 'live.m3u8')], check=True)
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                for path in ['live.m3u8', 'live0.ts']:
                    with self.subTest(path=path):
                        source = app.register('HTTP fixture', 'HTTP', 'Test', '127.0.0.1', url=f'http://127.0.0.1:{server.server_port}/{path}')
                        preview = app.Preview(source)
                        try:
                            self.wait_frame(preview)
                            self.assertEqual((preview.width, preview.height), (320, 180))
                        finally:
                            preview.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    @unittest.skipUnless(os.environ.get('VTO_TEST_RTSP_URL'), 'Opt-in: provide VTO_TEST_RTSP_URL for a real RTSP test source')
    def test_rtsp_video_reception(self):
        source = app.register('RTSP fixture', 'RTSP', 'Test', 'RTSP test source', url=os.environ['VTO_TEST_RTSP_URL'])
        preview = app.Preview(source)
        try:
            self.wait_frame(preview)
        finally:
            preview.close()

    @unittest.skipUnless(app.NDI_READY and os.environ.get('VTO_TEST_NDI') == '1', 'Opt-in: VTO_TEST_NDI=1; requires a working NDI/mDNS network and Avahi on Linux')
    def test_real_ndi_discovery_and_video_reception(self):
        import numpy as np
        from fractions import Fraction
        from cyndilib.sender import Sender
        from cyndilib.video_frame import VideoSendFrame
        from cyndilib.wrapper.ndi_structs import FourCC
        sender = Sender('VTO integration test', clock_video=False)
        frame = VideoSendFrame()
        frame.set_resolution(320, 180)
        frame.set_fourcc(FourCC.BGRX)
        frame.set_frame_rate(Fraction(15, 1))
        sender.set_video_frame(frame)
        sender.open()
        done = threading.Event()
        def send():
            pixels = np.full(180 * 320 * 4, 120, dtype=np.uint8)
            while not done.is_set():
                sender.write_video(pixels)
                done.wait(1/15)
        worker = threading.Thread(target=send)
        worker.start()
        preview = None
        try:
            deadline = time.monotonic() + 12
            found = None
            while time.monotonic() < deadline:
                for source in app.scan():
                    if 'VTO integration test' in source['name']:
                        found = app.sources[source['id']]
                if found:
                    break
            self.assertIsNotNone(found, 'Local NDI sender was not discovered')
            preview = app.Preview(found)
            self.wait_frame(preview)
            self.assertEqual((preview.width, preview.height), (320,180))
        finally:
            if preview:
                preview.close()
            done.set()
            worker.join()
            sender.close()


if __name__ == '__main__':
    unittest.main()
