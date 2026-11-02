# ruff: noqa: S105

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

# REST2 can neither create authentication tokens nor apply custom fields to a queue, so tests/rt_setup.pl prepares RT
# for the tests using them and prints a token, which is passed in the environment variable RT_TOKEN (see the script).
RT_TOKEN = os.environ.get('RT_TOKEN', '')
# custom field of the queue RT_QUEUE created by tests/rt_setup.pl, the quote and the space test the quoting
RT_CUSTOM_FIELD = "python-rt Test's Field"

requires_rt_setup = pytest.mark.skipif(not RT_TOKEN, reason='RT is not prepared by tests/rt_setup.pl (RT_TOKEN is not set)')


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
