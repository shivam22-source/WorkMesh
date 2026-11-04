"""Standalone database and pgvector verification CLI for WorkMesh."""

import argparse
import sys
from typing import Dict, List, Tuple

from app.common.config import get_settings


def verify_database_and_vector(db_url: str) -> Tuple[bool, List[Dict[str, str]]]:
    """Execute deep verification of PostgreSQL schema, pgvector extension, and row counts."""
    import psycopg

    checks: List[Dict[str, str]] = []
    all_ok = True

    try:
        with psycopg.connect(db_url) as conn:
            # 1. Connectivity
            checks.append({"Check": "Database Connectivity", "Status": "PASS", "Detail": "Successfully connected"})

            with conn.cursor() as cur:
                # 2. pgvector extension
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
                row = cur.fetchone()
                if row:
                    checks.append({"Check": "pgvector Extension", "Status": "PASS", "Detail": f"v{row[0]}"})
                else:
                    all_ok = False
                    checks.append({"Check": "pgvector Extension", "Status": "FAIL", "Detail": "vector extension missing"})

                # 3. Vector operator test
                try:
                    cur.execute("SELECT '[1,2,3]'::vector <=> '[1,2,4]'::vector AS dist;")
                    dist = cur.fetchone()[0]
                    checks.append({"Check": "Cosine Distance Operator", "Status": "PASS", "Detail": f"dist={dist:.4f}"})
                except Exception as e:
                    all_ok = False
                    checks.append({"Check": "Cosine Distance Operator", "Status": "FAIL", "Detail": str(e)})

                # 4. Table counts
                tables = ["documents", "chunks", "acl_references", "entities", "relationships", "audit_events"]
                for tbl in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                        cnt = cur.fetchone()[0]
                        checks.append({"Check": f"Table: {tbl}", "Status": "PASS", "Detail": f"{cnt} rows"})
                    except Exception as e:
                        all_ok = False
                        checks.append({"Check": f"Table: {tbl}", "Status": "FAIL", "Detail": str(e)})

    except Exception as e:
        checks.append({"Check": "Database Connectivity", "Status": "FAIL", "Detail": str(e)})
        return False, checks

    return all_ok, checks


def main():
    parser = argparse.ArgumentParser(description="WorkMesh Database and pgvector Verification Tool")
    parser.add_argument("--url", default=None, help="Database connection URL (defaults to Settings.database_url)")
    args = parser.parse_args()

    settings = get_settings()
    db_url = args.url or settings.database_url

    print("=" * 65)
    print("      WORKMESH DATABASE & PGVECTOR VERIFICATION")
    print("=" * 65)
    print(f"Target URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print("-" * 65)

    success, results = verify_database_and_vector(db_url)

    for item in results:
        status_str = f"[{item['Status']}]"
        print(f"{item['Check']:<28} {status_str:<8} {item['Detail']}")

    print("=" * 65)
    if success:
        print("RESULT: All database and vector verification checks passed.")
        sys.exit(0)
    else:
        print("RESULT: Verification failed. Check details above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
