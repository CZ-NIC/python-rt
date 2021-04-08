"""Tests for the REST2 API client."""
from rt import rest2

from requests import Session


REST2_URL = "http://localhost/rt/REST/2.0/"


class TestRest2:
    """Group of test cases for the REST2 API client."""

    def test_rest2_constructor(self, monkeypatch):
        """All instance attributes are in place in a new instance."""
        monkeypatch.setattr(
            'rt.rest2.requests.sessions.default_headers', lambda: {})
        api = rest2.Rest2(REST2_URL)
        assert api.url == REST2_URL
        assert isinstance(api.session, Session)
        assert api.session.headers == {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Accept-Charset': 'utf-8'
        }
