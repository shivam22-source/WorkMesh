"""Tests for enterprise acronym and synonym query expansion."""

from app.retrieval.expansion import expand_query_terms


def test_expand_query_terms_acronyms():
    assert "pull request" in expand_query_terms("auth PR")
    assert "authentication" in expand_query_terms("JWT verification")
    assert "kubernetes" in expand_query_terms("deploy to k8s cluster")
    assert "permissions" in expand_query_terms("check user ACL")


def test_expand_query_terms_passthrough():
    # Queries without mapped acronyms remain unchanged
    assert expand_query_terms("DC-8692") == "DC-8692"
    assert expand_query_terms("payment checkout validation") == "payment checkout validation"
    assert expand_query_terms("") == ""
    assert expand_query_terms("   ") == "   "
