# Build natively for each target; PyInstaller cannot cross-compile macOS/Windows.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [(str(root / 'templates'), 'templates'), (str(root / 'static'), 'static')]
binaries = []
hiddenimports = []
for package in ['cyndilib', 'imageio_ffmpeg', 'certifi']:
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

if sys.platform == 'darwin':
    hiddenimports += ['webview.platforms.cocoa']
elif sys.platform == 'win32':
    hiddenimports += ['webview.platforms.edgechromium']

a = Analysis([str(root / 'desktop.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gi'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VTO',
          debug=False, strip=False, upx=False, console=False)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='VTO')
if sys.platform == 'darwin':
    application = BUNDLE(collection, name='VTO.app', bundle_identifier='com.vto.monitor',
        info_plist={
            'CFBundleDisplayName': 'VTO',
            'CFBundleShortVersionString': '0.1.0',
            'CFBundleVersion': '1',
            'LSMinimumSystemVersion': '14.0',
            'NSHighResolutionCapable': True,
            'NSLocalNetworkUsageDescription': 'VTO zoekt en ontvangt NDI- en camerafeeds op je lokale netwerk.',
            'NSBonjourServices': ['_ndi._tcp', '_rtsp._tcp'],
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
        })
