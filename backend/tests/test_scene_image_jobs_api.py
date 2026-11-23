from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.auth import StudioUser, get_current_user
import app.main as main_module


def authenticated_user():
    return StudioUser(
        user_id="11111111-1111-4111-8111-111111111111",
        email="creator@example.test",
        role="creator",
    )


def test_scene_image_job_fails_closed_when_worker_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            generation_jobs_enabled=True,
            generation_job_worker_ready=False,
            image_generation_provider="chosen-provider",
            image_generation_model="chosen-model",
        ),
    )
    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        response = TestClient(app).post(
            "/api/scenes/22222222-2222-4222-8222-222222222222/image-jobs",
            headers={"Idempotency-Key": "scene-image-test-001"},
            json={"prompt": "A calm ocean at sunrise"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 503
    assert "worker is not ready" in response.json()["detail"]


def test_scene_image_job_fails_closed_without_selected_image_provider(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            generation_jobs_enabled=True,
            generation_job_worker_ready=True,
            image_generation_provider=None,
            image_generation_model=None,
        ),
    )
    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        response = TestClient(app).post(
            "/api/scenes/22222222-2222-4222-8222-222222222222/image-jobs",
            headers={"Idempotency-Key": "scene-image-test-002"},
            json={"prompt": "A calm ocean at sunrise"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 503
    assert "No image provider has been selected" in response.json()["detail"]


def test_scene_image_job_rejects_invalid_dimensions_before_submission():
    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        response = TestClient(app).post(
            "/api/scenes/22222222-2222-4222-8222-222222222222/image-jobs",
            headers={"Idempotency-Key": "scene-image-test-003"},
            json={"prompt": "A calm ocean at sunrise", "width": 1000},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422



def test_scene_image_job_requires_signed_quote_after_worker_readiness(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            generation_jobs_enabled=True,
            generation_job_worker_ready=True,
            image_generation_provider="chosen-provider",
            image_generation_model="chosen-model",
        ),
    )
    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        response = TestClient(app).post(
            "/api/scenes/22222222-2222-4222-8222-222222222222/image-jobs",
            headers={"Idempotency-Key": "scene-image-test-004"},
            json={"prompt": "A calm ocean at sunrise"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422
    assert "server-issued pricing quote" in response.json()["detail"]


def test_scene_image_job_uses_atomic_plan_admission(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID

    captured = {}

    def fake_admission(settings, **kwargs):
        captured.update(kwargs)
        quota = SimpleNamespace(
            feature_key="daily_image_generations",
            feature_limit=10,
            used_units=1,
            remaining_units=9,
            status="reserved",
        )
        return SimpleNamespace(
            job_id=UUID("33333333-3333-4333-8333-333333333333"),
            event_id=UUID("44444444-4444-4444-8444-444444444444"),
            hold_id=UUID("55555555-5555-4555-8555-555555555555"),
            available_credits=90,
            reserved_credits=10,
            created=True,
            replayed=False,
            quota_reservations=(quota,),
        )

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            generation_jobs_enabled=True,
            generation_job_worker_ready=True,
            image_generation_provider="chosen-provider",
            image_generation_model="chosen-model",
        ),
    )
    monkeypatch.setattr(main_module, "create_plan_credited_generation_job", fake_admission)
    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        response = TestClient(app).post(
            "/api/scenes/22222222-2222-4222-8222-222222222222/image-jobs",
            headers={"Idempotency-Key": "scene-image-test-005"},
            json={
                "prompt": "A calm ocean at sunrise",
                "quote_snapshot": {"schema": "server-issued"},
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 202
    assert captured["user_id"] == UUID("11111111-1111-4111-8111-111111111111")
    assert captured["job_type"] == "image_generation"
    assert captured["request_snapshot"]["quantity"] == 1
    assert captured["quote_snapshot"] == {"schema": "server-issued"}
    assert response.json()["hold_id"] == "55555555-5555-4555-8555-555555555555"
