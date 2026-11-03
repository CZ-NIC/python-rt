"""Python interface to Request Tracker :term:`API`.

Description of Request Tracker :term:`REST` :term:`API`:
https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html
"""

import logging
import types
import typing

import httpx2

from rt._rest2_async.articles import AsyncArticles, AsyncClasses
from rt._rest2_async.assets import AsyncAssets, AsyncCatalogs
from rt._rest2_async.custom_fields import AsyncCustomFields, AsyncCustomRoles
from rt._rest2_async.groups import AsyncGroups
from rt._rest2_async.queues import AsyncQueues
from rt._rest2_async.rights import AsyncRights
from rt._rest2_async.tickets import AsyncTickets
from rt._rest2_async.transport import _AsyncTransport
from rt._rest2_async.users import AsyncUsers

__license__ = """ Copyright (C) 2012 CZ.NIC, z.s.p.o.
    Copyright (c) 2015 Genome Research Ltd.
    Copyright (c) 2017 CERT Gouvernemental (GOVCERT.LU)

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
__docformat__ = 'reStructuredText en'
__authors__ = [
    '"Jiri Machalek" <jiri.machalek@nic.cz>',
    '"Joshua C. randall" <jcrandall@alum.mit.edu>',
    '"Georges Toth" <georges.toth@govcert.etat.lu>',
]


class AsyncRt:
    """:term:`API` for Request Tracker according to
    https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html. Interface is based on
    :term:`REST` architecture, which is based on HTTP/1.1 protocol. This module
    is therefore mainly sending and parsing special HTTP messages.

    The client can be used as a context manager, which closes the underlying HTTP
    connections when leaving the context::

        async with AsyncRt(url='https://tracker.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('user', 'password')) as tracker:
            ticket = await tracker.tickets.get(1)

    The methods are grouped by the objects of RT in attributes of the client, e.g. :py:attr:`tickets`, :py:attr:`users` or
    :py:attr:`queues`, which are instances of the classes :py:class:`AsyncTickets`, :py:class:`AsyncUsers`,
    :py:class:`AsyncQueues` etc.::

        ticket = await tracker.tickets.get(1)
        await tracker.tickets.tickets.comment(1, 'Looking into it')
        async for found in tracker.tickets.tickets.search(queue='General', Status='new'):
            ...

    .. warning:: The client targets the latest version of RT (6.0) and is tested with it.
                 Older versions of RT are not tested.

    .. note:: Use only ASCII LF (line feed) as newline. Time is returned in UTC.
              All strings returned are encoded in UTF-8 and the same is
              expected as input for string values.
    """

    tickets: AsyncTickets
    """Tickets, their history, messages, attachments and links, and the actions on them."""

    users: AsyncUsers
    """Users."""

    groups: AsyncGroups
    """Groups."""

    queues: AsyncQueues
    """Queues."""

    assets: AsyncAssets
    """Assets."""

    catalogs: AsyncCatalogs
    """Catalogs of assets."""

    articles: AsyncArticles
    """Articles."""

    classes: AsyncClasses
    """Classes of articles."""

    custom_fields: AsyncCustomFields
    """Custom fields and their values."""

    custom_roles: AsyncCustomRoles
    """Custom roles."""

    rights: AsyncRights
    """Rights."""

    def __init__(
        self,
        *,
        url: str,
        proxy: str | None = None,
        verify_cert: str | bool = True,
        http_auth: httpx2.Auth | None = None,
        token: str | None = None,
        http_timeout: float | None = 20,
        per_page: int = 100,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        """API initialization.

        :param url: Base URL for Request Tracker API.
                      E.g.: http://tracker.example.com/REST/2.0/
        :param proxy: Proxy server (string with http://user:password@host/ syntax)
        :param verify_cert: Verify the server certificate (``True``/``False``) or path
                            to a CA bundle file to verify against.
        :param http_auth: Specify a http authentication instance, e.g. httpx2.BasicAuth(), httpx2.DigestAuth(),
                            etc. to be used for authenticating to RT
        :param token: Optional authentication token to be used instead of basic authentication.
        :param http_timeout: HTTP timeout in seconds after which a request is aborted.
        :param per_page: Number of items to request per page for results which are split into pages
                         by RT (e.g. search results). The maximum supported by RT is 100.
        :param client: Optional HTTP client to use, e.g. configured with a custom transport, retries,
                       event hooks or HTTP/2. Its settings and authentication are used as they are, so
                       `proxy`, `verify_cert`, `http_auth`, `token` and `http_timeout` must not be specified.
                       The client is owned by the caller and therefore not closed by :py:meth:`aclose`.

        :raises InvalidUseError: If the specified `url` or `per_page` is invalid, both `http_auth` and `token` are
                            specified, or connection settings are specified together with `client`.
        """
        self._t = _AsyncTransport(
            logger=logging.getLogger(__name__),
            url=url,
            proxy=proxy,
            verify_cert=verify_cert,
            http_auth=http_auth,
            token=token,
            http_timeout=http_timeout,
            per_page=per_page,
            client=client,
        )

        self.tickets = AsyncTickets(self._t)
        self.users = AsyncUsers(self._t)
        self.groups = AsyncGroups(self._t)
        self.queues = AsyncQueues(self._t)
        self.assets = AsyncAssets(self._t)
        self.catalogs = AsyncCatalogs(self._t)
        self.articles = AsyncArticles(self._t)
        self.classes = AsyncClasses(self._t)
        self.custom_fields = AsyncCustomFields(self._t)
        self.custom_roles = AsyncCustomRoles(self._t)
        self.rights = AsyncRights(self._t)

    @property
    def url(self) -> str:
        """Base URL of the REST2 API of RT, with a trailing slash."""
        return self._t.url

    @property
    def per_page(self) -> int:
        """Number of items requested per page for results which are split into pages by RT."""
        return self._t.per_page

    @property
    def session(self) -> httpx2.AsyncClient:
        """The underlying HTTP client."""
        return self._t.session

    @property
    def logger(self) -> logging.Logger:
        """The logger of the client; the requests and responses are logged with the level debug."""
        return self._t.logger

    async def aclose(self) -> None:
        """Close the underlying HTTP client and its connections.

        The client can not be used anymore afterwards. An HTTP client passed to the
        constructor is not closed, as it is owned by the caller.
        """
        await self._t.aclose()

    async def __aenter__(self) -> typing.Self:
        """Enter the context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        """Leave the context manager and close the underlying HTTP client."""
        await self.aclose()

    async def get_system_info(self) -> dict[str, typing.Any]:
        """Get information about the RT system.

        .. note:: Requires RT 5.0.0 or newer.

        :returns: Dictionary with the RT version and the installed plugins, e.g.
                  ``{'Version': '6.0.4', 'Plugins': []}``.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', 'rt'))
