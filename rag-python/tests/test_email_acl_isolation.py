"""Security tests for Email ACL isolation, per-message permissions, and BCC leak prevention."""

from app.connectors.email.fixture_adapter import EmailFixtureAdapter
from app.normalization.email_normalizer import EmailNormalizer
from app.security.acl import has_read_permission


def test_demo_identity_and_group_mapping():
    adapter = EmailFixtureAdapter()
    item = adapter.fetch_item("email:carol.security@company.internal:msg-103-inbox")
    assert item is not None
    acls = adapter.extract_acl(item)

    # Sender: employee_carol
    # Mailbox owner: employee_carol
    # To: employee_42, employee_bob
    # Cc: group_engineering
    principals = {(a.principal_type.value, a.principal_id) for a in acls}
    assert ("USER", "employee_carol") in principals
    assert ("USER", "employee_42") in principals
    assert ("USER", "employee_bob") in principals
    assert ("GROUP", "group_engineering") in principals


def test_unknown_and_external_recipients_deny_by_default():
    adapter = EmailFixtureAdapter()
    # msg-401 from vendor@partner.com, cc contractor99@company.internal
    item = adapter.fetch_item("email:alex.engineer@company.internal:msg-401-inbox")
    assert item is not None
    acls = adapter.extract_acl(item)

    # Neither vendor@partner.com nor contractor99@company.internal is in demo registries
    principals = {(a.principal_type.value, a.principal_id) for a in acls}
    assert ("USER", "vendor") not in principals
    assert ("USER", "contractor99") not in principals

    # Deny by default: vendor and contractor cannot read
    assert not has_read_permission(acls, user_id="vendor", group_ids=[])
    assert not has_read_permission(acls, user_id="contractor99", group_ids=[])

    # Mailbox owner Alex can read
    assert has_read_permission(acls, user_id="employee_42", group_ids=[])


def test_per_message_thread_acl_isolation():
    adapter = EmailFixtureAdapter()

    # Message 1: Alice to Bob only
    item1 = adapter.fetch_item("email:bob.architect@company.internal:msg-101-inbox")
    assert item1 is not None
    acls1 = adapter.extract_acl(item1)

    assert has_read_permission(acls1, user_id="employee_42", group_ids=[])
    assert has_read_permission(acls1, user_id="employee_bob", group_ids=[])
    # Carol is NOT in Message 1
    assert not has_read_permission(acls1, user_id="employee_carol", group_ids=[])

    # Message 2: Bob replies and adds Carol
    item2 = adapter.fetch_item("email:bob.architect@company.internal:msg-102-inbox")
    assert item2 is not None
    acls2 = adapter.extract_acl(item2)

    assert has_read_permission(acls2, user_id="employee_42", group_ids=[])
    assert has_read_permission(acls2, user_id="employee_bob", group_ids=[])
    # Carol is now authorized on Message 2
    assert has_read_permission(acls2, user_id="employee_carol", group_ids=[])
    # But Carol still has NO access to Message 1!
    assert not has_read_permission(acls1, user_id="employee_carol", group_ids=[])

    # Message 3: Carol Cc's group_engineering
    item3 = adapter.fetch_item("email:carol.security@company.internal:msg-103-inbox")
    assert item3 is not None
    acls3 = adapter.extract_acl(item3)

    # General engineer who is only in group_engineering
    assert has_read_permission(acls3, user_id="other_eng", group_ids=["group_engineering"])
    # General engineer cannot read Message 1 or Message 2
    assert not has_read_permission(acls1, user_id="other_eng", group_ids=["group_engineering"])
    assert not has_read_permission(acls2, user_id="other_eng", group_ids=["group_engineering"])


def test_bcc_three_copies_permissions_and_serialized_isolation():
    adapter = EmailFixtureAdapter()
    normalizer = EmailNormalizer()

    # 1. Sent Copy: Sender ONLY
    sent_item = adapter.fetch_item("email:alex.engineer@company.internal:msg-201-sent")
    assert sent_item is not None
    sent_acls = adapter.extract_acl(sent_item)

    assert has_read_permission(sent_acls, user_id="employee_42", group_ids=[])
    # Bob and Dave must NOT have access to Alice's sent record
    assert not has_read_permission(sent_acls, user_id="employee_bob", group_ids=[])
    assert not has_read_permission(sent_acls, user_id="employee_dave", group_ids=[])

    # 2. Bob's Inbox Copy: Sender + Bob
    bob_item = adapter.fetch_item("email:bob.architect@company.internal:msg-201-inbox")
    assert bob_item is not None
    bob_acls = adapter.extract_acl(bob_item)

    assert has_read_permission(bob_acls, user_id="employee_42", group_ids=[])
    assert has_read_permission(bob_acls, user_id="employee_bob", group_ids=[])
    # Dave must NOT have access to Bob's copy
    assert not has_read_permission(bob_acls, user_id="employee_dave", group_ids=[])

    # 3. Dave's BCC Inbox Copy: Sender + Dave
    dave_item = adapter.fetch_item("email:dave.intern@company.internal:msg-201-inbox")
    assert dave_item is not None
    dave_acls = adapter.extract_acl(dave_item)

    assert has_read_permission(dave_acls, user_id="employee_42", group_ids=[])
    assert has_read_permission(dave_acls, user_id="employee_dave", group_ids=[])
    # Bob must NOT have access to Dave's copy
    assert not has_read_permission(dave_acls, user_id="employee_bob", group_ids=[])

    # 4. Serialized Leakage Verification:
    # Bob's copy must not contain any trace of Dave's BCC address, ID, or any BCC field at all
    bob_raw_json = bob_item.model_dump_json()
    assert "dave.intern" not in bob_raw_json
    assert "employee_dave" not in bob_raw_json
    assert "bcc" not in bob_raw_json.lower()

    bob_doc = normalizer.normalize(bob_item, bob_acls)
    bob_doc_json = bob_doc.model_dump_json()
    assert "dave.intern" not in bob_doc_json
    assert "employee_dave" not in bob_doc_json
    assert "bcc" not in bob_doc_json.lower()


def test_shared_folder_acl():
    adapter = EmailFixtureAdapter()
    item = adapter.fetch_item("email:alex.engineer@company.internal:msg-301-finance")
    assert item is not None
    acls = adapter.extract_acl(item)

    # Finance group can read
    assert has_read_permission(acls, user_id="some_user", group_ids=["group_finance"])
    # Engineering group cannot read
    assert not has_read_permission(acls, user_id="some_user", group_ids=["group_engineering"])
