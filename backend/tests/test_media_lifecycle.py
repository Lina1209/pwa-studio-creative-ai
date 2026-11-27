"""Tests for the pure media lifecycle state machine."""
import unittest

from app.services.media_lifecycle import (
    MediaLifecycle, MediaStatus, transition_media_status,
)


class MediaLifecycleTests(unittest.TestCase):
    def test_pending_upload_is_never_readable(self):
        self.assertFalse(MediaLifecycle(MediaStatus.PENDING_UPLOAD).is_readable)

    def test_only_ready_is_readable(self):
        for status in MediaStatus:
            self.assertEqual(
                MediaLifecycle(status).is_readable,
                status is MediaStatus.READY,
            )

    def test_successful_upload_requires_verification_before_ready(self):
        self.assertEqual(
            transition_media_status(MediaStatus.PENDING_UPLOAD, MediaStatus.OBJECT_UPLOADED),
            MediaStatus.OBJECT_UPLOADED,
        )
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.PENDING_UPLOAD, MediaStatus.READY)

    def test_verified_object_can_become_ready(self):
        self.assertEqual(
            transition_media_status(MediaStatus.OBJECT_UPLOADED, MediaStatus.READY),
            MediaStatus.READY,
        )

    def test_upload_failure_cannot_become_ready(self):
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.UPLOAD_FAILED, MediaStatus.READY)

    def test_ready_asset_must_become_unavailable_before_delete(self):
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.READY, MediaStatus.DELETED)
        self.assertEqual(
            transition_media_status(MediaStatus.READY, MediaStatus.CLEANUP_PENDING),
            MediaStatus.CLEANUP_PENDING,
        )

    def test_cleanup_pending_can_only_finish_as_deleted(self):
        lifecycle = MediaLifecycle(MediaStatus.CLEANUP_PENDING)
        self.assertTrue(lifecycle.needs_cleanup)
        self.assertEqual(
            transition_media_status(MediaStatus.CLEANUP_PENDING, MediaStatus.DELETED),
            MediaStatus.DELETED,
        )
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.CLEANUP_PENDING, MediaStatus.READY)

    def test_same_state_transition_is_idempotent(self):
        self.assertEqual(
            transition_media_status(MediaStatus.READY, MediaStatus.READY),
            MediaStatus.READY,
        )

    def test_deleted_is_terminal(self):
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.DELETED, MediaStatus.READY)
        with self.assertRaises(ValueError):
            transition_media_status(MediaStatus.DELETED, MediaStatus.CLEANUP_PENDING)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValueError):
            transition_media_status("unknown", MediaStatus.READY)


if __name__ == "__main__":
    unittest.main()
