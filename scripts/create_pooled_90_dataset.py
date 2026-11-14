import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

dev_path = REPO_ROOT / "data" / "evaluation" / "queries_v2.jsonl"
heldout_path = REPO_ROOT / "data" / "evaluation" / "queries_heldout_30.jsonl"
pooled_path = REPO_ROOT / "data" / "evaluation" / "queries_pooled_90.jsonl"

dev_records = [json.loads(line) for line in dev_path.read_text(encoding="utf-8").splitlines() if line.strip()]
dev_60 = [r for r in dev_records if r["category"] in ("exact_identifier", "semantic", "multi_source")]

heldout_records = [json.loads(line) for line in heldout_path.read_text(encoding="utf-8").splitlines() if line.strip()]

assert len(dev_60) == 60, f"Expected 60 dev queries, got {len(dev_60)}"
assert len(heldout_records) == 30, f"Expected 30 heldout queries, got {len(heldout_records)}"

pooled_records = dev_60 + heldout_records
assert len(pooled_records) == 90

with open(pooled_path, "w", encoding="utf-8") as f:
    for r in pooled_records:
        f.write(json.dumps(r) + "\n")

print(f"Created {pooled_path} with {len(pooled_records)} queries (60 dev + 30 heldout).")
