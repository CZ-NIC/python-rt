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
