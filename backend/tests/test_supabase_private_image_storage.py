from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.services.generation_result_storage import GenerationResultStorageError, calculate_sha256
from app.services.supabase_private_image_storage import (
    SupabasePrivateImageStorage,
    SupabaseStorageAdapterError,
    SupabaseStorageNotConfiguredError,
)


OWNER = UUID("11111111-1111-4111-8111-111111111111")
JOB = UUID("22222222-2222-4222-8222-222222222222")
PNG = b"\x89PNG\r\n\x1a\nprivate-storage-test"


def make_settings(**overrides):
    values = {
        "supabase_url": "https://project.supabase.co",
        "supabase_service_role_key": "sb_secret_server_only",
        "generation_storage_bucket": "studio-media",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_upload_verifies_private_bucket_object_metadata_and_downloaded_bytes():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            assert request.content == PNG
            assert request.headers["content-type"] == "image/png"
            assert request.headers["x-upsert"] == "false"
            return httpx.Response(200, json={"Key": f"studio-media/{OWNER}/generated/{JOB}.png"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"id": "studio-media", "public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        uploaded = await storage.upload_image(
            owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
        )

    assert uploaded.metadata.is_private is True
    assert uploaded.metadata.object_path == f"{OWNER}/generated/{JOB}.png"
    assert uploaded.metadata.sha256_hex == calculate_sha256(PNG)
    assert len(seen) == 4
    assert all("authorization" not in req.headers for req in seen)


@pytest.mark.asyncio
async def test_public_bucket_is_rejected_and_uploaded_object_cleanup_attempted():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": True})
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )
    assert any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_storage_byte_mismatch_is_rejected_and_cleaned_up():
    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG + b"tampered")
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


@pytest.mark.asyncio
async def test_missing_object_metadata_is_not_treated_as_success():
    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[])
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(SupabaseStorageAdapterError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


def test_storage_adapter_fails_closed_without_service_key():
    with pytest.raises(SupabaseStorageNotConfiguredError):
        SupabasePrivateImageStorage(
            Settings(supabase_url="https://project.supabase.co"),
            httpx.AsyncClient(),
        )
