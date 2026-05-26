from types import SimpleNamespace

import pytest

from src.api.middleware import request_id_middleware


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers = {}


class FakeRequest:
    def __init__(self, request_id: str | None = None) -> None:
        self.headers = Headers()
        if request_id:
            self.headers["X-Request-ID"] = request_id
        self.state = SimpleNamespace()
        self.method = "GET"
        self.url = SimpleNamespace(path="/api/health")
        self.client = SimpleNamespace(host="127.0.0.1")


@pytest.mark.anyio
async def test_request_id_generated() -> None:
    request = FakeRequest()

    response = await request_id_middleware(request, lambda _: FakeResponse())

    assert response.headers["X-Request-ID"].startswith("req_")
    assert request.state.request_id == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_request_id_preserved() -> None:
    request = FakeRequest("req_custom_123")

    response = await request_id_middleware(request, lambda _: FakeResponse())

    assert response.headers["X-Request-ID"] == "req_custom_123"


@pytest.mark.anyio
async def test_process_time_header_included() -> None:
    response = await request_id_middleware(FakeRequest(), lambda _: FakeResponse())

    assert float(response.headers["X-Process-Time"]) >= 0


@pytest.mark.anyio
async def test_status_code_is_preserved() -> None:
    response = await request_id_middleware(FakeRequest(), lambda _: FakeResponse(404))

    assert response.status_code == 404


@pytest.mark.anyio
async def test_middleware_reraises_exceptions() -> None:
    async def failing_call_next(_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await request_id_middleware(FakeRequest("req_error"), failing_call_next)
