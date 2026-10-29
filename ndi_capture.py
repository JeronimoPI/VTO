"""Direct NDI video capture without FrameSync's frame dropping/repetition.

Uses the C ABI shipped with cyndilib (NDI SDK v6). A separate receiver is created
here because cyndilib.Receiver always binds a FrameSync to its receiver; the SDK
requires using that FrameSync once bound, which is unsuitable for ISO recording.
"""
import ctypes as C
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import platform
import sys
from types import SimpleNamespace

import numpy as np

from ndi_video import NDIReceiveError


class Source(C.Structure):
    _fields_ = [('name', C.c_char_p), ('address', C.c_char_p)]


class ReceiverSettings(C.Structure):
    _fields_ = [('source', Source), ('color_format', C.c_int), ('bandwidth', C.c_int),
                ('allow_video_fields', C.c_bool), ('name', C.c_char_p)]


class VideoFrame(C.Structure):
    _fields_ = [('xres', C.c_int), ('yres', C.c_int), ('fourcc', C.c_uint32),
                ('rate_n', C.c_int), ('rate_d', C.c_int), ('aspect', C.c_float),
                ('format', C.c_int), ('timecode', C.c_int64), ('data', C.POINTER(C.c_uint8)),
                ('stride', C.c_int), ('metadata', C.c_char_p), ('timestamp', C.c_int64)]

    def get_fourcc(self):
        return SimpleNamespace(name=int(self.fourcc).to_bytes(4, 'little').decode('ascii', errors='replace'))

    def get_frame_rate(self):
        return Fraction(self.rate_n, self.rate_d)

    @property
    def frame_format(self):
        return SimpleNamespace(name={0: 'interleaved', 1: 'progressive', 2: 'field_0', 3: 'field_1'}.get(self.format, 'unknown'))

    def get_line_stride(self):
        return self.stride

    def get_array(self):
        channels = 2 if self.get_fourcc().name == 'UYVY' else 4
        stride = self.stride or self.xres * channels
        if not self.data or stride <= 0 or self.yres <= 0 or stride * self.yres > 128 * 1024 * 1024:
            raise NDIReceiveError('NDI_FRAME_SIZE', 'Ongeldige of te grote NDI-beeldbuffer.')
        return np.ctypeslib.as_array(self.data, shape=(stride * self.yres,)).copy()


class Performance(C.Structure):
    _fields_ = [('video', C.c_int64), ('audio', C.c_int64), ('metadata', C.c_int64)]


@lru_cache(maxsize=1)
def ndi_library():
    import cyndilib
    root = Path(cyndilib.__file__).parent / 'wrapper' / 'bin'
    if sys.platform == 'darwin':
        relocated = root.parent.parent / '.dylibs' / 'libndi.dylib'
        candidates = [relocated] if relocated.is_file() else list(root.rglob('libndi*.dylib'))
    elif sys.platform == 'win32':
        candidates = list(root.rglob('Processing.NDI.Lib.x64.dll'))
    else:
        architecture = {'x86_64': 'x86_64-linux-gnu', 'aarch64': 'aarch64-rpi4-linux-gnueabi'}.get(platform.machine())
        candidates = list((root / architecture).glob('libndi.so*')) if architecture else []
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise NDIReceiveError('NDI_RUNTIME', 'De meegeleverde NDI-runtime is niet gevonden.')
    library = C.CDLL(str(candidates[0]))
    signatures = {
        'NDIlib_initialize': (C.c_bool, []),
        'NDIlib_recv_create_v3': (C.c_void_p, [C.POINTER(ReceiverSettings)]),
        'NDIlib_recv_destroy': (None, [C.c_void_p]),
        'NDIlib_recv_capture_v2': (C.c_int, [C.c_void_p, C.POINTER(VideoFrame), C.c_void_p, C.c_void_p, C.c_uint32]),
        'NDIlib_recv_free_video_v2': (None, [C.c_void_p, C.POINTER(VideoFrame)]),
        'NDIlib_recv_get_no_connections': (C.c_int, [C.c_void_p]),
        'NDIlib_recv_get_performance': (None, [C.c_void_p, C.POINTER(Performance), C.POINTER(Performance)]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    if not library.NDIlib_initialize():
        raise NDIReceiveError('NDI_RUNTIME', 'De NDI-runtime kan niet initialiseren.')
    return library


class NativeReceiver:
    def __init__(self, source_name, address=None):
        self.library = ndi_library()
        self._name = source_name.encode('utf-8') if source_name else None
        self._address = address.encode('utf-8') if address else None
        self._receiver_name = b'VTO capture'
        # RGBX/RGBA (2), highest bandwidth (100), progressive output.
        settings = ReceiverSettings(Source(self._name, self._address), 2, 100, False, self._receiver_name)
        self.handle = self.library.NDIlib_recv_create_v3(C.byref(settings))
        self.frame = None
        if not self.handle:
            raise NDIReceiveError('NDI_RUNTIME', 'De NDI-ontvanger kan niet worden aangemaakt.')

    def capture_video(self, timeout=100):
        self.free_video()
        frame = VideoFrame()
        kind = self.library.NDIlib_recv_capture_v2(self.handle, C.byref(frame), None, None, timeout)
        if kind == 4:
            raise NDIReceiveError('NDI_CONNECTION', 'De NDI-videoverbinding is verbroken.')
        if kind == 1:
            self.frame = frame
            return frame
        return None

    def free_video(self):
        if self.frame is not None:
            self.library.NDIlib_recv_free_video_v2(self.handle, C.byref(self.frame))
            self.frame = None

    def get_num_connections(self):
        return self.library.NDIlib_recv_get_no_connections(self.handle)

    def get_performance_data(self):
        total, dropped = Performance(), Performance()
        self.library.NDIlib_recv_get_performance(self.handle, C.byref(total), C.byref(dropped))
        return dict(video=dict(frames_total=total.video, frames_dropped=dropped.video))

    def close(self):
        if self.handle:
            self.free_video()
            self.library.NDIlib_recv_destroy(self.handle)
            self.handle = None
