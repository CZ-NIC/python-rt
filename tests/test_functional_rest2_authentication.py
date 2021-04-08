"""Test function of an actual login against a live RT instance.

This file aims to verify which different authentication methods work and which
don't. It will also help to track if an authentication method that's broken
will eventually be fixed in a certain RT version.

 * The tests in this file all require a live RT instance that can receive
   requests.
 * The tests also require that the credential information be valid for
   permitting login to the RT instance.

This file uses credentials that are valid for the docker image
netsandbox/request-tracker:4.4, so you can use this image to run tests
locally.
"""
import pytest

import requests
from urllib.parse import urljoin, quote


@pytest.fixture
def instance_info(scope="session"):
    """Information about instance under test."""
    return {
        "url": "http://localhost:8080/",
        "user": "root",
        "pass": "password",
        # XXX the docker instance does not provide a default token, so it
        # needs to be manually inserted into the database.
        "token": "1-14-85d105ea058f445f6b4cc5811e0079cb",
    }


class TestFunctionalRTAuthentication:
    """Try authenticating to a live instance using different methods.

    .. seealso:: https://docs.bestpractical.com/rt/5.0.0/RT/REST2.html#Authentication-Methods
    """  # noqa: E501

    def test_http_basic_auth(self, instance_info):
        """Use HTTP Basic Authentication to make an authenticated request."""
        API_URL = urljoin(instance_info["url"], "REST/2.0/rt")
        basic_auth = requests.auth.HTTPBasicAuth(
            instance_info["user"],
            instance_info["pass"]
        )

        r = requests.get(API_URL, auth=basic_auth)
        r.raise_for_status()

    def test_token_auth(self, instance_info):
        """Use a token to run an authenticated request to the API."""
        endpoint_url = urljoin(instance_info["url"], "REST/2.0/rt")
        prepared_token = quote(instance_info["token"])
        headers = {
            "Authorization": "token {}".format(prepared_token),
        }

        r = requests.get(endpoint_url, headers=headers)
        r.raise_for_status()

        assert len(r.json()) == 2

    def test_http_session_cookie_auth(self, instance_info):
        """Use the cookie of a session authenticated outside of the API.

        According to the API's documentation, this method is not recommended
        to be used. However, judging as to how HTTP Basic Authentication is
        currently broken, it is the only method we can use to authenticated
        without a token.
        """
        auth_url = urljoin(instance_info["url"], "NoAuth/Login.html")

        credentials = {
            "user": instance_info["user"],
            "pass": instance_info["pass"],
        }
        r = requests.post(auth_url, data=credentials)
        r.raise_for_status()

        assert len(dict(r.cookies)) == 1
