"""Local network video monitor. Run on the machine connected to your sources."""
import atexit
import ipaddress
import os
import queue
import sys
import subprocess
import threading
import time
import uuid
from urllib.parse import urlsplit

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, render_template, request
from media_runtime import ffmpeg_path, trusted_ca_file
from ndi_video import NDIReceiveError, read_bgr

try:
    from cyndilib.finder import Finder
    from cyndilib.receiver import Receiver
    from cyndilib.video_frame import VideoFrameSync
    from cyndilib.wrapper.ndi_recv import RecvBandwidth, RecvColorFormat
    NDI_READY = True
except (ImportError, OSError, RuntimeError):
    NDI_READY = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8192
sources = {}
sources_lock = threading.RLock()
scan_lock = threading.Lock()
control_lock = threading.Lock()
finder = None
current = None
mdns = None
browser = None


def public(source):
    return {k: source[k] for k in ('id', 'name', 'kind', 'origin', 'address')}


def register(name, kind, origin, address, **private):
    with sources_lock:
        for source in sources.values():
            if source['kind'] == kind and ((kind == 'NDI' and source['name'] == name) or (kind != 'NDI' and source.get('url', source['address']) == private.get('url', address))):
                return source
        source = dict(id=uuid.uuid4().hex, name=name, kind=kind, origin=origin, address=address, **private)
        sources[source['id']] = source
        return source


DEMO = register('VTO testbeeld', 'DEMO', 'Testbron', 'Intern gegenereerd · geen netwerkfeed')


class Discovery:
    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name, timeout=1500)
        if not info:
            return
        addresses = info.parsed_scoped_addresses()
        if not addresses:
            return
        host = addresses[0]
        if ':' in host:
            host = f'[{host}]'
        path = info.properties.get(b'path', b'/').decode(errors='replace')
        path = '/' + path.lstrip('/')
        url = f'rtsp://{host}:{info.port}{path}'
        register(name.removesuffix('._rtsp._tcp.local.'), 'RTSP', 'Netwerk · mDNS', f'{host}:{info.port}', url=url, service=name)

    update_service = add_service

    def remove_service(self, zc, type_, name):
        with sources_lock:
            for key in [k for k, s in sources.items() if s.get('service') == name]:
                del sources[key]


def init_discovery():
    global mdns, browser
    try:
        from zeroconf import Zeroconf, ServiceBrowser
        mdns = Zeroconf()
        browser = ServiceBrowser(mdns, '_rtsp._tcp.local.', Discovery())
    except (OSError, RuntimeError):
        app.logger.warning('mDNS unavailable; manual URLs remain available.')


def scan():
    global finder
    with scan_lock:
        if NDI_READY:
            if finder is None:
                finder = Finder()
                finder.open()
            if finder is not None:
                finder.wait(1.5)
                found = list(finder.iter_sources())
                with sources_lock:
                    names = {s.name for s in found}
                    for key in [k for k, s in sources.items() if s['kind'] == 'NDI' and s['name'] not in names]:
                        del sources[key]
                    for source in found:
                        registered = register(source.name, 'NDI', 'Netwerk · NDI', source.host_name or 'NDI', ndi_source=source)
                        registered['ndi_source'] = source
    with sources_lock:
        return [public(s) for s in sources.values()]


class Preview:
    def __init__(self, source):
        self.id = uuid.uuid4().hex
        self.source = source
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.frame = None
        self.sequence = 0
        self.state = 'connecting'
        self.message = 'Verbinding maken met de bron…'
        self.width = self.height = 0
        self.last_frame = time.monotonic()
        self.error_code = None
        self.ndi_stage = 'initialiseren'
        self.ndi_connections = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def publish(self, jpeg, width, height):
        with self.condition:
            self.frame = jpeg
            self.sequence += 1
            self.width, self.height = width, height
            self.last_frame = time.monotonic()
            self.state, self.message = 'live', 'Beeld wordt ontvangen'
            self.condition.notify_all()

    def run(self):
        try:
            if self.source['kind'] == 'NDI':
                self.receive_ndi()
            else:
                self.receive_ffmpeg()
        except Exception as exc:
            self.state = 'error'
            if self.source['kind'] == 'NDI':
                self.error_code = exc.code if isinstance(exc, NDIReceiveError) else 'NDI_RECEIVE_ERROR'
                if isinstance(exc, NDIReceiveError):
                    self.message = f'{exc} ({self.error_code})'
                else:
                    self.message = f'NDI-ontvangst mislukt tijdens {self.ndi_stage} ({type(exc).__name__}, {self.error_code}).'
                # Never log arbitrary exception text that could contain URLs.
                app.logger.warning('NDI preview failed: code=%s stage=%s exception=%s',
                                   self.error_code, self.ndi_stage, type(exc).__name__)
            else:
                app.logger.warning('Preview failed for source %s', self.source['id'])
                self.message = 'Geen beeld ontvangen. Controleer het adres, de toegangsgegevens en de netwerkverbinding.'
        finally:
            if self.stop.is_set():
                self.state, self.message = 'stopped', 'Weergave gestopt'
            elif self.state != 'error':
                self.state, self.message = 'error', 'De bron heeft de verbinding beëindigd.'
            with self.condition:
                self.condition.notify_all()

    def receive_ffmpeg(self):
        executable = ffmpeg_path()
        if not executable:
            raise RuntimeError('FFmpeg is not installed')
        args = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin']
        if self.source['kind'] == 'DEMO':
            args += ['-re', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=15']
        else:
            args += ['-protocol_whitelist', 'http,https,tcp,tls,rtsp,rtp,udp,crypto']
            if self.source['kind'] == 'RTSP':
                args += ['-rtsp_transport', 'tcp', '-timeout', '10000000']
            else:
                args += ['-rw_timeout', '10000000']
            if urlsplit(self.source['url']).scheme in ('https', 'rtsps'):
                args += ['-tls_verify', '1']
                ca_file = trusted_ca_file()
                if ca_file:
                    args += ['-ca_file', ca_file]
            args += ['-i', self.source['url']]
        args += ['-an', '-vf', "fps=15,scale='min(1280,iw)':-2", '-threads', '2', '-q:v', '5', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
        # Do not log stderr: FFmpeg may include URL credentials in diagnostics.
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        chunks = queue.Queue(maxsize=8)
        reader_stop = threading.Event()

        def read_pipe():
            # Windows select() cannot watch subprocess pipes. A bounded queue
            # keeps reading portable and lets the receiver enforce its deadline.
            try:
                while not reader_stop.is_set():
                    chunk = process.stdout.read(65536)
                    while not reader_stop.is_set():
                        try:
                            chunks.put(chunk or None, timeout=.2)
                            break
                        except queue.Full:
                            pass
                    if not chunk:
                        return
            except (OSError, ValueError):
                return

        reader = threading.Thread(target=read_pipe, daemon=True)
        reader.start()
        buffer = bytearray()
        try:
            while not self.stop.is_set():
                if time.monotonic() - self.last_frame > 15:
                    raise TimeoutError('No video frames')
                try:
                    chunk = chunks.get(timeout=.25)
                except queue.Empty:
                    continue
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > 16 * 1024 * 1024:
                    raise ValueError('Frame too large')
                while True:
                    start, end = buffer.find(b'\xff\xd8'), buffer.find(b'\xff\xd9')
                    if start < 0 or end < start:
                        break
                    jpeg = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if decoded is not None:
                        self.publish(jpeg, decoded.shape[1], decoded.shape[0])
        finally:
            reader_stop.set()
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join(timeout=2)
            process.stdout.close()

    def receive_ndi(self):
        if not NDI_READY:
            raise NDIReceiveError('NDI_RUNTIME', 'De NDI-runtime kon niet worden geladen.')
        # Follow cyndilib's viewer example: let the NDI FrameSync receiver
        # produce display frames at the preview cadence, independently of the
        # sender's cadence (e.g. the user's 1080/50p Test Patterns source).
        receiver = Receiver(color_format=RecvColorFormat.RGBX_RGBA,
                            bandwidth=RecvBandwidth.highest, allow_video_fields=False,
                            recv_name='VTO preview')
        try:
            video = VideoFrameSync()
            receiver.frame_sync.set_video_frame(video)
            self.ndi_stage = 'verbinden'
            source = self.source['ndi_source']
            if not source.valid and not source.update():
                raise NDIReceiveError('NDI_SOURCE_LOST', 'De NDI-bron is niet meer beschikbaar. Zoek opnieuw.')
            receiver.set_source(source)
            while not self.stop.is_set():
                self.ndi_connections = receiver.get_num_connections()
                if time.monotonic() - self.last_frame > 15:
                    if not self.ndi_connections:
                        raise NDIReceiveError('NDI_CONNECT_TIMEOUT', 'NDI-bron gevonden, maar de videoverbinding komt niet tot stand binnen 15 seconden.')
                    raise NDIReceiveError('NDI_VIDEO_TIMEOUT', 'De NDI-verbinding is actief, maar de bron levert binnen 15 seconden geen videoframe.')
                if not self.ndi_connections:
                    self.ndi_stage = 'verbinden'
                    self.stop.wait(.1)
                    continue
                self.ndi_stage = 'beeld ontvangen'
                receiver.frame_sync.capture_video()
                self.ndi_stage = 'beeld omzetten'
                frame = read_bgr(video)
                if frame is not None:
                    if frame.shape[1] > 1280:
                        frame = cv2.resize(frame, (1280, round(frame.shape[0] * 1280 / frame.shape[1])))
                    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        self.publish(encoded.tobytes(), frame.shape[1], frame.shape[0])
                self.stop.wait(1 / 15)
        finally:
            receiver.disconnect()

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=3)

    def status(self):
        extra = dict(error_code=self.error_code)
        if self.source['kind'] == 'NDI':
            extra['ndi'] = dict(stage=self.ndi_stage, connections=self.ndi_connections)
        if self.state == 'live' and time.monotonic() - self.last_frame > 3:
            return dict(state='buffering', message='Wachten op nieuw beeld…', width=self.width, height=self.height, **extra)
        return dict(state=self.state, message=self.message, width=self.width, height=self.height, **extra)

    def frames(self):
        sequence = -1
        while not self.stop.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.sequence != sequence or self.state in ('error', 'stopped') or self.stop.is_set(), timeout=2)
                if self.state in ('error', 'stopped') or self.stop.is_set():
                    return
                if self.frame is None or sequence == self.sequence:
                    continue
                frame, sequence = self.frame, self.sequence
            yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n'


@app.before_request
def local_only():
    # Loopback binding plus Host/Origin checks prevent DNS rebinding and cross-site control.
    hostname = urlsplit('http://' + request.host).hostname
    try:
        allowed = hostname == 'localhost' or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        abort(403)
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        abort(403)
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/sources')
def list_sources():
    return jsonify(sources=scan(), ndi=bool(NDI_READY), ffmpeg=bool(ffmpeg_path()), mdns=mdns is not None, ndi_discovery_warning=(sys.platform.startswith('linux') and not os.path.exists('/run/dbus/system_bus_socket')))


@app.post('/api/sources')
def add_source():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Verwacht een JSON-object.'), 400
    url, name = data.get('url', ''), data.get('name', '')
    if not isinstance(url, str) or not isinstance(name, str):
        return jsonify(error='Vul een geldig adres en een naam in.'), 400
    url, name = url.strip(), name.strip()
    try:
        parts = urlsplit(url)
        if len(url) > 2048 or parts.scheme not in ('rtsp', 'rtsps', 'http', 'https') or not parts.hostname or parts.fragment or any(ord(c) < 33 for c in url):
            raise ValueError()
        port = parts.port
    except ValueError:
        return jsonify(error='Gebruik een geldig rtsp://, rtsps://, http:// of https:// adres.'), 400
    with sources_lock:
        if len(sources) >= 100:
            return jsonify(error='Maximaal 100 bronnen. Herstart de app om handmatige bronnen te wissen.'), 400
    source = register(name[:100] or parts.hostname, 'RTSP' if parts.scheme.startswith('rtsp') else 'HTTP', 'Handmatig', parts.hostname + (f':{port}' if port else ''), url=url)
    return jsonify(source=public(source)), 201


@app.post('/api/preview')
def start_preview():
    global current
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Verwacht een JSON-object.'), 400
    source_id = data.get('source_id')
    if not isinstance(source_id, str):
        return jsonify(error='Selecteer een bron.'), 400
    with sources_lock:
        source = sources.get(source_id)
    if source is None:
        return jsonify(error='Deze bron is niet meer beschikbaar. Zoek opnieuw.'), 404
    with control_lock:
        if current:
            current.close()
        current = Preview(source)
        return jsonify(id=current.id)


@app.get('/api/preview/<preview_id>')
def preview_status(preview_id):
    if not current or current.id != preview_id:
        abort(404)
    return jsonify(current.status())


@app.get('/api/preview/<preview_id>/video')
def preview_video(preview_id):
    if not current or current.id != preview_id:
        abort(404)
    return Response(current.frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.delete('/api/preview/<preview_id>')
def stop_preview(preview_id):
    with control_lock:
        if current and current.id == preview_id:
            current.close()
    return '', 204


def cleanup():
    global current, browser, mdns, finder
    with control_lock:
        if current:
            current.close()
            current = None
    if browser:
        browser.cancel()
        browser = None
    if mdns:
        mdns.close()
        mdns = None
    with scan_lock:
        if finder is not None:
            finder.close()
            finder = None


atexit.register(cleanup)
if __name__ == '__main__':
    init_discovery()
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8000')), threaded=True, debug=False)
