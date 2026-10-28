"""Check the actual packaged executable, not the build virtualenv."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
executable = root / 'dist' / ('VTO.app/Contents/MacOS/VTO' if sys.platform == 'darwin' else 'VTO/VTO.exe')
subprocess.run([str(executable), '--smoke-test'], check=True, timeout=90)
