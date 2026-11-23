from uuid import UUID

from app.core.config import Settings
from app.services.support_inbox import add_message, create_ticket


USER = UUID("11111111-1111-4111-8111-111111111111")
TICKET = "33333333-3333-4333-8333-333333333333"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.content = b"{}" if payload is not None else b""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, *, params=None, json=None, headers=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        return FakeResponse(self.payload)


def settings():
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-secret",
    )


def test_create_ticket_uses_single_atomic_rpc_with_category_and_context(monkeypatch):
    import app.services.support_inbox as module

    fake = FakeClient([{"id": TICKET, "category": "bug", "status": "open"}])
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: fake)

    ticket = create_ticket(
        settings(),
        USER,
        "Save problem",
        "The project did not save.",
        category="bug",
        context={"page_path": "#movie"},
    )

    assert ticket["id"] == TICKET
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/rpc/create_support_ticket_with_message")
    assert call["json"] == {
        "p_user_id": str(USER),
        "p_subject": "Save problem",
        "p_body": "The project did not save.",
        "p_category": "bug",
        "p_context": {"page_path": "#movie"},
    }


def test_add_message_uses_one_atomic_rpc_for_each_sender_role(monkeypatch):
    import app.services.support_inbox as module

    for role in ("user", "admin"):
        fake = FakeClient(None)
        monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: fake)

        add_message(settings(), UUID(TICKET), USER, role, "A reply")

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["url"].endswith("/rpc/add_support_ticket_message")
        assert call["json"] == {
            "p_ticket_id": TICKET,
            "p_sender_user_id": str(USER),
            "p_sender_role": role,
            "p_body": "A reply",
        }


def test_add_message_rejects_unknown_sender_role_before_network(monkeypatch):
    import app.services.support_inbox as module

    fake = FakeClient(None)
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: fake)

    try:
        add_message(settings(), UUID(TICKET), USER, "owner", "A reply")
    except ValueError as exc:
        assert "sender role" in str(exc)
    else:
        raise AssertionError("Unknown sender role was accepted")

    assert fake.calls == []
