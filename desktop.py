"""Desktop entry point. The web UI lives inside a native system webview."""
import multiprocessing
import sys
import threading

from werkzeug.serving import make_server

import app as backend
from recording import RecordingError


class DesktopAPI:
    def __init__(self):
        self._window = None
        self._picker_lock = threading.Lock()

    def choose_recording_folder(self):
        import webview

        with self._picker_lock:
            if backend.recordings.is_busy():
                return dict(error='Wacht tot de huidige clip is opgeslagen.')
            folder = backend.recordings.directory
            try:
                selected = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                    directory=str(folder if folder.is_dir() else folder.parent), allow_multiple=False)
                if not selected:
                    return dict(cancelled=True)
                return dict(folder=backend.recordings.set_directory(selected[0]))
            except (OSError, RecordingError):
                return dict(error='Deze map kon niet worden gekozen of onthouden. Controleer de schrijfrechten.')


def recording_close_guard(window):
    allowed = threading.Event()
    prompting = threading.Lock()

    def on_closing():
        if allowed.is_set() or not backend.recordings.is_busy():
            return True
        # Closing callbacks run on the GUI thread on macOS. Its native dialog
        # marshals back to that thread, so never wait for it in this callback.
        if prompting.acquire(blocking=False):
            def confirm():
                try:
                    if window.create_confirmation_dialog('Opname nog niet opgeslagen',
                            'Er wordt nog een clip gemaakt. Wil je VTO afsluiten en deze opname afbreken?'):
                        allowed.set()
                        window.destroy()
                finally:
                    prompting.release()
            threading.Thread(target=confirm, daemon=True).start()
        return False

    return on_closing


class DesktopServer:
    def __init__(self):
        # Port 0 asks the OS for a free port, so multiple launches cannot collide.
        self.server = make_server('127.0.0.1', 0, backend.app, threaded=True)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.started = False

    def start(self):
        backend.init_discovery()
        self.thread.start()
        self.started = True

    def close(self):
        if self.started:
            self.server.shutdown()
            self.thread.join(timeout=5)
            self.started = False
        backend.cleanup()
        self.server.server_close()


def main():
    import webview

    server = DesktopServer()
    try:
        server.start()
        api = DesktopAPI()
        window = webview.create_window('VTO — Stream monitor', server.url, width=1320, height=960,
                              min_size=(840, 640), background_color='#101214', js_api=api)
        api._window = window

        window.events.closing += recording_close_guard(window)
        # pywebview uses WKWebView on macOS and WebView2 on Windows.
        # The GUI event loop must stay on the main thread.
        webview.start(debug=False)
    finally:
        server.close()


def smoke_test():
    """Verify a built bundle without requiring a monitor or a network camera."""
    import json
    import time
    import urllib.request

    if not backend.NDI_READY:
        raise RuntimeError('The bundled NDI binding could not be loaded')
    from ndi_capture import NativeReceiver
    probe = NativeReceiver('')
    probe.close()
    server = DesktopServer()
    try:
        server.start()
        with urllib.request.urlopen(server.url, timeout=5) as response:
            if b'Stream monitor' not in response.read():
                raise RuntimeError('Bundled template is missing')
        for asset in ['/static/app.js', '/static/style.css']:
            with urllib.request.urlopen(server.url + asset, timeout=5) as response:
                if not response.read():
                    raise RuntimeError('Bundled static asset is empty')
        req = urllib.request.Request(server.url + '/api/preview',
            json.dumps({'source_id': backend.DEMO['id']}).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            preview_id = json.load(response)['id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with urllib.request.urlopen(server.url + '/api/preview/' + preview_id, timeout=5) as response:
                state = json.load(response)
            if state['state'] == 'live':
                with urllib.request.urlopen(server.url + '/api/preview/' + preview_id + '/video', timeout=5) as response:
                    if b'\xff\xd8' not in response.read(1024):
                        raise RuntimeError('Invalid bundled video response')
                return
            if state['state'] == 'error':
                break
            time.sleep(.1)
        raise RuntimeError('Bundled FFmpeg did not produce video')
    finally:
        server.close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--smoke-test' in sys.argv:
        smoke_test()
    else:
        main()
