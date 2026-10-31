"""Access Control List (ACL) permission evaluation and query builders (AD-04).

Implements the retrieval-level ACL filtering invariant:
- Deny by default: If no explicit READ permission matches, access is denied.
- Permission enforcement: Only 'READ' permission grants retrieval access.
- Supported principals: PUBLIC, USER, GROUP.
"""

from typing import Any, Iterable, List, Optional, Set, Tuple

from app.connectors.common.models import AclReference


def has_read_permission(
    acls: Iterable[AclReference],
    user_id: Optional[str] = None,
    group_ids: Optional[Iterable[str]] = None,
) -> bool:
    """Evaluate whether an identity context has READ permission based on ACL references.

    Rules:
    1. Deny by default: Returns False if acls is empty or no rule grants READ.
    2. Permission check: Only 'READ' (case-insensitive) grants access; 'WRITE', 'ADMIN', etc. do not.
    3. Principal check:
       - PUBLIC: Always grants access if permission is READ.
       - USER: Grants access if principal_id matches user_id.
       - GROUP: Grants access if principal_id matches any identifier in group_ids.
    """
    clean_user = str(user_id).strip() if user_id is not None and str(user_id).strip() else None
    clean_groups: Set[str] = {str(g).strip() for g in group_ids if str(g).strip()} if group_ids else set()

    for acl in acls:
        perm = (acl.permission or "").strip().upper()
        if perm != "READ":
            continue

        p_type = acl.principal_type.value if hasattr(acl.principal_type, "value") else str(acl.principal_type)
        p_type = p_type.strip().upper()
        p_id = (acl.principal_id or "").strip()

        if p_type == "PUBLIC":
            return True
        elif p_type == "USER":
            if clean_user and p_id == clean_user:
                return True
        elif p_type == "GROUP":
            if p_id in clean_groups:
                return True

    return False


def build_acl_where_clause(
    user_id: Optional[str] = None,
    group_ids: Optional[Iterable[str]] = None,
    doc_alias: str = "d",
    chunk_alias: str = "c",
    acl_alias: str = "a",
) -> Tuple[str, List[Any]]:
    """Build a parameterized SQL WHERE fragment that enforces ACL filtering.

    Applies identical semantics to PostgreSQL as has_read_permission:
    - Only READ permission matches.
    - Matches PUBLIC, USER matching user_id, or GROUP matching any in group_ids.
    - Resolves resource_id against SOURCE_RECORD (d.source_record_id),
      DOCUMENT (d.id), or CHUNK (c.id).
    - If user_id is None and group_ids is empty, only PUBLIC READ matches (deny by default for private content).
    """
    clean_user = str(user_id).strip() if user_id is not None and str(user_id).strip() else None
    clean_groups = [str(g).strip() for g in group_ids if str(g).strip()] if group_ids else []

    principal_conditions = [f"{acl_alias}.principal_type = 'PUBLIC'"]
    params: List[Any] = []

    if clean_user:
        principal_conditions.append(f"({acl_alias}.principal_type = 'USER' AND {acl_alias}.principal_id = %s)")
        params.append(clean_user)

    if clean_groups:
        principal_conditions.append(f"({acl_alias}.principal_type = 'GROUP' AND {acl_alias}.principal_id = ANY(%s))")
        params.append(clean_groups)

    principals_sql = " OR ".join(principal_conditions)

    clause = f"""EXISTS (
        SELECT 1 FROM acl_references {acl_alias}
        WHERE UPPER({acl_alias}.permission) = 'READ'
          AND (
              ({acl_alias}.resource_type = 'SOURCE_RECORD' AND {acl_alias}.resource_id = {doc_alias}.source_record_id)
              OR ({acl_alias}.resource_type = 'DOCUMENT' AND {acl_alias}.resource_id = {doc_alias}.id)
              OR ({acl_alias}.resource_type = 'CHUNK' AND {acl_alias}.resource_id = {chunk_alias}.id)
          )
          AND ({principals_sql})
    )"""

    return clause, params
