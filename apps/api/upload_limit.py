"""Bound the entire streamed multipart request before Starlette spools it to disk."""

from solution_copilot.config import get_settings
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class UploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/api/v1/documents"
        ):
            return await self.app(scope, receive, send)
        limit = get_settings().upload_max_bytes + 1024 * 1024
        count = 0

        async def bounded():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > limit:
                # Starlette closes temporary upload files for MultiPartException.
                raise MultiPartException("Upload exceeds limit")
            return message

        async def bounded_send(message):
            if count > limit:
                if message["type"] == "http.response.start":
                    response = JSONResponse(
                        {"error": {"code": "FILE_TOO_LARGE", "message": "文件超过上传大小限制。"}},
                        status_code=413,
                    )
                    await response(scope, receive, send)
                return
            await send(message)

        await self.app(scope, bounded, bounded_send)
