"""Locate bundled media tools without depending on a shell or Homebrew."""
from pathlib import Path
import shutil
import ssl
import sys


def ffmpeg_path():
    # The imageio Linux static binary can crash in DNS/network calls on newer
    # glibc hosts. Use the distribution build for Linux development and tests.
    if sys.platform.startswith('linux'):
        return shutil.which('ffmpeg')
    try:
        import imageio_ffmpeg
        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(candidate).is_file():
            return candidate
    except (ImportError, RuntimeError, OSError):
        pass
    return shutil.which('ffmpeg')


def trusted_ca_file():
    configured = ssl.get_default_verify_paths().cafile
    if configured:
        return configured
    # Finder-launched macOS bundles do not inherit a shell certificate setup.
    import certifi
    return certifi.where()
