"""Unit tests for deterministic QueryClassifier covering IDENTIFIER, KEYWORD, SEMANTIC, and MIXED."""

import pytest

from app.retrieval.query_classifier import (
    ClassificationResult,
    QueryClassifier,
    QueryType,
)


@pytest.fixture
def classifier() -> QueryClassifier:
    return QueryClassifier()


# ---------------------------------------------------------------------------
# 1. IDENTIFIER Queries
# ---------------------------------------------------------------------------

def test_exact_ticket_id(classifier: QueryClassifier):
    result = classifier.classify("DC-8692")
    assert result.query_type == QueryType.IDENTIFIER
    assert result.ticket_ids == ["DC-8692"]
    assert result.is_identifier is True
    assert result.is_semantic is False


def test_lowercase_ticket_id(classifier: QueryClassifier):
    result = classifier.classify("dc-8692")
    assert result.query_type == QueryType.IDENTIFIER
    assert result.ticket_ids == ["DC-8692"]


def test_ticket_id_with_boilerplate(classifier: QueryClassifier):
    cases = [
        ("ticket DC-8692", ["DC-8692"]),
        ("lookup issue DC-8692", ["DC-8692"]),
        ("find ticket DC-8692", ["DC-8692"]),
        ("show DC-8692", ["DC-8692"]),
    ]
    for query, expected_tickets in cases:
        res = classifier.classify(query)
        assert res.query_type == QueryType.IDENTIFIER, f"Failed for '{query}'"
        assert res.ticket_ids == expected_tickets


def test_commit_hash(classifier: QueryClassifier):
    # From sample_github_data.json
    res1 = classifier.classify("8af2d1e94b2a8d3e")
    assert res1.query_type == QueryType.IDENTIFIER
    assert res1.commit_hashes == ["8af2d1e94b2a8d3e"]

    res2 = classifier.classify("commit b4c90e1f7a3d2c11")
    assert res2.query_type == QueryType.IDENTIFIER
    assert res2.commit_hashes == ["b4c90e1f7a3d2c11"]


def test_pr_references(classifier: QueryClassifier):
    cases = ["#42", "PR #123", "pull request #42", "pr 99"]
    for query in cases:
        res = classifier.classify(query)
        assert res.query_type == QueryType.IDENTIFIER, f"Failed for '{query}'"
        assert len(res.pr_numbers) > 0


def test_multiple_ticket_ids(classifier: QueryClassifier):
    res = classifier.classify("DC-8692 and DC-8693")
    assert res.query_type == QueryType.IDENTIFIER
    assert "DC-8692" in res.ticket_ids
    assert "DC-8693" in res.ticket_ids


# ---------------------------------------------------------------------------
# 2. KEYWORD Queries
# ---------------------------------------------------------------------------

def test_single_technical_keyword(classifier: QueryClassifier):
    res = classifier.classify("NullPointerException")
    assert res.query_type == QueryType.KEYWORD
    assert res.is_identifier is False
    assert res.is_semantic is False


def test_multi_keyword_phrases(classifier: QueryClassifier):
    cases = [
        "payment validation",
        "PaymentValidationService",
        "HTTP 400 Bad Request",
        "card verification error",
        "docker postgres vector",
    ]
    for query in cases:
        res = classifier.classify(query)
        assert res.query_type == QueryType.KEYWORD, f"Failed for '{query}'"
        assert res.ticket_ids == []
        assert res.commit_hashes == []


# ---------------------------------------------------------------------------
# 3. SEMANTIC Queries
# ---------------------------------------------------------------------------

def test_why_and_how_questions(classifier: QueryClassifier):
    res1 = classifier.classify("why did validation change from 500 to 400?")
    assert res1.query_type == QueryType.SEMANTIC
    assert res1.has_question_intent is True
    assert res1.is_semantic is True

    res2 = classifier.classify("how does checkout handle null card tokens")
    assert res2.query_type == QueryType.SEMANTIC
    assert res2.has_question_intent is True


def test_what_and_where_questions(classifier: QueryClassifier):
    res1 = classifier.classify("what is the SLA for tier 1 incident response")
    assert res1.query_type == QueryType.SEMANTIC

    res2 = classifier.classify("where can I find the payment retry policy?")
    assert res2.query_type == QueryType.SEMANTIC


def test_explain_and_describe_queries(classifier: QueryClassifier):
    res = classifier.classify("explain the payment reconciliation process")
    assert res.query_type == QueryType.SEMANTIC
    assert res.is_semantic is True


def test_auxiliary_question_starters(classifier: QueryClassifier):
    res = classifier.classify("is card verification executed asynchronously?")
    assert res.query_type == QueryType.SEMANTIC
    assert res.has_question_intent is True


def test_long_descriptive_natural_language_phrase(classifier: QueryClassifier):
    res = classifier.classify("best practices for configuring connection pooling and timeout settings in spring boot")
    assert res.query_type == QueryType.SEMANTIC


# ---------------------------------------------------------------------------
# 4. MIXED Queries
# ---------------------------------------------------------------------------

def test_question_with_ticket_id(classifier: QueryClassifier):
    res = classifier.classify("why did DC-8692 change the error code from 500 to 400?")
    assert res.query_type == QueryType.MIXED
    assert res.ticket_ids == ["DC-8692"]
    assert res.is_identifier is True
    assert res.is_semantic is True


def test_question_with_commit_hash(classifier: QueryClassifier):
    res = classifier.classify("what was fixed in commit 8af2d1e94b2a8d3e?")
    assert res.query_type == QueryType.MIXED
    assert res.commit_hashes == ["8af2d1e94b2a8d3e"]
    assert res.is_identifier is True
    assert res.is_semantic is True


def test_ticket_id_with_substantive_keywords(classifier: QueryClassifier):
    res = classifier.classify("DC-8692 payment gateway card validation error")
    assert res.query_type == QueryType.MIXED
    assert res.ticket_ids == ["DC-8692"]
    assert "payment" in res.keywords
    assert "validation" in res.keywords


def test_pr_with_semantic_question(classifier: QueryClassifier):
    res = classifier.classify("has PR #42 been merged into main branch?")
    assert res.query_type == QueryType.MIXED
    assert "42" in res.pr_numbers
    assert res.is_semantic is True


# ---------------------------------------------------------------------------
# 5. Edge Cases & Robustness
# ---------------------------------------------------------------------------

def test_empty_and_whitespace_queries(classifier: QueryClassifier):
    res1 = classifier.classify("")
    assert res1.query_type == QueryType.KEYWORD
    assert res1.ticket_ids == []

    res2 = classifier.classify("   \t\n  ")
    assert res2.query_type == QueryType.KEYWORD


def test_punctuation_around_identifiers(classifier: QueryClassifier):
    res = classifier.classify("Fix for [DC-8692]!")
    assert res.ticket_ids == ["DC-8692"]


def test_non_commit_hex_words_not_falsely_detected(classifier: QueryClassifier):
    # 'decided', 'defect' shouldn't be matched as commit hashes
    res = classifier.classify("payment defect in production")
    assert res.commit_hashes == []
    assert res.query_type == QueryType.KEYWORD
