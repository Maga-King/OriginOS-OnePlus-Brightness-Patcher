"""Summarize real native CWB captures; no device or ROM writes."""
from collections import Counter
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parent
prefix = sys.argv[1] if len(sys.argv) > 1 else "coloros_spatial"
results = {}
for phase in ("roi_red", "roi_green", "roi_blue", "roi_black", "offroi_red", "white"):
    text = (root / f"{prefix}_{phase}_verbose.txt").read_text(encoding="utf-8-sig")
    captures = re.findall(r"CWBScreenShotCallback.*?rgb\((\d+) (\d+) (\d+) (\d+)\).*?duration:(\d+)ms", text)
    reports = re.findall(r"process end reported = (\d+).*?match ([0-9.]+)", text)
    colors = Counter(tuple(map(int, row[:4])) for row in captures)
    state = (root / f"{prefix}_{phase}_state.txt").read_text(encoding="utf-8-sig")
    results[phase] = {
        "callbacks": len(captures),
        "dominant_rgbp": list(colors.most_common(1)[0][0]) if colors else None,
        "window_ms_range": [min(int(row[4]) for row in captures), max(int(row[4]) for row in captures)] if captures else None,
        "reports": len(reports),
        "reported": sum(int(row[0]) == 1 for row in reports),
        "match_at_least_06": sum(float(row[1]) >= 0.6 for row in reports),
        "screen_awake_before_and_after": state.count("mWakefulness=Awake") == 2,
    }
print(json.dumps(results, ensure_ascii=False, indent=2))
if any(not result["callbacks"] or not result["screen_awake_before_and_after"] for result in results.values()):
    raise SystemExit("Incomplete or screen-off test; do not treat as valid spatial evidence")
for phase, channel in (("roi_red", 0), ("roi_green", 1), ("roi_blue", 2)):
    rgb = results[phase]["dominant_rgbp"][:3]
    if rgb[channel] != max(rgb) or rgb[channel] - min(rgb) < 100:
        raise SystemExit(f"{phase}: requested channel did not dominate; investigate coordinate/color handling")
white = results["white"]["dominant_rgbp"][:3]
off = results["offroi_red"]["dominant_rgbp"][:3]
if max(abs(a-b) for a,b in zip(white,off)) > 10:
    raise SystemExit("Off-ROI red changed sampled RGB; investigate geometry or whole-screen color transforms")
if max(results["roi_black"]["dominant_rgbp"][:3]) > 80:
    raise SystemExit("ROI black was not dark: patch coverage requires investigation")
print("PASS: requested ROI colors observed; off-ROI red stayed equivalent to white.")
