"""Tests for the private Storage delete primitive."""
import unittest
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_cleanup import MediaCleanupPlan
from app.services.media_storage_delete import delete_private_media_object

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
OBJECT = "33333333-3333-4333-8333-333333333333"
PATH = f"{OWNER}/characters/{ASSET}/{OBJECT}.png"


def settings():
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="eyJserver.secret")


def plan(**changes):
    values = dict(owner_id=OWNER, asset_id=ASSET, bucket="studio-media", storage_path=PATH)
    values.update(changes)
    return MediaCleanupPlan(**values)


class MediaStorageDeleteTests(unittest.TestCase):
    @patch("app.services.media_storage_delete.httpx.delete")
    def test_deletes_exact_server_planned_private_object(self, delete):
        delete.return_value = Mock(status_code=200)
        delete_private_media_object(settings(), plan())
        args, kwargs = delete.call_args
        self.assertEqual(args[0], f"https://example.supabase.co/storage/v1/object/studio-media/{PATH}")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJserver.secret")

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_missing_object_is_idempotent_success(self, delete):
        delete.return_value = Mock(status_code=404)
        self.assertIsNone(delete_private_media_object(settings(), plan()))

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_rejects_forged_bucket_or_path_before_network(self, delete):
        for forged in (plan(bucket="public"), plan(storage_path=f"{OWNER}/../../secret.png")):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                delete_private_media_object(settings(), forged)
        delete.assert_not_called()

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_storage_timeout_is_retryable_service_unavailable(self, delete):
        import httpx
        delete.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(settings(), plan())
        self.assertEqual(raised.exception.status_code, 503)

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_permanent_storage_rejection_is_gateway_error(self, delete):
        import httpx
        response = Mock(status_code=403)
        request = httpx.Request("DELETE", "https://example.supabase.co/storage/v1/object/studio-media/test")
        delete.return_value = response
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "forbidden", request=request, response=httpx.Response(403, request=request)
        )
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(settings(), plan())
        self.assertEqual(raised.exception.status_code, 502)

    def test_connection_drop_after_delete_is_safe_to_retry_as_404(self):
        class Handler(BaseHTTPRequestHandler):
            def do_DELETE(self):
                self.server.calls += 1
                self.server.last_path = self.path
                self.server.last_authorization = self.headers.get("Authorization")
                if self.server.calls == 1:
                    # Simulate Storage committing the delete and the response
                    # being lost before the client receives confirmation.
                    self.server.object_exists = False
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.calls = 0
        server.object_exists = True
        server.last_path = None
        server.last_authorization = None
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        local_settings = Settings(
            supabase_url=f"http://127.0.0.1:{server.server_port}",
            supabase_service_role_key="eyJserver.secret",
        )
        try:
            with self.assertRaises(HTTPException) as raised:
                delete_private_media_object(local_settings, plan())
            self.assertEqual(raised.exception.status_code, 503)
            self.assertIsNone(delete_private_media_object(local_settings, plan()))
            self.assertFalse(server.object_exists)
            self.assertEqual(server.calls, 2)
            self.assertEqual(
                server.last_path,
                f"/storage/v1/object/studio-media/{PATH}",
            )
            self.assertEqual(server.last_authorization, "Bearer eyJserver.secret")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_requires_server_credentials(self, delete):
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(Settings(), plan())
        self.assertEqual(raised.exception.status_code, 503)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
