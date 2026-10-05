"""Cancel a request's handler when its client goes away before the response
starts.

acquire can hold a request for minutes (queued, then booting). Without this,
a caller that gives up keeps its place in the queue and later boots an
emulator nobody will use. Cancelling the handler is enough: the lease engine
already turns a cancelled acquire into "leave the queue" or "end the lease as
cancelled and delete its Pod". Once the response has started (a grant was
sent) nothing is cancelled, so a booting grant always finishes booting.

Pure ASGI, not BaseHTTPMiddleware: it must own receive() to see the
disconnect while the app is busy and not reading.
"""

import asyncio
import logging

log = logging.getLogger(__name__)


class CancelOnDisconnect:
    def __init__(self, app, paths: tuple[str, ...]):
        self.app = app
        self.paths = paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith(self.paths):
            await self.app(scope, receive, send)
            return

        # Read the whole body up front, so every later receive() is ours and
        # can only mean "the client disconnected".
        body = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.append(message)
            if not message.get("more_body"):
                break

        replay = iter(body)
        disconnected = asyncio.Event()

        async def app_receive():
            for message in replay:
                return message
            await disconnected.wait()
            return {"type": "http.disconnect"}

        started = False

        async def app_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        handler = asyncio.ensure_future(self.app(scope, app_receive, app_send))

        async def watch():
            while (await receive())["type"] != "http.disconnect":
                pass
            disconnected.set()
            if not started:
                log.info("client left %s before a response; cancelling it", scope["path"])
                handler.cancel()

        watcher = asyncio.ensure_future(watch())
        try:
            await handler
        except asyncio.CancelledError:
            if not disconnected.is_set():
                raise  # the server itself is shutting down
        finally:
            watcher.cancel()
