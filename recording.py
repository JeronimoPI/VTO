"""A bounded preview buffer and fixed-length, timestamped MP4 highlight clips."""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from media_runtime import ffmpeg_path

PRE_SECONDS = 3.0
POST_SECONDS = 7.0
FPS = 15
MAX_GAP = .75
MAX_BUFFER_BYTES = 256 * 1024 * 1024
MAX_CLIP_BYTES = 768 * 1024 * 1024
logger = logging.getLogger(__name__)


class RecordingError(RuntimeError):
    pass


def settings_path():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/VTO/settings.json'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'VTO/settings.json'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'vto/settings.json'


def default_directory():
    return Path.home() / ('Movies' if sys.platform == 'darwin' else 'Videos') / 'VTO'


@dataclass
class Clip:
    id: str
    source: str
    trigger: float
    path: Path
    frames: list
    fps: float = FPS
    native: bool = False
    state: str = 'collecting'
    message: str = 'Nog 7 seconden beeld verzamelen…'
    size: int = 0
    stop: threading.Event = field(default_factory=threading.Event)
    timer: object = None
    worker: object = None
    process: object = None


class ClipRecorder:
    def __init__(self, directory=None, preferences=None, clock=time.monotonic):
        self.lock = threading.RLock()
        self.clock = clock
        self.preferences = Path(preferences) if preferences else settings_path()
        self.directory = Path(directory) if directory else self._load_directory()
        self.source_id = None
        self.source_name = ''
        self.buffer = deque()
        self.buffer_bytes = 0
        self.resolution = None
        self.active = None
        self.jobs = {}
        self.fps = FPS
        self.native = False
        self.signal_error = None

    def _load_directory(self):
        override = os.environ.get('VTO_RECORDINGS_DIR')
        if override:
            return Path(override).expanduser().resolve()
        try:
            if self.preferences.stat().st_size < 8192:
                value = json.loads(self.preferences.read_text()).get('recording_directory')
                if isinstance(value, str) and Path(value).is_absolute():
                    return Path(value)
        except (OSError, ValueError, AttributeError):
            pass
        return default_directory()

    def set_directory(self, directory):
        path = Path(directory).expanduser().resolve()
        with self.lock:
            if self._busy():
                raise RecordingError('Wacht tot de huidige clip is opgeslagen voordat je de opnamemap wijzigt.')
            if not path.is_dir():
                raise RecordingError('De gekozen map bestaat niet.')
            try:
                # Check permission with a temporary file; never overwrite user files.
                with tempfile.TemporaryFile(dir=path):
                    pass
                self.preferences.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='w', dir=self.preferences.parent, delete=False, suffix='.tmp') as output:
                    temporary = Path(output.name)
                    json.dump({'recording_directory': str(path)}, output)
                try:
                    os.replace(temporary, self.preferences)
                finally:
                    temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise RecordingError('De mapkeuze kon niet worden opgeslagen. Controleer de schrijfrechten.') from exc
            self.directory = path
            return str(path)

    def _busy(self):
        return self.active is not None and self.active.state in ('collecting', 'saving')

    def is_collecting(self):
        with self.lock:
            return self._busy() and self.active.state == 'collecting'

    def is_busy(self):
        with self.lock:
            return self._busy()

    def select_source(self, source_id, name, fps=FPS, native=False):
        with self.lock:
            if self.is_collecting():
                raise RecordingError('De clip wordt opgenomen. Wacht met het wisselen van bron.')
            self.source_id, self.source_name = source_id, name
            self.fps, self.native = fps, native
            self.signal_error = 'Wachten op de bronframerate.' if native else None
            self._clear_buffer()

    def configure_native(self, source_id, fps):
        with self.lock:
            if source_id != self.source_id:
                return
            if fps is None or not math.isfinite(fps) or fps <= 0 or fps > 120:
                if self.is_collecting():
                    self._fail(self.active, 'Opname afgebroken: de bronframerate is niet meer beschikbaar of wordt niet ondersteund.')
                self.signal_error = 'Opnemen vereist een bekende bronframerate van maximaal 120 fps.'
                return
            if fps != self.fps:
                if self.is_collecting():
                    self._fail(self.active, 'Opname afgebroken: de bronframerate veranderde.')
                self._clear_buffer()
            self.fps, self.native, self.signal_error = fps, True, None

    def _clear_buffer(self):
        self.buffer.clear()
        self.buffer_bytes = 0
        self.resolution = None

    def stop_source(self, source_id):
        with self.lock:
            if self.source_id != source_id:
                return
            if self.is_collecting():
                self._fail(self.active, 'Opname afgebroken: de bron is gestopt. Er is geen onvolledige clip bewaard.')
            self.source_id = None
            self._clear_buffer()

    def discontinuity(self, source_id, message):
        with self.lock:
            if source_id != self.source_id:
                return
            if self.is_collecting():
                self._fail(self.active, message)
            self._clear_buffer()

    def push(self, source_id, jpeg, width, height, timestamp=None):
        timestamp = self.clock() if timestamp is None else timestamp
        with self.lock:
            if source_id != self.source_id:
                return
            gap = bool(self.buffer and timestamp - self.buffer[-1][0] > MAX_GAP)
            changed = self.resolution is not None and self.resolution != (width, height)
            if gap or changed:
                if self.is_collecting():
                    self._fail(self.active, 'Opname afgebroken: het beeld viel weg of de resolutie veranderde.')
                self._clear_buffer()
            self.resolution = (width, height)
            entry = (timestamp, jpeg)
            self.buffer.append(entry)
            self.buffer_bytes += len(jpeg)
            # Retain one frame at/before the pre-roll boundary for precise sampling.
            while len(self.buffer) > 1 and self.buffer[1][0] <= timestamp - PRE_SECONDS:
                self.buffer_bytes -= len(self.buffer.popleft()[1])
            while self.buffer and self.buffer_bytes > MAX_BUFFER_BYTES:
                self.buffer_bytes -= len(self.buffer.popleft()[1])
            if self.is_collecting() and timestamp < self.active.trigger + POST_SECONDS:
                self.active.frames.append(entry)
                self.active.size += len(jpeg)
                if self.active.size > MAX_CLIP_BYTES:
                    self._fail(self.active, 'Opname afgebroken: de beeldbuffer is te groot.')

    def _buffer_status(self, now):
        seconds = min(PRE_SECONDS, max(0, self.buffer[-1][0] - self.buffer[0][0])) if self.buffer else 0
        fresh = bool(self.buffer and now - self.buffer[-1][0] <= MAX_GAP)
        ready = not self.signal_error and fresh and bool(self.buffer) and self.buffer[0][0] <= now - PRE_SECONDS
        return dict(source_id=self.source_id, seconds=round(seconds, 2), ready=bool(ready), fresh=fresh,
                    fps=self.fps, native=self.native, resolution=self.resolution, error=self.signal_error)

    def trigger(self, source_id):
        with self.lock:
            now = self.clock()
            if self._busy():
                raise RecordingError('Er wordt al een clip gemaakt. Wacht tot die is opgeslagen.')
            if source_id != self.source_id or not self._buffer_status(now)['ready']:
                raise RecordingError('Wacht tot er 3 seconden ononderbroken beeld in de buffer zit.')
            if not ffmpeg_path():
                raise RecordingError('FFmpeg is niet beschikbaar om de opname op te slaan.')
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RecordingError('De opnamemap kan niet worden aangemaakt. Kies een schrijfbare map.') from exc
            identifier = uuid.uuid4().hex
            name = re.sub(r'[^A-Za-z0-9_-]+', '-', self.source_name).strip('-')[:40] or 'bron'
            filename = f'VTO-{datetime.now().astimezone():%Y%m%d-%H%M%S}-{name}-{identifier[:8]}.mp4'
            frames = list(self.buffer)
            # Begin at the last captured frame at/before the requested boundary.
            first = 0
            while first + 1 < len(frames) and frames[first + 1][0] <= now - PRE_SECONDS:
                first += 1
            clip = Clip(identifier, self.source_name, now, self.directory / filename, frames[first:], fps=self.fps, native=self.native)
            clip.size = sum(len(frame) for _, frame in clip.frames)
            self.active = clip
            self.jobs[identifier] = clip
            # Only metadata for the last 20 clips stays in the UI.
            while len(self.jobs) > 20:
                del self.jobs[next(iter(self.jobs))]
            clip.timer = threading.Timer(POST_SECONDS, self.finish, args=(identifier,))
            clip.timer.daemon = True
            clip.timer.start()
            return self._clip_status(clip, now)

    def _fail(self, clip, message):
        clip.state, clip.message = 'error', message
        clip.stop.set()
        clip.frames.clear()
        if clip.timer:
            clip.timer.cancel()

    def finish(self, identifier):
        with self.lock:
            clip = self.jobs.get(identifier)
            if clip is None or clip.state != 'collecting':
                return
            if self.clock() < clip.trigger + POST_SECONDS:
                return
            if not clip.frames or clip.trigger + POST_SECONDS - clip.frames[-1][0] > MAX_GAP:
                self._fail(clip, 'Opname afgebroken: er kwam aan het einde geen beeld meer binnen.')
                return
            if clip.timer:
                clip.timer.cancel()
            clip.state, clip.message = 'saving', 'MP4 opslaan…'
            frames, clip.frames = clip.frames, []
            clip.worker = threading.Thread(target=self._encode, args=(clip, frames), daemon=True)
            clip.worker.start()

    def _encode(self, clip, frames):
        partial = None
        process = None
        watchdog = None
        try:
            required = round((PRE_SECONDS + POST_SECONDS) * clip.fps)
            if clip.native and len(frames) > required + 2:
                raise RecordingError('Opname niet opgeslagen: het aantal bronframes wijkt af van de gemelde bronframerate.')
            if clip.native and len(frames) < required:
                raise RecordingError('Opname niet opgeslagen: er ontbreken bronframes. Er worden geen frames verzonnen om de framerate te halen.')
            with tempfile.NamedTemporaryFile(dir=clip.path.parent, prefix='.VTO-', suffix='.partial.mp4', delete=False) as output:
                partial = Path(output.name)
            args = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                    '-f', 'image2pipe', '-vcodec', 'mjpeg', '-framerate', str(clip.fps), '-i', 'pipe:0',
                    '-an', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264',
                    '-threads', '2', '-preset', 'ultrafast' if clip.fps > 60 else 'veryfast', '-crf', '16' if clip.native else '20', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', str(partial)]
            with tempfile.TemporaryFile() as diagnostics:
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=diagnostics, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                with self.lock:
                    clip.process = process
                watchdog = threading.Timer(120, lambda: process.kill() if process.poll() is None else None)
                watchdog.daemon = True
                watchdog.start()
                start = clip.trigger - PRE_SECONDS
                index = 0
                # NDI stores each original received frame once, without FrameSync
                # re-clocking or preview throttling. Other sources retain the
                # timestamped preview sampling used in the original clip feature.
                for number in range(required):
                    if clip.stop.is_set():
                        raise RecordingError('Opname geannuleerd.')
                    if clip.native:
                        index = number
                    else:
                        target = start + number / clip.fps
                        while index + 1 < len(frames) and frames[index + 1][0] <= target:
                            index += 1
                    process.stdin.write(frames[index][1])
                process.stdin.close()
                if process.wait(timeout=10) != 0 or partial.stat().st_size == 0:
                    raise RecordingError('MP4 kon niet worden opgeslagen.')
            with self.lock:
                if clip.stop.is_set():
                    raise RecordingError('Opname geannuleerd.')
                os.replace(partial, clip.path)
                clip.state, clip.message = 'saved', 'Opgeslagen'
        except Exception as exc:
            logger.warning('Recording failed: %s', type(exc).__name__)
            with self.lock:
                self._fail(clip, str(exc) if isinstance(exc, RecordingError) else 'Opslaan mislukt. Controleer de opnamemap, vrije schijfruimte en schrijfrechten.')
        finally:
            if watchdog:
                watchdog.cancel()
            if process:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            if partial:
                partial.unlink(missing_ok=True)
            with self.lock:
                clip.process = None

    def _clip_status(self, clip, now):
        return dict(id=clip.id, source=clip.source, state=clip.state, message=clip.message,
                    filename=clip.path.name, path=str(clip.path), duration=round(round(10 * clip.fps) / clip.fps, 4), pre_seconds=3,
                    fps=clip.fps, native=clip.native,
                    remaining=max(0, math.ceil(clip.trigger + POST_SECONDS - now)) if clip.state == 'collecting' else 0)

    def status(self):
        with self.lock:
            now = self.clock()
            return dict(folder=str(self.directory), buffer=self._buffer_status(now),
                        active=self._clip_status(self.active, now) if self._busy() else None,
                        items=[self._clip_status(clip, now) for clip in reversed(list(self.jobs.values()))])

    def open_directory(self):
        with self.lock:
            folder = self.directory
            folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'darwin':
            subprocess.run(['/usr/bin/open', str(folder)], check=True)
        elif sys.platform == 'win32':
            os.startfile(str(folder))
        else:
            subprocess.run(['xdg-open', str(folder)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def shutdown(self):
        with self.lock:
            self.source_id = None
            self._clear_buffer()
            clip = self.active
            if self._busy():
                self._fail(clip, 'Opname afgebroken: VTO is afgesloten.')
            process = clip.process if clip else None
            worker = clip.worker if clip else None
        if process and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)
