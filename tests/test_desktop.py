import json
import time
import unittest
import urllib.request

import app
from desktop import DesktopServer


class DesktopLifecycleTests(unittest.TestCase):
    def test_private_server_plays_video_and_cleans_up_on_close(self):
        server = DesktopServer()
        server.start()
        preview_id = None
        try:
            self.assertTrue(server.url.startswith('http://127.0.0.1:'))
            with urllib.request.urlopen(server.url, timeout=5) as response:
                self.assertIn(b'Stream monitor', response.read())
            request = urllib.request.Request(server.url + '/api/preview',
                json.dumps({'source_id': app.DEMO['id']}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=5) as response:
                preview_id = json.load(response)['id']
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                with urllib.request.urlopen(server.url + '/api/preview/' + preview_id, timeout=5) as response:
                    state = json.load(response)
                if state['state'] in ('live', 'error'):
                    break
                time.sleep(.1)
            self.assertEqual(state['state'], 'live', state)
            with urllib.request.urlopen(server.url + '/api/preview/' + preview_id + '/video', timeout=5) as response:
                self.assertIn(b'\xff\xd8', response.read(1024))
            receiver_thread = app.current.thread
        finally:
            server.close()
        self.assertFalse(server.thread.is_alive())
        self.assertFalse(receiver_thread.is_alive())
        self.assertIsNone(app.current)
        self.assertIsNone(app.finder)
        self.assertIsNone(app.mdns)
        server.close()  # Closing again must be safe (GUI shutdown + atexit).
