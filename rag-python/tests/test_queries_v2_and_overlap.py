"""Tests for data/evaluation/queries_v2.jsonl structure and scripts/check_overlap.py."""

import importlib.util
from pathlib import Path

from app.evaluation.corpus_v2 import build_v2_extension_records


def _load_check_overlap_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "check_overlap.py"
    spec = importlib.util.spec_from_file_location("check_overlap", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_queries_v2_dataset_structure_and_categories():
    """queries_v2.jsonl contains 60 valid queries (20/20/20) with graded qrels and user identities."""
    mod = _load_check_overlap_module()
    queries_path = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "queries_v2.jsonl"
    assert queries_path.exists()

    records = mod.load_queries_jsonl(queries_path)
    assert len(records) == 60

    counts = {"exact_identifier": 0, "semantic": 0, "multi_source": 0}
    for rec in records:
        assert rec["id"]
        assert rec["query"].strip()
        assert rec["user_id"]
        assert isinstance(rec["group_ids"], list)
        cat = rec["category"]
        counts[cat] = counts.get(cat, 0) + 1
        qrels = rec["qrels"]
        assert qrels, f"{rec['id']} has empty qrels"
        assert all(grade in (1, 2) for grade in qrels.values())
        if cat == "multi_source":
            assert len(rec["required_sources"]) == 2
            assert len([g for g in qrels.values() if g == 2]) >= 2

    assert counts == {"exact_identifier": 20, "semantic": 20, "multi_source": 20}


def test_semantic_queries_strict_max_one_content_word_overlap():
    """All 20 semantic queries share <= 1 content word with each of their gold chunks."""
    mod = _load_check_overlap_module()
    queries_path = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "queries_v2.jsonl"
    checked, failures = mod.verify_semantic_overlap(queries_path, max_overlap=1, offline=True)
    assert checked == 20
    assert failures == []


def test_v2_extension_records_have_unique_ids():
    """Generated v2 extension documents and chunks have distinct IDs and matching ACLs."""
    docs, chunks, acls, entities, relationships = build_v2_extension_records(embedder=None)
    doc_ids = [d.id for d in docs]
    chunk_ids = [c.id for c in chunks]
    assert len(doc_ids) == len(set(doc_ids))
    assert len(chunk_ids) == len(set(chunk_ids))
    assert len(docs) == 75
    assert len(entities) > 0
    assert len(relationships) > 0
