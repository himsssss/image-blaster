"""Create a scene-forge project from a reference image.

usage: python3 init_forge.py <image_path> <slug>
Creates worlds/<slug>/forge/ with reference.png, an analysis.json template, and loop/ objects/ dirs.
Never overwrites an existing analysis.json.
"""
import json, sys
from pathlib import Path
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
img, slug = Path(sys.argv[1]), sys.argv[2]
forge = REPO / "worlds" / slug / "forge"
for d in ("objects", "loop", "meshy-logs", "flow-upload"):
    (forge / d).mkdir(parents=True, exist_ok=True)
ref = Image.open(img).convert("RGB")
ref.save(forge / "reference.png")
a = forge / "analysis.json"
if not a.exists():
    a.write_text(json.dumps({
        "reference": "reference.png",
        "size": list(ref.size),
        "camera": {},
        "objects": [],
        "lighting": {"mood": "", "sources": [], "notes": ""},
    }, indent=1))
st = forge / "state.json"
if not st.exists():
    st.write_text(json.dumps({"iterations": []}, indent=1))
print(json.dumps({"forge": str(forge), "size": ref.size}))
