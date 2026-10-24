import json
from pathlib import Path
raw = Path("src.dts").read_text()
j = json.loads(Path("patches.json").read_text())
for r in j["replacements"]:
    assert raw.count(r["old"]) == 1, "mismatch " + r["node"]
    raw = raw.replace(r["old"], r["new"])
Path("patched.dts").write_text(raw)
