# ruff: noqa: S105

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
