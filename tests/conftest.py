# ruff: noqa: S105, SLF001

import os
import typing

import httpx2
import pytest

if typing.TYPE_CHECKING:
    import rt.rest2
    import rt.rest2_async

# blank setup defaults
RT_URL = 'http://localhost:8080/REST/2.0/'
RT_USER = 'root'
RT_PASSWORD = 'password'
RT_QUEUE = 'General'

# REST2 can neither create authentication tokens nor custom roles, so RT is prepared with tests/rt_initdata.pl for the
# tests using them and a token is created with the helper rt-token of the RT image; the token is passed in the
# environment variable RT_TOKEN (see tests/rt_initdata.pl).
RT_TOKEN = os.environ.get('RT_TOKEN', '')
# custom field of the queue RT_QUEUE created by tests/rt_initdata.pl, the quote and the space test the quoting
RT_CUSTOM_FIELD = "python-rt Test's Field"
# single value custom role of the queue RT_QUEUE created by tests/rt_initdata.pl
RT_CUSTOM_ROLE = 'python-rt Test Role'

requires_rt_setup = pytest.mark.skipif(not RT_TOKEN, reason='RT is not prepared by tests/rt_initdata.pl (RT_TOKEN is not set)')


@pytest.fixture(scope='session')
def rt_connection() -> 'rt.rest2.Rt':
    """Setup a generic connection."""
    import rt.rest2  # noqa: PLC0415

    return rt.rest2.Rt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), http_timeout=None)


@pytest.fixture(scope='session')
def async_rt_connection() -> 'rt.rest2_async.AsyncRt':
    """Setup a generic connection."""
    import rt.rest2_async  # noqa: PLC0415

    return rt.rest2_async.AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), http_timeout=None)


# The sync REST2 tests are generated from the async tests with unasyncd; they test the generated code of the sync client
# and are not run by default (see the marker "sync" in pyproject.toml).
_SYNC_TEST_FILES = frozenset({'test_basic.py', 'test_tickets.py', 'test_rest2_fixes.py', 'test_rest2_admin.py', 'test_rest2_messages.py'})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark the tests of the sync client with the marker "sync", and the tests which need a running RT with "live"."""
    for item in items:
        if item.path.name in _SYNC_TEST_FILES:
            item.add_marker(pytest.mark.sync)
        if {'async_rt_connection', 'rt_connection'} & set(getattr(item, 'fixturenames', ())) or item.path.name == 'test_rest1.py':
            item.add_marker(pytest.mark.live)


# --- messages of RT -----------------------------------------------------------------------------------------------
# The status messages RT returns in the live tests are recorded, to check at the end that the catalog of messages of the
# library (rt/_messages.py) knows all of them, see test_message_catalog.py. Responses of mocked clients are ignored.

LIVE_MESSAGES: set[str] = set()


@pytest.fixture(scope='session', autouse=True)
def record_messages_of_rt() -> typing.Iterator[None]:
    """Record the status messages RT returns; fail at the end of the session for messages which are not in the catalog."""
    import rt._rest2.transport  # noqa: PLC0415
    import rt._rest2_async.transport  # noqa: PLC0415
    from rt._messages import classify  # noqa: PLC0415

    def patch(client_class: type) -> typing.Callable[[], None]:
        original = client_class.__dict__['list_result']

        def patched(cls: type, response: typing.Any) -> list[str]:
            result: list[str] = original.__func__(cls, response)
            if 'Plack' in response.headers.get('server', ''):
                LIVE_MESSAGES.update(result)
            return result

        client_class.list_result = classmethod(patched)  # type: ignore[attr-defined]

        return lambda: setattr(client_class, 'list_result', original)

    restore = [patch(rt._rest2.transport._Transport), patch(rt._rest2_async.transport._AsyncTransport)]

    yield

    for undo in restore:
        undo()

    unknown = sorted(message for message in LIVE_MESSAGES if classify(message) is None and message not in KNOWN_UNRECOGNIZED_MESSAGES)
    if unknown:
        pytest.fail(f'These messages of RT are not in the catalog rt/_messages.py (add them with their kind): {unknown}', pytrace=False)


# Messages of RT of the tests which are deliberately not classified, as the values of the users in them make them ambiguous
KNOWN_UNRECOGNIZED_MESSAGES: frozenset[str] = frozenset()
