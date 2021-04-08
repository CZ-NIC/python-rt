"""
Python RESTful client for Request Tracker's REST2 :term:`API`.

Request Tracker implemented a version 2.0 of their :term:`REST` :term:`API`.
This version uses JSON as input and output format instead of a stream format
that was loosely based on email command formatting as was the case for version
1.0 of the :term:`API`.

Version 2.0 of the :term:`API` started out as an extension to Request Tracker
4.x: https://metacpan.org/release/RT-Extension-REST2

It was then included as core code into Request Tracker 5.x:
https://docs.bestpractical.com/rt/5.0.0/RT/REST2.html
"""

__license__ = """ Copyright (C) 2020 Gabriel Filion

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
__docformat__ = "reStructuredText en"


import requests


class Rest2:
    """Client to Request Tracker 4's REST API v2.0."""

    def __init__(self, url: str) -> None:
        """Initialize the API client.

        :param url: Base URL for Request Tracker API.
                    E.g.: http://tracker.example.com/rt/REST/2.0/

        v2 of the API defines two login methods that libraries should use:
            * HTTP Basic auth
            * Token (given that the RT::Authen::Token plugin is used)
        """
        self.url = url
        self.session = requests.Session()
        # All HTTP requests sent to the API should be using JSON to
        # communicate data to the API.
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Accept-Charset': 'utf-8'})
