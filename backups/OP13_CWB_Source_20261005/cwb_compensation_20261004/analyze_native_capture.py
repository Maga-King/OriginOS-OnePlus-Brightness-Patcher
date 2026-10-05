"""Compare finite CWB/SSC probe outcomes without assuming raw-sample count is report rate."""
from collections import Counter
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parent
for prefix in sys.argv[1:] or ["origin_static_white", "origin_dynamic_offroi"]:
    lines = (root / f"{prefix}_probe.txt").read_text(encoding="utf-8-sig").splitlines()
    callbacks, raw, summaries = [], [], []
    for line in lines:
        if line.startswith("CWB_SEQUENCE="):
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            callbacks.append(fields)
        elif line.startswith("SAMPLE="):
            raw.append(dict(re.findall(r"(\w+)=([^ ]+)", line)))
        elif line.startswith("SUMMARY"):
            summaries.append(line)
    ordinary_final = [s for s in raw if int(float(s["SEQ"])) & 0x70000 == 0x10000]
    first_corrected = next((i for i,s in enumerate(raw) if s["APPLIED"] == "1"), None)
    durations = [(int(c["END"]) - int(c["START"]))/1e6 for c in callbacks]
    colors = Counter(c["RGB"] for c in callbacks)
    output = {
        "capture": prefix,
        "callback_count": len(callbacks),
        "rgb_counts": dict(colors),
        "capture_window_ms": {"min": min(durations), "max": max(durations), "shorter_than_20ms": sum(d<20 for d in durations)},
        "final_bursts": len(ordinary_final),
        "final_bursts_corrected": sum(s["APPLIED"] == "1" for s in ordinary_final),
        "final_bursts_held": sum(s["APPLIED"] == "2" for s in ordinary_final),
        "final_bursts_raw_fallback": sum(s["APPLIED"] == "0" for s in ordinary_final),
        "all_packet_outcomes": dict(Counter(s["APPLIED"] for s in raw)),
        "raw_packets_after_first_valid_compensation": sum(s["APPLIED"] == "0" for s in raw[first_corrected+1:]) if first_corrected is not None else None,
        "summary": summaries,
    }
    print(json.dumps(output, indent=2))
    if not summaries or "active_after_stop=0 idle_callback_delta=0" not in summaries[-1]:
        raise SystemExit("Capture did not confirm client stop; investigate before continuing")
