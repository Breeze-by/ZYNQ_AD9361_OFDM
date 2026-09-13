"""Read existing independent summaries, retaining missing sequence lists."""
import json
import os
from pathlib import Path
import sys

diag = Path(os.environ["TEMP"]) / "ad9361-diag-20260906"
results = []
for tag in sys.argv[1:]:
    if not tag.startswith("stage21-") or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in tag):
        raise ValueError("Invalid tag")
    summary = json.loads((diag / tag / "independent.summary.json").read_text(encoding="utf-8"))
    summary.pop("bad_details", None)
    results.append(summary)
print(json.dumps(results, indent=2))
