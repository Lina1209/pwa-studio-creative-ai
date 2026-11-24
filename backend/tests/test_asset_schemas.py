import pytest
from pydantic import ValidationError

from app.asset_schemas import (
    AssetListQuery,
    AssetSafeResponse,
    AssetUploadInitRequest,
    ProjectAssetAttachRequest,
)


ASSET_ID = "11111111-1111-4111-8111-111111111111"


def test_upload_init_accepts_matching_image_metadata():
    payload = AssetUploadInitRequest(
        kind="image", filename="storyboard.webp",
        mime_type="image/webp", size_bytes=1024,
    )
    assert payload.filename == "storyboard.webp"
    assert payload.mime_type == "image/webp"


@pytest.mark.parametrize("filename", ["../secret.txt", "folder/file.png", "folder\\file.png", "..", ""])
def test_upload_init_rejects_path_like_or_empty_filename(filename):
    with pytest.raises(ValidationError):
        AssetUploadInitRequest(
            kind="image", filename=filename,
            mime_type="image/png", size_bytes=100,
        )


def test_upload_init_rejects_mismatched_media_kind_and_mime_type():
    with pytest.raises(ValidationError, match="does not match"):
        AssetUploadInitRequest(
            kind="image", filename="movie.mp4",
            mime_type="video/mp4", size_bytes=100,
        )


def test_upload_init_rejects_mime_parameters_and_spaces():
    with pytest.raises(ValidationError):
        AssetUploadInitRequest(
            kind="audio", filename="track.mp3",
            mime_type="audio/mpeg; charset=utf-8", size_bytes=100,
        )


def test_project_attach_requires_uuid_and_allowlisted_role():
    payload = ProjectAssetAttachRequest(asset_id=ASSET_ID, role="soundtrack")
    assert str(payload.asset_id) == ASSET_ID
    assert payload.position == 0


def test_project_attach_rejects_unknown_role_and_extra_owner_id():
    with pytest.raises(ValidationError):
        ProjectAssetAttachRequest(asset_id=ASSET_ID, role="admin_override")
    with pytest.raises(ValidationError):
        ProjectAssetAttachRequest(
            asset_id=ASSET_ID, role="soundtrack",
            owner_id="22222222-2222-4222-8222-222222222222",
        )


def test_asset_list_query_bounds_page_size_and_allowlists_filters():
    assert AssetListQuery(limit=100, kind="video").limit == 100
    with pytest.raises(ValidationError):
        AssetListQuery(limit=1000)
    with pytest.raises(ValidationError):
        AssetListQuery(status="public")


def test_asset_safe_response_has_no_storage_path_field():
    payload = AssetSafeResponse(
        id=ASSET_ID, kind="image", status="ready",
        display_name="Reference", mime_type="image/webp",
        size_bytes=100, created_at="2026-11-24T00:00:00Z",
        updated_at="2026-11-24T00:00:00Z",
    )
    assert not hasattr(payload, "storage_path")
    assert not hasattr(payload, "signed_url")
