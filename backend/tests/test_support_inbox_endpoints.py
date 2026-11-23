from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
TICKET = "33333333-3333-4333-8333-333333333333"

def client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def teardown_function():
    app.dependency_overrides.clear()

def test_user_cannot_read_another_users_support_ticket(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "get_ticket", lambda *a: {"id":TICKET,"user_id":OTHER,"status":"open"})
    monkeypatch.setattr(main, "list_messages", lambda *a: (_ for _ in ()).throw(AssertionError("messages must not be read")))
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.get(f"/api/support/tickets/{TICKET}")
    assert response.status_code == 404

def test_user_can_read_only_owned_ticket(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "get_ticket", lambda *a: {"id":TICKET,"user_id":OWNER,"status":"open"})
    monkeypatch.setattr(main, "list_messages", lambda *a: [{"body":"hello"}])
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.get(f"/api/support/tickets/{TICKET}")
    assert response.status_code == 200
    assert response.json()["messages"][0]["body"] == "hello"

def test_admin_support_inbox_requires_admin(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "list_tickets", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not query inbox")))
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.get("/api/admin/support/tickets")
    assert response.status_code == 403

def test_support_ticket_create_trims_text_and_uses_verified_user(monkeypatch):
    import app.main as main
    captured={}
    monkeypatch.setattr(main, "create_ticket", lambda *a, **k: captured.update(user_id=a[1],subject=a[2],body=a[3],category=k["category"],context=k["context"]) or {"id":TICKET})
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: "audit")
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.post("/api/support/tickets",json={"subject":"  Help  ","message":"  Please help  ","category":"bug","context":{"page_path":"#account"}})
    assert response.status_code == 201
    assert captured == {"user_id":UUID(OWNER),"subject":"Help","body":"Please help","category":"bug","context":{"page_path":"#account"}}

def test_support_message_rejects_extra_fields():
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.post(f"/api/support/tickets/{TICKET}/messages",json={"message":"hello","sender_user_id":OTHER})
    assert response.status_code == 422



def test_support_ticket_rejects_unknown_category():
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.post("/api/support/tickets",json={"subject":"Help","message":"Please help","category":"root"})
    assert response.status_code == 422


def test_support_ticket_context_rejects_unapproved_fields():
    client=client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response=client.post("/api/support/tickets",json={"subject":"Help","message":"Please help","context":{"email":"private@example.com"}})
    assert response.status_code == 422


def test_notifications_are_scoped_to_authenticated_user(monkeypatch):
    import app.main as main
    captured = {}
    monkeypatch.setattr(main, "list_notifications", lambda settings, user_id, **kwargs:
        captured.update(user_id=user_id) or [{"id":"n1","read_at":None}])
    client = client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response = client.get("/api/notifications")
    assert response.status_code == 200
    assert captured["user_id"] == UUID(OWNER)
    assert response.json()["unread_count"] == 1


def test_user_cannot_mark_another_users_notification_read(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "mark_notification_read", lambda *args: 0)
    client = client_for(StudioUser(user_id=OWNER,email=None,role="creator"))
    response = client.patch(f"/api/notifications/{TICKET}/read")
    assert response.status_code == 404
