"""Copy and convert FrameSync frames while their native storage is valid."""
import cv2
import numpy as np


class NDIReceiveError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def read_bgr(video):
    # get_array() releases the native frame after copying it. Capture metadata
    # first; do not read width/height/stride from released native storage.
    width, height = video.xres, video.yres
    if width <= 0 or height <= 0:
        return None
    pixel_format = video.get_fourcc().name
    layouts = {
        'BGRX': (4, cv2.COLOR_BGRA2BGR),
        'BGRA': (4, cv2.COLOR_BGRA2BGR),
        'RGBX': (4, cv2.COLOR_RGBA2BGR),
        'RGBA': (4, cv2.COLOR_RGBA2BGR),
        'UYVY': (2, cv2.COLOR_YUV2BGR_UYVY),
    }
    if pixel_format not in layouts:
        raise NDIReceiveError('NDI_PIXEL_FORMAT', f'Het ontvangen NDI-pixelformaat {pixel_format} wordt nog niet ondersteund.')
    channels, conversion = layouts[pixel_format]
    stride = video.get_line_stride() or width * channels
    if stride < width * channels or (pixel_format == 'UYVY' and width % 2):
        raise NDIReceiveError('NDI_FRAME_LAYOUT', 'Het ontvangen NDI-frame heeft een ongeldige rij-indeling.')
    raw = video.get_array()
    if raw.dtype != np.uint8 or raw.size < stride * height:
        raise NDIReceiveError('NDI_FRAME_SIZE', 'De ontvangen NDI-beeldbuffer is kleiner dan de opgegeven resolutie.')
    rows = raw.reshape(-1)[:stride * height].reshape(height, stride)
    pixels = rows[:, :width * channels].reshape(height, width, channels)
    return cv2.cvtColor(pixels, conversion)
