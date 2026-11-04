"""Tests for database verification CLI."""

from unittest.mock import MagicMock, patch
from app.cli.verify_db import verify_database_and_vector


def test_verify_database_and_vector_success():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value = mock_cursor

    # Setup mock query returns:
    # 1. extversion -> ('0.5.1',)
    # 2. vector dist -> (0.0123,)
    # 3. 6 table counts -> (100,) each
    mock_cursor.fetchone.side_effect = [
        ("0.5.1",),
        (0.0123,),
        (10,), (20,), (30,), (40,), (50,), (60,),
    ]

    with patch("psycopg.connect", return_value=mock_conn):
        success, results = verify_database_and_vector("postgresql://test:test@localhost:5432/test")
        assert success is True
        assert any(r["Check"] == "pgvector Extension" and r["Status"] == "PASS" for r in results)
        assert any(r["Check"] == "Cosine Distance Operator" and r["Status"] == "PASS" for r in results)


def test_verify_database_and_vector_connection_failure():
    with patch("psycopg.connect", side_effect=ConnectionError("Connection refused")):
        success, results = verify_database_and_vector("postgresql://test:test@invalid_host:5432/test")
        assert success is False
        assert results[0]["Check"] == "Database Connectivity"
        assert results[0]["Status"] == "FAIL"
