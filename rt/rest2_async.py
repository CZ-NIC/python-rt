"""Python interface to Request Tracker :term:`API`.

Description of Request Tracker :term:`REST` :term:`API`:
https://developer.bestpractical.com/rt/6.0.4/RT/REST2.html
"""

import collections.abc
import datetime as dt
import json
import logging
import re
import ssl
import types
import typing
from urllib.parse import urljoin

import httpx2

from .common import (
    _CORRESPOND_ACTIONS,
    _QUEUE_FIELDS,
    _REDACTED_HEADERS,
    _USER_FIELDS,
    REGEX_PATTERNS,
    VALID_CONTENT_TYPES,
    VALID_TICKET_LINK_NAMES,
    Attachment,
    ContentType,
    JSONInput,
    JSONValue,
    QueryParams,
    SearchFormat,
    TicketLinkName,
    _build_ticket_query,
    _check_fields,
    _CorrespondAction,
    _fields_params,
    _path,
    _search_fields_params,
)
from .exceptions import AuthorizationError, BadRequestError, InvalidUseError, NotFoundError, RtConnectionError, UnexpectedResponseError

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
    https://developer.bestpractical.com/rt/6.0.4/RT/REST2.html. Interface is based on
    :term:`REST` architecture, which is based on HTTP/1.1 protocol. This module
    is therefore mainly sending and parsing special HTTP messages.

    The client can be used as a context manager, which closes the underlying HTTP
    connections when leaving the context::

        async with AsyncRt(url='https://tracker.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('user', 'password')) as tracker:
            ticket = await tracker.get_ticket(1)

    .. warning:: You need at least version 5.0.2 of RT.

    .. note:: Use only ASCII LF (line feed) as newline. Time is returned in UTC.
              All strings returned are encoded in UTF-8 and the same is
              expected as input for string values.
    """

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

        :raises ValueError: If the specified `url` or `per_page` is invalid, both `http_auth` and `token` are
                            specified, or connection settings are specified together with `client`.
        """
        self.logger = logging.getLogger(__name__)

        # ensure trailing slash
        if not url.endswith('/'):
            url = f'{url}/'

        if not url.endswith('REST/2.0/'):
            raise ValueError('Invalid REST URL specified, please use a form of https://example.com/REST/2.0/')

        if http_auth is not None and token is not None:
            raise ValueError('Specify either http_auth or token, but not both.')

        if not 1 <= per_page <= 100:
            raise ValueError('per_page must be between 1 and 100 (the maximum supported by RT).')

        self.url = url
        self.per_page = per_page

        if client is not None:
            connection_settings_specified = proxy is not None or verify_cert is not True or http_auth is not None or token is not None or http_timeout != 20
            if connection_settings_specified:
                raise ValueError('proxy, verify_cert, http_auth, token and http_timeout can not be used together with client, configure the client instead.')

            self.session = client
            # the client is owned by the caller, who is responsible for closing it
            self._close_session = False
        else:
            if isinstance(verify_cert, bool):
                ssl_verify: ssl.SSLContext | bool = verify_cert
            elif isinstance(verify_cert, str):
                ssl_verify = ssl.create_default_context(cafile=verify_cert)
            else:
                ssl_verify = True

            self.session = httpx2.AsyncClient(timeout=http_timeout, verify=ssl_verify, proxy=proxy, auth=http_auth)
            self._close_session = True

            if token is not None:  # pragma: no cover  # no way to add tests for this with the current docker image
                self.session.headers['Authorization'] = f'token {token}'

    async def aclose(self) -> None:
        """Close the underlying HTTP client and its connections.

        The client can not be used anymore afterwards. An HTTP client passed to the
        constructor is not closed, as it is owned by the caller.
        """
        if self._close_session:
            await self.session.aclose()

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

    def _debug_response(self, response: httpx2.Response) -> None:
        """Log a request and its response for debugging.

        Credentials in the request headers are redacted and the request body is not logged,
        as it may contain passwords (e.g. when creating or editing users).
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        request = response.request
        headers = {}
        for name, value in request.headers.items():
            if name.lower() in _REDACTED_HEADERS:
                headers[name] = '[redacted]'
            else:
                headers[name] = value

        self.logger.debug('### %s', dt.datetime.now(tz=dt.UTC).isoformat())
        self.logger.debug('Request URL: %s', request.url)
        self.logger.debug('Request method: %s', request.method)
        self.logger.debug('Request headers: %s', headers)
        self.logger.debug('Response status code: %s', response.status_code)
        self.logger.debug('Response content: %s', response.text)

    async def _send(
        self,
        method: typing.Literal['GET', 'POST', 'PUT', 'DELETE'],
        selector: str,
        *,
        params: QueryParams | None = None,
        json_data: JSONInput = None,
        attachments: typing.Sequence[Attachment] | None = None,
    ) -> httpx2.Response:
        """Send a request to the :term:`API` and check the response for errors.

        :param method: HTTP method of the request.
        :param selector: End part of URL which completes self.url parameter
                           set during class initialization.
                           E.g.: ``ticket/123456/show``
        :param params: Query parameters to add to the URL.
        :param json_data: Data to send as JSON request body.
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects. If given, the request
                            is sent as multipart/form-data with *json_data* in the ``JSON`` field.

        :returns: The response, which has a successful status code.
        :raises BadRequestError: If the server returned an HTTP/400 error.
        :raises AuthorizationError: Credentials are invalid or missing.
        :raises NotFoundError: Resource was not found.
        :raises UnexpectedResponseError: Server returned an unexpected status code.
        :raises RtConnectionError: In case of a connection or transport error.
        """
        url = urljoin(self.url, selector)

        # RT rejects PUT requests without a JSON content type, even if they have no body (e.g. take/untake/steal).
        headers = None
        if method in ('PUT', 'DELETE'):
            headers = {'Content-Type': 'application/json'}

        try:
            if attachments:
                files = [('Attachments', attachment.multipart_form_element()) for attachment in attachments]
                response = await self.session.request(
                    method,
                    url,
                    params=params,
                    data={'JSON': json.dumps(json_data)},
                    files=files,
                )
            else:
                response = await self.session.request(method, url, params=params, headers=headers, json=json_data)
        except httpx2.ConnectError as exc:
            raise RtConnectionError('Connection error', exc) from exc
        except httpx2.TransportError as exc:
            raise RtConnectionError('Transport error', exc) from exc

        self._debug_response(response)
        self._check_response(response)

        return response

    @staticmethod
    def _check_response(response: httpx2.Response) -> None:
        """Search general errors in server response and raise exceptions when found.

        :param response: Response from HTTP request.
        :raises BadRequestError: If the server returned an HTTP/400 error.
        :raises AuthorizationError: Credentials are invalid or missing.
        :raises NotFoundError: Resource was not found.
        :raises UnexpectedResponseError: Server returned an unexpected status code.
        """
        status_code = response.status_code

        if status_code == 400:
            try:
                result = response.json()
            except ValueError:
                result = 'Bad request'

            if isinstance(result, dict):
                raise BadRequestError(result.get('message', response.text))

            raise BadRequestError(result)

        if status_code == 401:
            raise AuthorizationError('Server could not verify that you are authorized to access the requested document.')

        if status_code == 404:
            raise NotFoundError('No such resource found.')

        # 204 (No Content) is returned when deleting resources
        if status_code not in (200, 201, 204):
            raise UnexpectedResponseError(
                f'Received status code {status_code} instead of 200.',
                status_code=status_code,
                response_message=response.text,
            )

    @staticmethod
    def _decode_json(response: httpx2.Response) -> JSONValue:
        """Decode the JSON body of a response.

        :raises UnexpectedResponseError: If the body is not valid JSON, e.g. an HTML page returned by a proxy.
        """
        try:
            # json.loads() is typed to return Any, but always returns JSON data
            return typing.cast('JSONValue', response.json())
        except ValueError as exc:  # json.JSONDecodeError and UnicodeDecodeError are subclasses of ValueError
            raise UnexpectedResponseError(
                f'Received an invalid JSON response: {exc}',
                status_code=response.status_code,
                response_message=response.text,
            ) from exc

    @classmethod
    def _dict_result(cls, response: httpx2.Response) -> dict[str, JSONValue]:
        """Return the JSON body of a response, which must be a dictionary.

        :raises UnexpectedResponseError: If the body is not a JSON object.
        """
        result = cls._decode_json(response)

        if not isinstance(result, dict):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        return result

    @classmethod
    def _list_result(cls, response: httpx2.Response) -> list[str]:
        """Return the JSON body of a response, which must be a list of strings (e.g. status messages).

        :raises UnexpectedResponseError: If the body is not a JSON array of strings.
        """
        result = cls._decode_json(response)

        if not isinstance(result, list):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        messages = []
        for message in result:
            if not isinstance(message, str):
                raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)
            messages.append(message)

        return messages

    @staticmethod
    def _created_id(result: dict[str, JSONValue]) -> str:
        """Return the ID of an object created by RT, which is returned as string.

        :raises UnexpectedResponseError: If the result does not contain an ID.
        """
        object_id = result.get('id')

        if not isinstance(object_id, (str, int)):
            raise UnexpectedResponseError(f'Response does not contain the ID of the created object: {result}')

        return str(object_id)

    async def _delete(self, selector: str) -> None:
        """Send a DELETE request to the :term:`API`.

        :param selector: End part of URL which completes self.url parameter
                           set during class initialization.
                           E.g.: ``ticket/123456``
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('DELETE', selector)

        # RT confirms a deletion with 204 (No Content). Any other successful response must
        # still be valid JSON, so e.g. an HTML page returned by a proxy is not taken as success.
        if response.status_code != 204:
            self._decode_json(response)

    async def _paged_request(
        self,
        selector: str,
        json_data: JSONInput = None,
        params: QueryParams | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, JSONValue]]:
        """Request all pages of a paginated :term:`API` result.

        :param selector: End part of URL which completes self.url parameter
                           set during class initialization.
                           E.g.: ``ticket/123456/show``
        :param json_data: JSON request (e.g. search filter) to send to the API. If set, the request
                          is sent as POST, otherwise as GET.
        :param params: Query parameters to add to the URL.

        :returns: Iterator over the items of all pages.
        :raises UnexpectedResponseError: If the response is not a paginated result.
        :raises RtConnectionError: In case of connection error.
        """
        method: typing.Literal['GET', 'POST'] = 'GET' if json_data is None else 'POST'
        page = 1
        per_page = self.per_page

        while True:
            # copy the parameters, so the dictionary passed by the caller is not modified
            page_params = {**(params or {}), 'page': page, 'per_page': per_page}
            result = self._dict_result(await self._send(method, selector, params=page_params, json_data=json_data))

            items = result.get('items')
            pages = result.get('pages')
            if not isinstance(items, list) or not (pages is None or isinstance(pages, int)):
                raise UnexpectedResponseError('Server returned an unexpected result', response_message=str(result))

            page_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise UnexpectedResponseError('Server returned an unexpected result', response_message=str(result))
                page_items.append(item)

            # RT returns the last page again if a page after the last one is requested
            # (e.g. if items were deleted meanwhile), so stop instead of returning items twice.
            if result.get('page', page) != page:
                return

            for item in page_items:
                yield item

            if pages is not None:
                # The number of pages is known if the user is allowed to see all results.
                if page >= pages:
                    return
            elif not page_items and not result.get('next_page'):
                # The number of pages is unknown (RT >= 5.0.5 for users not allowed to see all results),
                # so continue until a page is empty and RT does not announce a next page.
                return

            # RT may limit the number of items per page, so use the effective value for the following pages.
            effective_per_page = result.get('per_page')
            if isinstance(effective_per_page, int):
                per_page = effective_per_page
            page += 1

    @staticmethod
    def _validate_date(date: str) -> bool:
        """Check whether the specified date starts with a valid date in the supported format (YYYY-MM-DD)."""
        match = re.match(r'\d{4}-\d{2}-\d{2}', date)
        if match is None:
            return False

        try:
            parsed_date = dt.date.fromisoformat(match.group(0))
        except ValueError:
            return False

        return 1970 < parsed_date.year < 2100

    def new_correspondence(self, queue: str | None = None) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed by other users than the system one.

        :param queue: Queue where to search

        :returns: Iterator of tickets which were last updated by another user than
                  the system one, ordered in decreasing order by LastUpdated.
                  Each ticket is dictionary, the same as in
                  :py:meth:`~AsyncRt.get_ticket`.
        """
        return self.search(queue=queue, order='-LastUpdated')

    def last_updated(
        self,
        since: str | dt.date | dt.datetime,
        queue: str | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed after given date.

        :param since: Date and optionally time after which the tickets were changed:

                      - :py:class:`datetime.datetime` with timezone: exact point in time.
                      - :py:class:`datetime.datetime` without timezone, :py:class:`datetime.date` or
                        string in form '2011-02-24', optionally followed by a time, e.g. '2011-02-24 13:45:00':
                        interpreted by RT in the timezone of the RT user (or the default timezone of RT).
        :param queue: Queue where to search

        :returns: Iterator of tickets with LastUpdated parameter later than
                  *since* ordered in decreasing order by LastUpdated.
                  Each ticket is a dictionary, the same as in
                  :py:meth:`~AsyncRt.get_ticket`.

        :raises InvalidUseError: If the specified date is of an unsupported format.
        """
        since_value = self._date_to_string(since)
        if not self._validate_date(since_value):
            raise InvalidUseError(f'Invalid date specified - "{since}"')

        return self.search(queue=queue, order='-LastUpdated', LastUpdated__gt=since_value)

    @staticmethod
    def _date_to_string(date: str | dt.date | dt.datetime) -> str:
        """Convert a date or datetime to a string as understood by RT in TicketSQL queries."""
        if isinstance(date, dt.datetime):
            if date.utcoffset() is not None:
                # RT only respects the timezone of a time in ISO 8601 format in UTC (with suffix "Z")
                return date.astimezone(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
            return date.strftime('%Y-%m-%d %H:%M:%S')

        if isinstance(date, dt.date):
            return date.isoformat()

        return date

    async def search(
        self,
        queue: str | None = None,
        order: str | None = None,
        raw_query: str | None = None,
        query_format: SearchFormat | list[str] | dict[str, str] = 'l',
        **kwargs: object,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search arbitrary needles in given fields and queue.

        Example::

            >>> tracker = AsyncRt(url='http://tracker.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('rt-username', 'top-secret'))
            >>> tickets = list(tracker.search(CF_Domain='example.com', Subject__like='warning'))
            >>> tickets = list(tracker.search(queue='General', order='Status', raw_query="id='1'+OR+id='2'+OR+id='3'"))

        :param queue:      Queue where to search. If you wish to search across
                           all of your queues, pass None as the argument.
        :param order:      Name of field sorting result list, for descending
                           order put - before the field name. E.g. -Created
                           will put the newest tickets at the beginning
        :param raw_query:  A raw query to provide to RT if you know what
                             you are doing. You may still pass Queue and order
                             kwargs, so use these instead of including them in
                             the raw query. You can refer to the RT query builder.
                             If passing raw_query, all other ``**kwargs`` will be ignored.
                             The raw query is passed to RT as is, so never include
                             untrusted input in it.
        :param query_format: Format of the query:

                               - i: only *id* fields are populated
                               - s: only *id* and *subject* fields are populated
                               - l: multi-line format, all fields are populated
                               - [field1, field2]: list of fields to be populated
        :param kwargs:     Other arguments possible to set if not passing raw_query:

                             Requestors, Subject, Cc, AdminCc, Owner, Status,
                             Priority, InitialPriority, FinalPriority,
                             TimeEstimated, Starts, Due, Text,... (according to RT
                             fields)

                             Custom fields CF.{<CustomFieldName>} could be set
                             with keywords CF_CustomFieldName.

                             To alter lookup operators you can append one of the
                             following endings to each keyword:

                             __exact          for operator = (default)
                             __notexact       for operator !=
                             __gt             for operator >
                             __gte            for operator >=
                             __lt             for operator <
                             __lte            for operator <=
                             __like           for operator LIKE
                             __notlike        for operator NOT LIKE
                             __startswith     for operator STARTSWITH
                             __notstartswith  for operator NOT STARTSWITH
                             __endswith       for operator ENDSWITH
                             __notendswith    for operator NOT ENDSWITH
                             __is             for operator IS (value must be None or 'NULL')
                             __isnot          for operator IS NOT (value must be None or 'NULL')

                             E.g. ``Resolved__isnot=None`` finds resolved tickets.
                             A field name containing ``__`` must be followed by an
                             operator, e.g. ``CF_my__field__exact='value'``.

                             Setting values to keywords constrain search
                             result to the tickets satisfying all of them.

                             Values are quoted, so they can not change the
                             meaning of the query.

        :returns: Iterator over matching tickets. Each ticket is the same dictionary
                  as in :py:meth:`~AsyncRt.get_ticket`.
        :raises BadRequestError: If the query is malformed.
        :raises InvalidUseError: If an unsupported operator is used.
        """
        get_params: dict[str, str | int] = {'query': _build_ticket_query(queue, raw_query, kwargs)}

        if order:
            if order.startswith('-'):
                get_params['orderby'] = order[1:]
                get_params['order'] = 'DESC'
            else:
                get_params['orderby'] = order

        get_params.update(_search_fields_params(query_format))

        async for item in self._paged_request('tickets', params=get_params):
            yield item

    async def get_ticket(self, ticket_id: str | int, query_format: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Fetch ticket by its ID.

        :param ticket_id: ID of demanded ticket
        :param query_format: Returned fields to be populated

        :returns: Dictionary with key, value pairs for ticket with
                  *ticket_id*. List of keys (when query_format is None):

                      * id
                      * numerical_id
                      * Queue
                      * Owner
                      * Creator
                      * Subject
                      * Status
                      * Priority
                      * InitialPriority
                      * FinalPriority
                      * Requestors
                      * Cc
                      * AdminCc
                      * Created
                      * Starts
                      * Started
                      * Due
                      * Resolved
                      * Told
                      * TimeEstimated
                      * TimeWorked
                      * TimeLeft
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        """
        if not query_format:
            query_format = {}

        response = await self._send('GET', _path('ticket', ticket_id), params={'fields[Queue]': 'Name', **query_format})

        return self._dict_result(response)

    async def create_ticket(
        self,
        queue: str,
        content_type: ContentType = 'text/plain',
        subject: str | None = None,
        content: str | None = None,
        attachments: typing.Sequence[Attachment] | None = None,
        **kwargs: JSONInput,
    ) -> int:
        """Create new ticket and set given parameters.

        Example of message sent to ``http://tracker.example.com/REST/2.0/ticket/new``::

            { "Queue": "General",
              "Subject": "Ticket created through REST API",
              "Owner": "Nobody",
              "Requestor": "somebody@example.com",
              "Cc": "user2@example.com",
              "CustomRoles": {"My Role": "staff1@example.com"},
              "Content": "Lorem Ipsum",
              "CustomFields": {"Severity": "Low"}
            }

        :param queue: Queue where to create ticket
        :param content_type: Content-type of the Content parameter; can be either text/plain or text/html.
        :param subject: Optional subject for the ticket.
        :param content: Optional content of the ticket. Must be specified unless attachments are specified.
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :param kwargs: Other arguments possible to set:

                         Requestor, Cc, AdminCc, Owner, Status,
                         Priority, InitialPriority, FinalPriority,
                         TimeEstimated, Starts, Due

        :returns: ID of new ticket
        :raises ValueError: If the `content_type` is not of a supported format.
        """
        if content_type not in VALID_CONTENT_TYPES:
            raise ValueError('Invalid content-type specified.')

        ticket_data: dict[str, JSONInput] = {'Queue': queue}

        if subject is not None:
            ticket_data['Subject'] = subject

        if content is not None:
            ticket_data['Content'] = content
            ticket_data['ContentType'] = content_type

        ticket_data.update(kwargs)

        response = await self._send('POST', 'ticket', json_data=ticket_data, attachments=attachments)

        return int(self._created_id(self._dict_result(response)))

    async def edit_ticket(self, ticket_id: str | int, **kwargs: JSONInput) -> bool:
        """Edit ticket values.

        :param ticket_id: ID of ticket to edit
        :param kwargs: Fields to set, e.g. Requestor, Subject, Cc, AdminCc, Owner, Status,
                       Priority, InitialPriority, FinalPriority, TimeEstimated, Starts, Due
                       (according to RT fields). Custom fields can be set as dictionary, e.g.
                       ``CustomFields={'Severity': 'Low'}``. RT ignores unknown fields.
        :returns: ``True``, unless RT returned an empty status message.
        :raises NotFoundError: If the ticket, or a user or queue set in *kwargs*, does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id), json_data=kwargs))

        if not msg:
            return True

        for message in msg:
            if REGEX_PATTERNS['does_not_exist'].search(message):
                raise NotFoundError(message)

        return bool(msg[0])

    async def get_ticket_history(self, ticket_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get set of short history items.

        :param ticket_id: ID of ticket
        :returns: Iterator of history items ordered increasingly by time of event.
                  Each history item is a dictionary with the keys Type, Creator,
                  Created, Description and _hyperlinks.
        """
        async for transaction in self._paged_request(
            _path('ticket', ticket_id, 'history'),
            params={
                'fields': 'Type,Creator,Created,Description,_hyperlinks',
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
            },
        ):
            yield transaction

    async def get_transaction(self, transaction_id: str | int) -> dict[str, typing.Any]:
        """Get a transaction.

        :param transaction_id: ID of transaction
        :returns: The transaction as dictionary.
        :raises UnexpectedResponseError: If the response from RT is not as expected,
                                         e.g. if the transaction does not exist (RT returns status code 500).
        """
        response = await self._send('GET', _path('transaction', transaction_id), params={'fields': 'Description'})

        return self._dict_result(response)

    async def _correspond(
        self,
        ticket_id: str | int,
        content: str = '',
        action: _CorrespondAction = 'correspond',
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
    ) -> list[str]:
        """Sends out the correspondence.

        :param ticket_id: ID of ticket to which message belongs
        :param content: Content of email message
        :param action: correspond or comment
        :param content_type: Content type of email message, defaults to text/plain. Alternative is text/html.
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :returns: List of messages returned by the backend related to the executed action.
        :raises BadRequestError: When ticket does not exist
        :raises InvalidUseError: If the `action` parameter is invalid
        :raises ValueError: If the `content_type` is not of a supported format.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        if action not in _CORRESPOND_ACTIONS:
            raise InvalidUseError('action must be either "correspond" or "comment"')

        if content_type not in VALID_CONTENT_TYPES:
            raise ValueError('Invalid content-type specified.')

        post_data: dict[str, JSONInput] = {
            'Content': content,
            'ContentType': content_type,
        }

        # Adding a one-shot cc/bcc is not supported by RT5.0.2
        # if cc:
        #     post_data['Cc'] = cc  # noqa: ERA001
        #
        # if bcc:
        #     post_data['Bcc'] = bcc  # noqa: ERA001

        response = await self._send('POST', _path('ticket', ticket_id, action), json_data=post_data, attachments=attachments)

        return self._list_result(response)

    async def reply(
        self,
        ticket_id: str | int,
        content: str = '',
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
    ) -> bool:
        """Sends email message to the contacts in ``Requestors`` field of
        given ticket with subject as is set in ``Subject`` field.

        :param ticket_id: ID of ticket to which message belongs
        :param content: Content of email message (text/plain or text/html)
        :param content_type: Content type of email message, default to text/plain
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :returns: ``True``
                      Operation was successful
                  ``False``
                      RT returned an empty status message
        :raises BadRequestError: When ticket does not exist
        :raises ValueError: If the `content_type` is not of a supported format.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = await self._correspond(ticket_id, content, 'correspond', content_type, attachments)

        if not msg:
            raise UnexpectedResponseError(str(msg))

        return bool(msg[0])

    async def delete_ticket(self, ticket_id: str | int) -> None:
        """Mark a ticket as deleted.

        :param ticket_id: ID of ticket
        :raises NotFoundError: If the ticket does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('ticket', ticket_id))

    async def comment(
        self,
        ticket_id: str | int,
        content: str = '',
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
    ) -> bool:
        """Adds comment to the given ticket.

        :param ticket_id: ID of ticket to which comment belongs
        :param content: Content of comment
        :param content_type: Content type of comment, default to text/plain
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :returns: ``True``
                      Operation was successful
                  ``False``
                      RT returned an empty status message
        :raises BadRequestError: When ticket does not exist
        :raises ValueError: If the `content_type` is not of a supported format.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = await self._correspond(ticket_id, content, 'comment', content_type, attachments)

        if not msg:
            raise UnexpectedResponseError(str(msg))

        return bool(msg[0])

    async def get_attachments(
        self,
        ticket_id: str | int,
        query_filter: list[dict[str, str]] | None = None,
        query_format: str | list[str] | dict[str, str] | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get attachment list for a given ticket.

        Example of a return result:

        .. code-block:: json

            [
                {
                    "id": "17",
                    "Filename": "README.rst",
                    "ContentLength": "3578",
                    "type": "attachment",
                    "ContentType": "test/plain",
                    "_url": "http://localhost:8080/REST/2.0/attachment/17"
                }
            ]

        :param ticket_id: ID of ticket
        :param query_filter: JSON search filter, defaults to "filename is not empty"
        :param query_format: Returned fields to be populated
        :returns: Iterator of attachments belonging to given ticket.
        """
        if query_filter is None:
            query_filter = [{'field': 'Filename', 'operator': 'IS NOT', 'value': ''}]

        get_params = _fields_params(query_format, default_fields='Filename,ContentType,ContentLength')

        async for item in self._paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=query_filter,
            params=get_params,
        ):
            yield item

    async def get_attachments_ids(
        self,
        ticket_id: str | int,
        query_filter: list[dict[str, str]] | None = None,
    ) -> collections.abc.AsyncIterator[int]:
        """Get IDs of attachments for given ticket.

        :param ticket_id: ID of ticket
        :param query_filter: JSON search filter, defaults to "filename is not empty"
        :returns: Iterator of IDs (type int) of attachments belonging to given
                  ticket.
        """
        if query_filter is None:
            query_filter = [{'field': 'Filename', 'operator': 'IS NOT', 'value': ''}]

        async for item in self._paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=query_filter,
        ):
            attachment_id = item.get('id')
            if not isinstance(attachment_id, (str, int)):
                raise UnexpectedResponseError(f'Attachment without ID: {item}')
            yield int(attachment_id)

    async def get_attachment(self, attachment_id: str | int) -> dict[str, typing.Any]:
        """Get attachment.

        :param attachment_id: ID of attachment to fetch
        :returns: Attachment as dictionary with these keys:

                      * Transaction
                      * ContentType
                      * Parent
                      * Creator
                      * Created
                      * Filename
                      * Content (base64 encoded string)
                      * Headers
                      * MessageId
                      * ContentEncoding
                      * id
                      * Subject

                  All these fields are strings, just 'Headers' holds another
                  dictionary with attachment headers as strings e.g.:

                      * Delivered-To
                      * From
                      * Return-Path
                      * Content-Length
                      * To
                      * X-Seznam-User
                      * X-QM-Mark
                      * Domainkey-Signature
                      * RT-Message-ID
                      * X-RT-Incoming-Encryption
                      * X-Original-To
                      * Message-ID
                      * X-Spam-Status
                      * In-Reply-To
                      * Date
                      * Received
                      * X-Country
                      * X-Spam-Checker-Version
                      * X-Abuse
                      * MIME-Version
                      * Content-Type
                      * Subject

                  Set of headers available depends on mailservers sending
                  emails not on Request Tracker!

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If attachment with specified ID does not exist.
        """
        return self._dict_result(await self._send('GET', _path('attachment', attachment_id)))

    async def get_user(self, user_id: int | str) -> dict[str, typing.Any]:
        """Get user details.

        :param user_id: Identification of user by username (str) or user ID
                        (int)
        :returns: User details as strings in dictionary with these keys for RT
                  users:

                      * Lang
                      * RealName
                      * Privileged
                      * Disabled
                      * Gecos
                      * EmailAddress
                      * Password
                      * id
                      * Name

                  Or these keys for external users (e.g. Requestors) replying
                  to email from RT:

                      * RealName
                      * Disabled
                      * EmailAddress
                      * Password
                      * id
                      * Name

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If the user does not exist.
        """
        return self._dict_result(await self._send('GET', _path('user', user_id)))

    async def user_exists(self, user_id: int | str, privileged: bool = True) -> bool:
        """Check if a given user exists.

        :param user_id: Identification of user by username (str) or user ID (int).
        :param privileged: If set to True, only return True if the user exists and is privileged.
        :returns: ``True`` if the user exists (and is privileged, if requested), else ``False``.
        """
        try:
            user = await self.get_user(user_id)
        except NotFoundError:
            return False

        if not privileged:
            return True

        # RT returns the privileged flag as number; compare as string to also support string values
        return str(user.get('Privileged', 0)) == '1'

    async def create_user(self, user_name: str, email_address: str, **kwargs: JSONInput) -> str:
        """Create user.

        :param user_name: Username (login for privileged, required)
        :param email_address: Email address (required)
        :param kwargs: Optional fields to set (see edit_user)
        :returns: ID of new user
        :raises BadRequestError: When user already exists
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _USER_FIELDS)

        post_data: dict[str, JSONInput] = {
            'Name': user_name,
            'EmailAddress': email_address,
            **kwargs,
        }

        response = await self._send('POST', 'user', json_data=post_data)

        return self._created_id(self._dict_result(response))

    async def edit_user(self, user_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit user profile.

        :param user_id: Identification of user by username (str) or user ID
                        (int)
        :param kwargs: Other fields to edit from the following list:

                          * Name
                          * Password
                          * EmailAddress
                          * RealName
                          * Nickname
                          * Gecos
                          * Organization
                          * Address1
                          * Address2
                          * City
                          * State
                          * Zip
                          * Country
                          * HomePhone
                          * WorkPhone
                          * MobilePhone
                          * PagerPhone
                          * ContactInfo
                          * Comments
                          * Signature
                          * Lang
                          * EmailEncoding
                          * WebEncoding
                          * ExternalContactInfoId
                          * ContactInfoSystem
                          * ExternalAuthId
                          * AuthSystem
                          * Privileged
                          * Disabled

        :returns: List of status messages
        :raises BadRequestError: When user does not exist
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _USER_FIELDS)

        return self._list_result(await self._send('PUT', _path('user', user_id), json_data=kwargs))

    async def delete_user(self, user_id: str | int) -> None:
        """Disable a user.

        :param user_id: Identification of a user by name (str) or ID (int)
        :raises NotFoundError: If the user does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('user', user_id))

    async def get_queue(self, queue_id: str | int) -> dict[str, typing.Any]:
        """Get queue details.

        Example of a return result:

        .. code-block:: json

            {
                "LastUpdatedBy": {
                    "_url": "http://localhost:8080/REST/2.0/user/RT_System",
                    "type": "user",
                    "id": "RT_System"
                },
                "LastUpdated": "2022-03-06T04:53:38Z",
                "AdminCc": [],
                "SortOrder": "0",
                "CorrespondAddress": "",
                "Creator": {
                    "id": "RT_System",
                    "_url": "http://localhost:8080/REST/2.0/user/RT_System",
                    "type": "user"
                },
                "Lifecycle": "default",
                "Cc": [],
                "Created": "2022-03-06T04:53:38Z",
                "_hyperlinks": [
                    {
                        "_url": "http://localhost:8080/REST/2.0/queue/1",
                        "type": "queue",
                        "id": 1,
                        "ref": "self"
                    },
                    {
                        "ref": "history",
                        "_url": "http://localhost:8080/REST/2.0/queue/1/history"
                    },
                    {
                        "ref": "create",
                        "type": "ticket",
                        "_url": "http://localhost:8080/REST/2.0/ticket?Queue=1"
                    }
                ],
                "SLADisabled": "1",
                "Name": "General",
                "TicketCustomFields": [],
                "Disabled": "0",
                "TicketTransactionCustomFields": [],
                "CustomFields": [],
                "Description": "The default queue",
                "CommentAddress": "",
                "id": 1
            }

        :param queue_id: Identification of queue by name (str) or queue ID
                         (int)
        :returns: Queue details as a dictionary

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: In case the queue does not exist
        """
        return self._dict_result(await self._send('GET', _path('queue', queue_id)))

    async def get_all_queues(self, include_disabled: bool = False) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Return a list of all queues.

        Example of a return result:

        .. code-block:: json

            [
                {
                    "InitialPriority": "",
                    "_url": "http://localhost:8080/REST/2.0/queue/1",
                    "type": "queue",
                    "Name": "General",
                    "DefaultDueIn": "",
                    "Description": "The default queue",
                    "CorrespondAddress": "",
                    "CommentAddress": "",
                    "id": "1",
                    "FinalPriority": ""
                }
            ]

        :param include_disabled: Set to True to also return disabled queues.

        :returns: Iterator of dictionaries containing basic information on all queues.

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int] = {
            'fields': 'Name,Description,CorrespondAddress,CommentAddress,InitialPriority,FinalPriority,DefaultDueIn',
            'find_disabled_rows': int(include_disabled),
        }
        async for item in self._paged_request('queues/all', params=params):
            yield item

    async def edit_queue(self, queue_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit queue.

        :param queue_id: Identification of queue by name (str) or ID (int)
        :param kwargs: Other fields to edit from the following list:

                          * Name
                          * Description
                          * CorrespondAddress
                          * CommentAddress
                          * Disabled
                          * SLADisabled
                          * Lifecycle
                          * SortOrder

        :returns: List of status messages
        :raises BadRequestError: When queue does not exist
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _QUEUE_FIELDS)

        return self._list_result(await self._send('PUT', _path('queue', queue_id), json_data=kwargs))

    async def create_queue(self, name: str, **kwargs: JSONInput) -> int:
        """Create queue.

        :param name: Queue name (required)
        :param kwargs: Optional fields to set (see edit_queue)
        :returns: ID of new queue
        :raises BadRequestError: When queue already exists
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _QUEUE_FIELDS)

        response = await self._send('POST', 'queue', json_data={'Name': name, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def delete_queue(self, queue_id: str | int) -> None:
        """Disable a queue.

        :param queue_id: Identification of queue by name (str) or ID (int)
        :raises NotFoundError: If the queue does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('queue', queue_id))

    async def get_links(self, ticket_id: str | int) -> list[dict[str, str]]:
        """Gets the ticket links for a single ticket.

        Example of a return result:

        .. code-block:: json

            [
                {
                    "id": "13",
                    "type": "ticket",
                    "_url": "http://localhost:8080/REST/2.0/ticket/13",
                    "ref": "depends-on"
                }
            ]

        :param ticket_id: ticket ID
        :returns: Links as lists of strings in dictionary with these keys
                  (just those which are defined):

                        * depends-on
                        * depended-on-by
                        * parent
                        * child
                        * refers-to
                        * referred-to-by
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        ticket = await self.get_ticket(ticket_id)

        return [link for link in ticket['_hyperlinks'] if link.get('type', '') == 'ticket' and link['ref'] != 'self']

    async def edit_link(
        self,
        ticket_id: str | int,
        link_name: TicketLinkName,
        link_value: str | int,
        delete: bool = False,
    ) -> bool:
        """Creates or deletes a link between the specified tickets.

        :param ticket_id: ID of ticket to edit
        :param link_name: Name of link to edit ('Parent', 'Child', 'RefersTo',
                          'ReferredToBy', 'DependsOn', 'DependedOnBy')
        :param link_value: Either ticket ID or external link.
        :param delete: if True the link is deleted instead of created
        :returns: ``True``; errors are raised as exceptions.
        :raises NotFoundError: If the ticket or the linked ticket does not exist.
        :raises InvalidUseError: If the link name is not supported or RT does not allow the link,
                                 e.g. to a deleted ticket.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if link_name not in VALID_TICKET_LINK_NAMES:
            raise InvalidUseError(f'Unsupported link name. Use one of "{", ".join(VALID_TICKET_LINK_NAMES)}".')

        if delete:
            json_data = {f'Delete{link_name}': link_value}
        else:
            json_data = {f'Add{link_name}': link_value}

        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id), json_data=json_data))

        if msg:
            if msg[0].startswith("Couldn't resolve"):
                raise NotFoundError(msg[0])
            if 'not allowed' in msg[0]:
                raise InvalidUseError(msg[0])

        return True

    async def merge_ticket(self, ticket_id: str | int, into_id: str | int) -> bool:
        """Merge ticket into another.

        :param ticket_id: ID of ticket to be merged
        :param into_id: ID of destination ticket
        :returns: ``True`` if the tickets were merged, ``False`` if RT did not merge them,
                  e.g. because the destination ticket does not exist or the user does not
                  have the ModifyTicket right.
        :raises NotFoundError: If the ticket to be merged does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id), json_data={'MergeInto': into_id}))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        return msg[0].lower() == 'merge successful'

    async def _change_owner(self, ticket_id: str | int, action: typing.Literal['take', 'untake', 'steal']) -> bool:
        """Take, untake or steal a ticket.

        :param ticket_id: ID of ticket
        :param action: The action to execute
        :returns: ``True`` if RT confirmed the change of the owner.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id, action)))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        return msg[0].lower().startswith('owner changed')

    async def take(self, ticket_id: str | int) -> bool:
        """Take ticket.

        :param ticket_id: ID of ticket to be taken
        :returns: ``True`` if the owner was changed, ``False`` if RT did not change it,
                  e.g. because the user does not have the TakeTicket right.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'take')

    async def untake(self, ticket_id: str | int) -> bool:
        """Untake ticket.

        :param ticket_id: ID of ticket to be untaken
        :returns: ``True`` if the owner was changed, ``False`` if RT did not change it,
                  e.g. because the user does not own the ticket.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'untake')

    async def steal(self, ticket_id: str | int) -> bool:
        """Steal ticket.

        :param ticket_id: ID of ticket to be stolen
        :returns: ``True`` if the owner was changed, ``False`` if RT did not change it,
                  e.g. because the user does not have the StealTicket right.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'steal')

    async def get_catalog(self, catalog_id: str | int) -> dict[str, typing.Any]:
        """Get catalog.

        :param catalog_id: Identification of catalog by name (str) or ID (int).
        :returns: Catalog as dictionary with these keys:

                      * id
                      * Name
                      * Description
                      * Lifecycle
                      * Disabled
                      * Contact
                      * HeldBy
                      * Created
                      * Creator
                      * LastUpdated
                      * LastUpdatedBy
                      * _hyperlinks

        :raises NotFoundError: If the catalog does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('catalog', catalog_id)))

    async def get_asset(self, asset_id: str | int, query_format: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get asset.

        :param asset_id: Asset ID.
        :param query_format: Returned fields to be populated.
        :returns: Asset as dictionary, with these keys if *query_format* is None:

                      * id
                      * Name
                      * Description
                      * Catalog
                      * Status
                      * Owner
                      * Lifecycle
                      * Disabled
                      * Contact
                      * HeldBy
                      * CustomFields
                      * Created
                      * Creator
                      * LastUpdated
                      * LastUpdatedBy
                      * _hyperlinks

        :raises NotFoundError: If the asset does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if not query_format:
            query_format = {}

        return self._dict_result(await self._send('GET', _path('asset', asset_id), params=query_format))

    async def create_asset(self, name: str, catalog: str | int, **kwargs: JSONInput) -> int:
        """Create a new asset in a catalog.

        :param name: Asset name.
        :param catalog: Catalog name or ID.
        :param kwargs: Other fields to set, e.g. Description, Status, CustomFields, RefersTo.
        :returns: ID of the new asset.
        :raises BadRequestError: If RT rejects the request as invalid.
        :raises UnexpectedResponseError: If the response from RT is not as expected, e.g. if the catalog
                                         does not exist (RT returns status code 403).
        """
        response = await self._send('POST', 'asset', json_data={'Name': name, 'Catalog': catalog, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_asset(self, asset_id: str | int, **kwargs: JSONInput) -> bool:
        """Edit an existing asset.

        :param asset_id: Asset ID.
        :param kwargs: Fields to set, e.g. Name, Description, Status, CustomFields, RefersTo.
        :returns: ``True`` if RT returned status messages, ``False`` if it returned an unexpected response.
        :raises NotFoundError: If the asset does not exist.
        """
        response = await self._send('PUT', _path('asset', asset_id), json_data=kwargs)

        return isinstance(self._decode_json(response), list)

    async def search_assets(
        self,
        catalog_id: str | int | None = None,
        search_params: collections.abc.Sequence[collections.abc.Mapping[str, JSONInput]] | None = None,
        query_format: str | list[str] | dict[str, str] | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search assets in a catalog.

        Example::

            >>> client = AsyncRt(...)
            >>> await client.search_assets(1, [{"field": "Name", "value": "NameOfMyAsset"}], "Owner,Status")
            >>> await client.search_assets(1, [{"field": "Name", "value": "NameOfMyAsset"}], ["Owner", "Status"])
            >>> await client.search_assets(1, [{"field": "Name", "value": "NameOfMyAsset"}], {"fields": "Owner,Status", "fields[Owner]": "id,Name"})

        The following is returned for each asset by default (when `query_format` is `None`)::

            {
                'Description': '',
                'id': '1',
                '_url': 'http://localhost:8080/REST/2.0/asset/1',
                'Owner': {'_url': 'http://localhost:8080/REST/2.0/user/Nobody', 'id': 'Nobody', 'type': 'user'},
                'Status': 'new',
                'type': 'asset'
            }

        :param catalog_id: Catalog ID. Use `None` to search all catalogs.
        :param search_params: Params used to filter the results. Each param is a dictionary with the keys:

            - field: str
            - value: str | int
            - operator: Literal[">", "<", "=", "!=", "LIKE", "NOT LIKE", ">=", "<="] | None

        :param query_format: Returned fields to be populated.
        :returns: Iterator of the found assets.
        """
        # copy the search parameters, so the list passed by the caller is not modified
        search_params = list(search_params or [])
        if catalog_id:
            search_params.append({'field': 'Catalog', 'value': catalog_id, 'operator': '='})
        else:
            search_params.append({'field': 'Catalog', 'value': '%', 'operator': 'LIKE'})

        get_params = _fields_params(query_format, default_fields='Owner,Description,Status')

        async for item in self._paged_request('assets', json_data=search_params, params=get_params):
            yield item

    async def get_asset_history(self, asset_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get asset history.

        :param asset_id: Asset ID.
        :returns: Iterator of transactions, each a dictionary with the keys
                  id, type, Type, Creator, Created, Description, _url and _hyperlinks.
                  Empty if the asset does not exist.
        """
        async for transaction in self._paged_request(
            _path('asset', asset_id, 'history'),
            params={
                'fields': 'Type,Creator,Created,Description,_hyperlinks',
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
            },
        ):
            yield transaction
