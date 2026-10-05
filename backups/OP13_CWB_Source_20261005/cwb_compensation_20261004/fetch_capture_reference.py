"""Download the fixed AOSP Android 16 reference; no device writes."""
from pathlib import Path
import base64
import requests

ROOT = Path(__file__).resolve().parent / 'sf_reference'
FILES = [
    'libs/gui/aidl/android/gui/ISurfaceComposer.aidl',
    'libs/gui/aidl/android/gui/DisplayCaptureArgs.aidl',
    'libs/gui/aidl/android/gui/CaptureArgs.aidl',
    'libs/gui/aidl/android/gui/ScreenCaptureResults.aidl',
    'libs/gui/aidl/android/gui/IScreenCaptureListener.aidl',
    'libs/gui/include/gui/SyncScreenCaptureListener.h',
    'libs/gui/SyncScreenCaptureListener.cpp',
    'libs/gui/include/gui/ScreenCaptureResults.h',
    'libs/gui/ScreenCaptureResults.cpp',
    'libs/gui/include/gui/DisplayCaptureArgs.h',
    'libs/gui/DisplayCaptureArgs.cpp',
    'libs/gui/include/gui/CaptureArgs.h',
    'libs/gui/CaptureArgs.cpp',
    'services/surfaceflinger/RegionSamplingThread.cpp',
]
base = 'https://android.googlesource.com/platform/frameworks/native/+/refs/heads/android16-release/'
session = requests.Session()
for name in FILES:
    output = ROOT / name
    if output.exists():
        continue
    response = session.get(base + name + '?format=TEXT', timeout=20)
    if response.status_code == 404:
        print(f'Not present in this branch: {name}')
        continue
    response.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(response.content))
    print(f'Reference: {name}')
