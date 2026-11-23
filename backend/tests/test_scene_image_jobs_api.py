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
