"""Append one verifier-loop iteration to <forge>/state.json (the loop's memory).

usage: python3 log_iter.py <forge_dir> <tag> <group> "<what changed and why>" '<scores json>' [keep|revert]
group: camera | placement | materials | lights | exposure | room
Prints the best iteration so far (by edge_iou, then ssim) so the next step knows the baseline.
"""
import json, sys
from pathlib import Path

forge, tag, group, note, scores = sys.argv[1:6]
decision = sys.argv[6] if len(sys.argv) > 6 else "keep"
p = Path(forge) / "state.json"
st = json.loads(p.read_text()) if p.exists() else {"iterations": []}
sc = json.loads(scores)
sc.pop("regions", None)
st["iterations"].append({"tag": tag, "group": group, "note": note, "scores": sc, "decision": decision})
p.write_text(json.dumps(st, indent=1))
kept = [i for i in st["iterations"] if i["decision"] == "keep"]
best = max(kept, key=lambda i: (i["scores"].get("edge_iou", 0), i["scores"].get("ssim", 0)))
print(json.dumps({"logged": tag, "best": best["tag"], "best_scores": best["scores"], "n": len(st["iterations"])}))
