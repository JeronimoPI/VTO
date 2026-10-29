"""Signal metadata, SDK receiver counters and local processing rate."""
from collections import deque
import math
import numbers
import threading
import time

QUALITY_PROFILES = {
    'balanced': dict(id='balanced', label='Zuinig · 720p / 15 fps', width=1280, height=720, fps=15, jpeg_quality=80, ffmpeg_quality=5),
    'sharp': dict(id='sharp', label='Scherper · 1080p / 30 fps', width=1920, height=1080, fps=30, jpeg_quality=92, ffmpeg_quality=2),
}


def resize_preview(frame, profile):
    import cv2
    height, width = frame.shape[:2]
    scale = min(1, profile['width'] / width, profile['height'] / height)
    if scale < 1:
        return cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    return frame


def ndi_metadata(video):
    """Read before get_array() releases native storage; missing fields stay unknown."""
    metadata = dict(width=int(video.xres), height=int(video.yres), fps=None, pixel_format=None, scan=None)
    try:
        rate = float(video.get_frame_rate())
        if math.isfinite(rate) and rate > 0:
            metadata['fps'] = round(rate, 3)
    except (AttributeError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        pass
    try:
        metadata['pixel_format'] = video.get_fourcc().name
    except (AttributeError, ValueError):
        pass
    try:
        metadata['scan'] = video.frame_format.name
    except (AttributeError, ValueError):
        pass
    return metadata


class VideoStats:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.input = None
        self.frames = deque()
        self.first_frame = None
        self.last_frame = None
        self.previous = None
        self.sdk = None
        self.sdk_sample_time = None
        self.last_attempt = None

    def set_input(self, metadata):
        with self.lock:
            self.input = dict(metadata)

    def published(self, timestamp):
        with self.lock:
            self.frames.append(timestamp)
            if self.first_frame is None:
                self.first_frame = timestamp
            self.last_frame = timestamp
            self._prune(timestamp)

    def _prune(self, now):
        while self.frames and self.frames[0] <= now - 2:
            self.frames.popleft()

    def poll_sdk(self, receiver):
        now = self.clock()
        with self.lock:
            if self.last_attempt is not None and now - self.last_attempt < 1:
                return
            self.last_attempt = now
        try:
            video = receiver.get_performance_data()['video']
            received, dropped = video['frames_total'], video['frames_dropped']
            if any(not isinstance(value, numbers.Integral) or isinstance(value, bool) or value < 0 for value in [received, dropped]):
                raise ValueError('Invalid NDI counters')
            received, dropped = int(received), int(dropped)
            with self.lock:
                fps, recent_drops = None, None
                if self.previous:
                    previous_time, previous_received, previous_dropped = self.previous
                    # Reconnection/reset starts a new measurement baseline.
                    if received >= previous_received and dropped >= previous_dropped and now > previous_time:
                        fps = round((received - previous_received) / (now - previous_time), 1)
                        recent_drops = dropped - previous_dropped
                self.previous = (now, received, dropped)
                self.sdk_sample_time = now
                self.sdk = dict(received=received, dropped=dropped,
                                dropped_percent=round(100 * dropped / received, 3) if received else None,
                                fps=fps, recent_drops=recent_drops)
                return dict(self.sdk)
        except Exception:
            # Counter support must never interrupt otherwise valid video.
            with self.lock:
                self.sdk = None

    def snapshot(self):
        now = self.clock()
        with self.lock:
            self._prune(now)
            fps = None
            if self.first_frame is not None:
                age = now - self.first_frame
                if age >= 2:
                    fps = round(len(self.frames) / 2, 1)
                elif age > .1:
                    fps = round(max(0, len(self.frames) - 1) / age, 1)
            age = max(0, now - self.sdk_sample_time) if self.sdk_sample_time is not None else None
            current = self.sdk is not None and age is not None and age <= 3
            return dict(input=dict(self.input) if self.input else None,
                        processing_fps=fps,
                        frame_age=round(max(0, now - self.last_frame), 2) if self.last_frame is not None else None,
                        sdk=dict(available=current, age=round(age, 1) if age is not None else None,
                                 **(self.sdk if current else dict(received=None, dropped=None, dropped_percent=None, fps=None, recent_drops=None))))
