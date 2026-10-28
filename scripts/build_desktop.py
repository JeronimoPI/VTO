"""Run with the target OS/architecture's Python 3.12 and desktop dependencies."""
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform not in ('darwin', 'win32'):
        raise SystemExit('Build VTO.app on macOS or VTO.exe on Windows. Cross-compilation is not supported.')
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('Use Python 3.12 for this build.')
    arch = platform.machine().lower()
    supported = ('x86_64', 'arm64') if sys.platform == 'darwin' else ('amd64', 'x86_64')
    if arch not in supported:
        raise SystemExit(f'No configured desktop build for architecture {arch}.')
    print(f'Building VTO for {sys.platform}/{arch}', flush=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(ROOT / 'VTO.spec')], cwd=ROOT, check=True)
    if sys.platform == 'darwin':
        # ditto preserves executable permissions and macOS bundle metadata.
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(ROOT / 'dist' / 'VTO.app'), str(ROOT / 'dist' / f'VTO-macOS-{arch}.zip')], check=True)
    else:
        import shutil
        shutil.make_archive(str(ROOT / 'dist' / 'VTO-Windows-x64'), 'zip', ROOT / 'dist', 'VTO')


if __name__ == '__main__':
    main()
