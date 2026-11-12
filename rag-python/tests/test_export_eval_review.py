"""Tests for scripts/export_eval_review.py."""

import importlib.util
import random
import sys
from pathlib import Path


def _load_export_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "export_eval_review.py"
    spec = importlib.util.spec_from_file_location("export_eval_review", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["export_eval_review"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_review_markdown_puts_seed42_sample_first():
    """First 15 queries match random.Random(42).sample under 'REVIEW THESE 15' with no duplicates."""
    mod = _load_export_module()
    records = [
        {
            "id": f"q-{i:02d}",
            "category": "semantic" if i % 2 == 0 else "multi_source",
            "query": f"Question {i}",
            "user_id": f"employee_{i}",
            "group_ids": ["group_engineering"],
            "qrels": {f"chunk:{i}:0": 2, f"chunk:{i}:1": 1},
        }
        for i in range(25)
    ]
    chunks = {
        f"chunk:{i}:{j}": mod.ChunkRecord(
            chunk_id=f"chunk:{i}:{j}",
            source="github" if j == 0 else "slack",
            content=f"Full DB text for chunk {i}-{j} with ``` backticks.",
        )
        for i in range(25)
        for j in (0, 1)
    }

    md = mod.build_review_markdown(records, chunks, seed=42, sample_size=15)

    assert "## REVIEW THESE 15" in md
    assert "## REMAINING QUERIES (10)" in md
    assert md.index("## REVIEW THESE 15") < md.index("## REMAINING QUERIES (10)")

    expected_first_15 = [r["id"] for r in random.Random(42).sample(records, 15)]
    section_ids = [line[4:].strip() for line in md.splitlines() if line.startswith("### ")]
    assert len(section_ids) == 25
    assert section_ids[:15] == expected_first_15
    assert len(set(section_ids)) == 25

    for i in range(25):
        assert f"- **Query ID:** `q-{i:02d}`" in md
        assert f"- **Identity:** `employee_{i}` (groups: `group_engineering`)" in md
        assert f"Full DB text for chunk {i}-0" in md
        assert f"source `github`" in md
        assert f"source `slack`" in md


def test_generated_review_queries_v2_markdown_matches_jsonl():
    """Generated review_queries_v2.md covers all 60 queries with seed=42 sample first."""
    mod = _load_export_module()
    repo_root = Path(__file__).resolve().parents[2]
    queries_path = repo_root / "data" / "evaluation" / "queries_v2.jsonl"
    review_path = repo_root / "data" / "evaluation" / "review_queries_v2.md"

    records = mod.load_queries_jsonl(queries_path)
    assert len(records) == 60
    assert review_path.exists()

    text = review_path.read_text(encoding="utf-8")
    assert "## REVIEW THESE 15" in text
    section_ids = [line[4:].strip() for line in text.splitlines() if line.startswith("### ")]
    expected_first_15 = [r["id"] for r in random.Random(42).sample(records, 15)]
    assert len(section_ids) == 60
    assert len(set(section_ids)) == 60
    assert section_ids[:15] == expected_first_15
