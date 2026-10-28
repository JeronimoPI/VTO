"""Run on the source's network to test NDI reception without the desktop UI."""
from pathlib import Path
import argparse
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', help='Part of the source name (optional)')
    args = parser.parse_args()
    print(f'Platform: {platform.system()} / {platform.machine()} / Python {platform.python_version()}', flush=True)
    print(f'NDI-binding geladen: {app.NDI_READY}', flush=True)
    if not app.NDI_READY:
        return 1
    try:
        from cyndilib.wrapper import ndi_version
        print(f'NDI-runtime: {ndi_version}', flush=True)
        deadline = time.monotonic() + 8
        candidates = []
        while time.monotonic() < deadline:
            candidates = [s for s in app.scan() if s['kind'] == 'NDI' and (not args.source or args.source.lower() in s['name'].lower())]
            if candidates:
                break
        if not candidates:
            print('Geen passende NDI-bron gevonden.', flush=True)
            return 2
        if len(candidates) > 1:
            print('Meerdere bronnen; kies met --source "deel van de naam":', flush=True)
            for source in candidates:
                print('  ' + source['name'], flush=True)
            return 2
        source = candidates[0]
        print('Bron: ' + source['name'], flush=True)
        preview = app.Preview(app.sources[source['id']])
        try:
            previous = None
            while preview.thread.is_alive():
                status = preview.status()
                summary = (status['state'], status.get('ndi', {}).get('stage'), status.get('ndi', {}).get('connections'))
                if summary != previous:
                    print(f'Status: {summary[0]} | fase: {summary[1]} | verbindingen: {summary[2]}', flush=True)
                    previous = summary
                if preview.sequence >= 2:
                    print(f'Videobeeld ontvangen: {preview.width} x {preview.height}; {preview.sequence} previewframes.', flush=True)
                    return 0
                time.sleep(.2)
            print(preview.message, flush=True)
            return 1
        finally:
            preview.close()
    finally:
        app.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
