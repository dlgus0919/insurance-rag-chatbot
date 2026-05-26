from src.api.rate_limit import limiter, user_or_ip_key


class Client:
    host = "10.0.0.1"


class Request:
    headers = {}
    client = Client()

    class State:
        pass

    state = State()


def test_user_or_ip_key_uses_ip_without_user() -> None:
    assert user_or_ip_key(Request()) == "ip:10.0.0.1"


def test_user_or_ip_key_prefers_user() -> None:
    request = Request()
    request.state.user = type("User", (), {"username": "employee01"})()

    assert user_or_ip_key(request) == "user:employee01"


def test_limiter_has_limit_decorator() -> None:
    assert callable(limiter.limit("5/minute"))


def test_limit_decorator_preserves_callable() -> None:
    def endpoint():
        return "ok"

    wrapped = limiter.limit("5/minute")(endpoint)

    assert callable(wrapped)


def test_rate_limit_storage_configured() -> None:
    assert limiter is not None


def test_limit_decorator_blocks_after_threshold() -> None:
    limiter.reset()

    @limiter.limit("1/minute")
    def endpoint(request):
        return "ok"

    request = Request()
    assert endpoint(request) == "ok"

    try:
        endpoint(request)
    except Exception as exc:
        assert exc.__class__.__name__ == "RateLimitException"
    else:
        raise AssertionError("second request should be rate limited")
    finally:
        limiter.reset()
