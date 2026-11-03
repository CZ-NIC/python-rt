"""Python interface to Request Tracker :term:`API`.

Description of Request Tracker :term:`REST` :term:`API`:
https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html
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
    VALID_CUSTOM_FIELD_OBJECT_TYPES,
    VALID_RIGHTS_OBJECT_TYPES,
    VALID_TICKET_LINK_NAMES,
    Attachment,
    ContentType,
    CustomFieldObjectType,
    JSONInput,
    JSONSearchParams,
    JSONValue,
    QueryParams,
    RightsObjectType,
    SearchFormat,
    TicketLinkName,
    _build_ticket_query,
    _check_fields,
    _CorrespondAction,
    _fields_params,
    _path,
    _refusal_error,
    _search_fields_params,
)
from .exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    InvalidUseError,
    NotAllowedError,
    NotFoundError,
    RtConnectionError,
    UnexpectedResponseError,
)

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


# Fields of the transactions returned by the history methods. RT returns the field Description always empty in
# collections, as it is no attribute of transactions; Field, OldValue, NewValue and Data describe a change.
_HISTORY_FIELDS = 'Type,Field,OldValue,NewValue,Data,TimeTaken,Creator,Created,_hyperlinks'

# Names (ref) of the links between tickets in the hyperlinks of a ticket.
_LINK_REFS = frozenset({'depends-on', 'depended-on-by', 'parent', 'child', 'refers-to', 'referred-to-by'})


class AsyncRt:
    """:term:`API` for Request Tracker according to
    https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html. Interface is based on
    :term:`REST` architecture, which is based on HTTP/1.1 protocol. This module
    is therefore mainly sending and parsing special HTTP messages.

    The client can be used as a context manager, which closes the underlying HTTP
    connections when leaving the context::

        async with AsyncRt(url='https://tracker.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('user', 'password')) as tracker:
            ticket = await tracker.get_ticket(1)

    .. warning:: The client targets the latest version of RT (6.0) and is tested with it.
                 Older versions of RT are not tested.

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

        :raises InvalidUseError: If the specified `url` or `per_page` is invalid, both `http_auth` and `token` are
                            specified, or connection settings are specified together with `client`.
        """
        self.logger = logging.getLogger(__name__)

        # ensure trailing slash
        if not url.endswith('/'):
            url = f'{url}/'

        if not url.endswith('REST/2.0/'):
            raise InvalidUseError('Invalid REST URL specified, please use a form of https://example.com/REST/2.0/')

        if http_auth is not None and token is not None:
            raise InvalidUseError('Specify either http_auth or token, but not both.')

        if not 1 <= per_page <= 100:
            raise InvalidUseError('per_page must be between 1 and 100 (the maximum supported by RT).')

        self.url = url
        self.per_page = per_page

        if client is not None:
            connection_settings_specified = proxy is not None or verify_cert is not True or http_auth is not None or token is not None or http_timeout != 20
            if connection_settings_specified:
                raise InvalidUseError(
                    'proxy, verify_cert, http_auth, token and http_timeout can not be used together with client, configure the client instead.'
                )

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

            if token is not None:
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
        form_data: collections.abc.Mapping[str, str] | None = None,
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
        :param form_data: Fields to send as form encoded request body (application/x-www-form-urlencoded), e.g. the
                          query of a search sent as POST. Can not be combined with *json_data* and *attachments*.

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

        if form_data is not None and (json_data is not None or attachments):
            raise InvalidUseError('form_data can not be combined with json_data or attachments.')

        try:
            if form_data is not None:
                response = await self.session.request(method, url, params=params, data=form_data)
            elif attachments:
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
    def _error_message(response: httpx2.Response, default: str) -> str:
        """Return the error message of an error response of RT, which is usually JSON like ``{"message": "..."}``.

        :param response: Error response from RT.
        :param default: Message used if the response does not contain a message.
        :returns: The error message.
        """
        try:
            result = response.json()
        except ValueError:  # json.JSONDecodeError and UnicodeDecodeError are subclasses of ValueError
            return default

        if isinstance(result, dict):
            message = result.get('message')
            return message if isinstance(message, str) and message else response.text

        return str(result)

    @classmethod
    def _check_response(cls, response: httpx2.Response) -> None:
        """Search general errors in server response and raise exceptions when found.

        All raised exceptions carry the status code and body of the response.

        :param response: Response from HTTP request.
        :raises BadRequestError: If the server returned an HTTP/400 error.
        :raises AuthorizationError: Credentials are invalid or missing.
        :raises NotAllowedError: The user is not allowed to execute the request (HTTP/403).
        :raises NotFoundError: Resource was not found.
        :raises ConflictError: The request conflicts with the state of the resource (HTTP/409), e.g. a right is
                               already granted.
        :raises UnexpectedResponseError: Server returned an unexpected status code.
        """
        status_code = response.status_code
        text = response.text

        if status_code == 400:
            raise BadRequestError(cls._error_message(response, 'Bad request'), status_code=status_code, response_message=text)

        if status_code == 401:
            raise AuthorizationError(
                'Server could not verify that you are authorized to access the requested document.', status_code=status_code, response_message=text
            )

        if status_code == 403:
            raise NotAllowedError(cls._error_message(response, 'Forbidden'), status_code=status_code, response_message=text)

        if status_code == 404:
            raise NotFoundError('No such resource found.', status_code=status_code, response_message=text)

        if status_code == 409:
            raise ConflictError(cls._error_message(response, 'Conflict'), status_code=status_code, response_message=text)

        # 204 (No Content) is returned when deleting resources
        if status_code not in (200, 201, 204):
            message = cls._error_message(response, '')
            raise UnexpectedResponseError(
                f'Received status code {status_code} instead of 200' + (f': {message}' if message else '.'), status_code=status_code, response_message=text
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
        form_data: collections.abc.Mapping[str, str] | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, JSONValue]]:
        """Request all pages of a paginated :term:`API` result.

        :param selector: End part of URL which completes self.url parameter
                           set during class initialization.
                           E.g.: ``ticket/123456/show``
        :param json_data: JSON request (e.g. search filter) to send to the API. If set, the request
                          is sent as POST, otherwise as GET.
        :param params: Query parameters to add to the URL.
        :param form_data: Fields to send as form encoded request body, e.g. a TicketSQL query. If set, the request
                          is sent as POST. RT reads them like query parameters, so the paging parameters are still
                          added to the URL.

        :returns: Iterator over the items of all pages.
        :raises UnexpectedResponseError: If the response is not a paginated result.
        :raises RtConnectionError: In case of connection error.
        """
        method: typing.Literal['GET', 'POST'] = 'GET' if json_data is None and form_data is None else 'POST'
        page = 1
        per_page = self.per_page

        while True:
            # copy the parameters, so the dictionary passed by the caller is not modified
            page_params = {**(params or {}), 'page': page, 'per_page': per_page}
            result = self._dict_result(await self._send(method, selector, params=page_params, json_data=json_data, form_data=form_data))

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

    async def _search_objects(
        self,
        selector: str,
        search_params: JSONSearchParams | None,
        fields: str | list[str] | dict[str, str] | None,
        default_fields: str,
        *,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search objects with a JSON search, e.g. queues or classes.

        :param selector: Endpoint of the search, e.g. ``queues``.
        :param search_params: Conditions of the search. All objects if not specified: RT returns no object for a
                              search without a condition, so a condition matching all objects is sent instead.
        :param fields: Fields returned for each object, see :py:meth:`search_assets`.
        :param default_fields: Fields returned if *fields* is not specified.
        :param include_disabled: Set to True to also return disabled objects.
        :returns: Iterator of the found objects.
        """
        conditions = list(search_params or [])
        if not conditions:
            conditions = [{'field': 'id', 'operator': '>', 'value': 0}]

        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields=default_fields),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._paged_request(selector, json_data=conditions, params=params):
            yield item

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

    def new_correspondence(self, *, queue: str | None = None) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed by other users than the one used for the connection.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue: Queue where to search

        :returns: Iterator of tickets which were last updated by another user than
                  the one used for the connection, ordered in decreasing order by LastUpdated.
                  Each ticket is a dictionary, the same as in
                  :py:meth:`~AsyncRt.search`.
        """
        # RT replaces __CurrentUser__ with the user who executes the search
        return self.search(queue=queue, order='-LastUpdated', LastUpdatedBy__notexact='__CurrentUser__')

    def last_updated(
        self,
        since: str | dt.date | dt.datetime,
        *,
        queue: str | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed after given date.

        .. note:: Requires RT 5.0.0 or newer.

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
        *,
        queue: str | None = None,
        order: str | None = None,
        raw_query: str | None = None,
        fields: SearchFormat | list[str] | dict[str, str] = 'l',
        conditions: collections.abc.Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search arbitrary needles in given fields and queue.

        Example::

            >>> tracker.search(CF_Domain='example.com', Subject__like='warning')
            >>> tracker.search(conditions={'CF_Contact Email': 'a@example.com', 'Status': 'open'})
            >>> tracker.search(queue='General', order='Status', raw_query="id = 1 OR id = 2 OR id = 3")

        The query is sent in the body of a POST request, so it is not limited by the maximum length of URLs and does
        not appear in the access logs of RT or of proxies in front of it.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue:      Queue where to search. If you wish to search across
                           all of your queues, pass None as the argument.
        :param order:      Name of field sorting result list, for descending
                           order put - before the field name. E.g. -Created
                           will put the newest tickets at the beginning
        :param raw_query:  A TicketSQL query (see the query builder of RT), used instead of *conditions* and
                           *kwargs*. *queue* and *order* can still be used. The query is passed to RT as is,
                           so never include untrusted input in it.
        :param fields:     Fields returned for each ticket:

                             - i: only *id* fields are populated
                             - s: only *id* and *subject* fields are populated
                             - l: multi-line format, many fields are populated
                             - [field1, field2]: list of fields to be populated
                             - dict: query parameters as defined by RT, e.g.
                               ``{'fields': 'Owner', 'fields[Owner]': 'Name'}``
        :param conditions: Search conditions as a mapping, in the same form as *kwargs*.
                           Use this for conditions built at runtime and for field names
                           which are not valid Python identifiers, e.g.
                           ``{'CF_Contact Email': 'a@example.com'}``. Unlike unpacking a
                           dictionary into *kwargs*, this is accepted by type checkers.
                           Conditions are combined with *kwargs*.
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
                             meaning of the query. Field names other than plain
                             names like ``Subject`` or ``Requestor.EmailAddress``
                             are quoted as well, e.g. ``'CustomRole.{Manager}'``.

        :returns: Iterator over matching tickets, each a dictionary with the fields selected by *fields*.
        :raises BadRequestError: If the query is malformed.
        :raises InvalidUseError: If an unsupported operator is used, a condition is given in both *conditions* and
                                 *kwargs*, or *raw_query* is combined with conditions.
        """
        if raw_query is not None and (conditions or kwargs):
            raise InvalidUseError('raw_query can not be combined with conditions; add them to the query instead.')

        if conditions:
            duplicates = conditions.keys() & kwargs.keys()
            if duplicates:
                raise InvalidUseError(f'Conditions given both in conditions and as keyword arguments: {", ".join(sorted(duplicates))}')
            kwargs = {**conditions, **kwargs}

        # The query is sent in the body of a POST request, so it is not limited by the maximum length of URLs and does
        # not appear in the access logs of RT or proxies. RT reads it like a query parameter.
        query = _build_ticket_query(queue, raw_query, kwargs)
        get_params: dict[str, str | int] = {}

        if order:
            if order.startswith('-'):
                get_params['orderby'] = order[1:]
                get_params['order'] = 'DESC'
            else:
                get_params['orderby'] = order

        get_params.update(_search_fields_params(fields))

        async for item in self._paged_request('tickets', params=get_params, form_data={'query': query}):
            yield item

    async def get_ticket(self, ticket_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Fetch ticket by its ID.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of demanded ticket
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Owner]': 'Name,EmailAddress'}``. RT always returns all fields of
                       the ticket itself, so a list of fields as in :py:meth:`~AsyncRt.search` is not supported.

        :returns: The ticket as dictionary with the keys id, EffectiveId, Type, Queue, Subject, Status, Owner,
                  Creator, LastUpdatedBy, Requestor, Cc, AdminCc, CustomRoles, CustomFields, Priority,
                  InitialPriority, FinalPriority, Created, LastUpdated, Starts, Started, Due, Resolved,
                  TimeEstimated, TimeWorked, TotalTimeWorked, TimeLeft and _hyperlinks.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        """
        response = await self._send('GET', _path('ticket', ticket_id), params={'fields[Queue]': 'Name', **(fields or {})})

        return self._dict_result(response)

    async def create_ticket(
        self,
        queue: str | int,
        *,
        subject: str | None = None,
        content: str | None = None,
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
        **kwargs: JSONInput,
    ) -> int:
        """Create new ticket and set given parameters.

        Example of the request sent to ``http://tracker.example.com/REST/2.0/ticket``::

            { "Queue": "General",
              "Subject": "Ticket created through REST API",
              "Owner": "Nobody",
              "Requestor": "somebody@example.com",
              "Cc": "user2@example.com",
              "CustomRoles": {"My Role": "staff1@example.com"},
              "Content": "Lorem Ipsum",
              "CustomFields": {"Severity": "Low"}
            }

        .. note:: Requires RT 5.0.0 or newer.

        :param queue: Name or ID of the queue to create the ticket in.
        :param subject: Optional subject for the ticket.
        :param content: Optional content of the ticket. Must be specified unless attachments are specified.
        :param content_type: Content-type of the Content parameter; can be either text/plain or text/html.
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :param kwargs: Other fields to set, e.g. Requestor, Cc, AdminCc, Owner, Status, Priority, InitialPriority,
                       FinalPriority, TimeEstimated, Starts, Due, CustomFields (e.g. ``{'Severity': 'High'}``),
                       CustomRoles (e.g. ``{'Manager': 'alice'}``). Roles (Requestor, Cc, AdminCc, Owner and custom roles in CustomRoles)
                       are set to the given members, replacing the current ones: user names, email addresses (users
                       which do not exist are created), principal IDs, or groups as ``'group:Name'``. Dates (e.g.
                       Due, Starts) are interpreted in UTC, e.g. ``'2030-01-31 12:00:00'``.

        :returns: ID of new ticket
        :raises InvalidUseError: If the `content_type` is not of a supported format.
        :raises NotAllowedError: If the user is not allowed to create tickets in the queue, or the queue does not
                                 exist or is disabled (RT returns status code 403 for all of them).
        :raises BadRequestError: If RT rejects the request, e.g. for an invalid value.
        """
        if content_type not in VALID_CONTENT_TYPES:
            raise InvalidUseError('Invalid content-type specified.')

        ticket_data: dict[str, JSONInput] = {'Queue': queue}

        if subject is not None:
            ticket_data['Subject'] = subject

        if content is not None:
            ticket_data['Content'] = content
            ticket_data['ContentType'] = content_type

        ticket_data.update(kwargs)

        response = await self._send('POST', 'ticket', json_data=ticket_data, attachments=attachments)

        return int(self._created_id(self._dict_result(response)))

    async def edit_ticket(self, ticket_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit ticket values.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket to edit
        :param kwargs: Fields to set, e.g. Requestor, Subject, Cc, AdminCc, Owner, Status,
                       Priority, InitialPriority, FinalPriority, TimeEstimated, Starts, Due
                       (according to RT fields). Custom fields can be set as dictionary, e.g.
                       ``CustomFields={'Severity': 'Low'}``, ``None`` deletes the value. RT ignores unknown fields.
                       Roles (Requestor, Cc, AdminCc, Owner and custom roles in CustomRoles)
                       are set to the given members, replacing the current ones: user names, email addresses (users
                       which do not exist are created), principal IDs, or groups as ``'group:Name'``. Dates (e.g.
                       Due, Starts) are interpreted in UTC, e.g. ``'2030-01-31 12:00:00'``.
                       Link names (e.g. ``RefersTo=[1, 2]``) replace all links of that type; use
                       :py:meth:`edit_link` to add or delete single links.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed),
                  e.g. ``["Ticket 1: Subject changed from 'a' to 'b'"]``. RT reports invalid values only in these
                  messages, e.g. ``"Ticket 1: Status 'x' isn't a valid status for this ticket."``, while the
                  other fields are still changed.
        :raises NotFoundError: If the ticket, or a user or queue set in *kwargs*, does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id), json_data=kwargs))

        for message in msg:
            if REGEX_PATTERNS['does_not_exist'].search(message):
                raise NotFoundError(message)

        return msg

    async def get_ticket_history(self, ticket_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get set of short history items.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket
        :returns: Iterator of the transactions of the ticket, oldest first, each a dictionary with the keys id, type,
                  _url, Type (e.g. Create, Correspond, Comment, Status, Set, CustomField), Field (the changed field,
                  e.g. Owner), OldValue, NewValue, Data (e.g. the subject of a message), TimeTaken, Creator (a
                  dictionary with id, Name, RealName and EmailAddress), Created and _hyperlinks. Use
                  :py:meth:`get_ticket_messages` for the text of messages.
        """
        async for transaction in self._paged_request(
            _path('ticket', ticket_id, 'history'),
            params={
                'fields': _HISTORY_FIELDS,
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
            },
        ):
            yield transaction

    async def get_transaction(self, transaction_id: str | int) -> dict[str, typing.Any]:
        """Get a transaction.

        .. note:: Requires RT 5.0.0 or newer.

        :param transaction_id: ID of transaction
        :returns: The transaction as dictionary, e.g. with the keys id, Type, Data, Content (text of a message),
                  ContentType, TimeTaken, Object (the ticket, asset etc.), Creator, Created, CustomFields and
                  _hyperlinks (also to its attachments), and for changes Field, OldValue and NewValue.
        :raises UnexpectedResponseError: If the response from RT is not as expected,
                                         e.g. if the transaction does not exist (RT returns status code 500).
        """
        return self._dict_result(await self._send('GET', _path('transaction', transaction_id)))

    async def search_transactions(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        raw_query: str | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        order: str | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search transactions, e.g. of a ticket or across tickets, with conditions or a TransactionSQL query.

        Example::

            >>> tracker.search_transactions(search_params=[{'field': 'ObjectId', 'value': 1}, {'field': 'Type', 'value': 'Comment'}])
            >>> tracker.search_transactions(raw_query="Type = 'Correspond' AND Created > '2024-01-01'", fields=['Type', 'Content'])

        Conditions on different fields are combined with AND, several conditions on the same field with OR (see the
        REST2 documentation of RT on JSON searches). The query is sent in the body of a POST request like the one of
        :py:meth:`search`.

        .. note:: Requires RT 5.0.0 or newer, *raw_query* requires RT 5.0.2 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'ObjectType', 'value': 'RT::Ticket'}, {'field': 'ObjectId', 'value': 1}]``.
        :param raw_query: TransactionSQL query, used instead of *search_params*, e.g.
                          ``"ObjectType = 'RT::Ticket' AND ObjectId = 1 AND Type = 'Comment'"``. It is passed to RT
                          as is, so never include untrusted input in it.
        :param fields: Fields returned for each transaction: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Type, Created, Creator,
                       ObjectType and ObjectId. ``Content`` returns the text of messages, see
                       :py:meth:`get_ticket_messages`.
        :param order: Name of the field to sort the transactions by, with ``-`` in front for descending order,
                      e.g. ``'-Created'``.
        :returns: Iterator of the found transactions.
        :raises InvalidUseError: If not exactly one of *search_params* and *raw_query* is specified, or *raw_query* is
                                 empty.
        :raises BadRequestError: If the TransactionSQL query is invalid.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if (search_params is None) == (raw_query is None):
            raise InvalidUseError('Specify either search_params or raw_query.')

        params: dict[str, str | int] = {**_fields_params(fields, default_fields='Type,Created,Creator,ObjectType,ObjectId')}
        if order:
            if order.startswith('-'):
                params['orderby'] = order[1:]
                params['order'] = 'DESC'
            else:
                params['orderby'] = order

        if raw_query is not None:
            if not raw_query.strip():
                raise InvalidUseError('raw_query must not be empty.')
            transactions = self._paged_request('transactions', params=params, form_data={'query': raw_query})
        else:
            transactions = self._paged_request('transactions', json_data=list(search_params or []), params=params)

        async for item in transactions:
            yield item

    async def get_ticket_messages(self, ticket_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the messages of a ticket, i.e. its creation, replies and comments with their text, oldest first.

        Unlike :py:meth:`get_ticket_history` followed by :py:meth:`get_transaction` for each entry, this needs only one
        request per 100 messages.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of the ticket.
        :returns: Iterator of the transactions, each a dictionary with the keys id, type, _url, Type (Create, Correspond
                  or Comment), Created, Creator (a dictionary with id, Name, RealName and EmailAddress), TimeTaken and
                  Content. Content is the text of the message, as plain text also for HTML messages (converted by RT),
                  without attachments (see :py:meth:`get_attachments`), so it is empty for a message with only
                  attachments. Empty if the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        search_params: list[dict[str, JSONInput]] = [
            {'field': 'ObjectType', 'value': 'RT::Ticket'},
            {'field': 'ObjectId', 'value': ticket_id},
            # several conditions on the same field are combined with OR
            {'field': 'Type', 'value': 'Create'},
            {'field': 'Type', 'value': 'Correspond'},
            {'field': 'Type', 'value': 'Comment'},
        ]
        params: dict[str, str | int] = {
            'fields': 'Type,Created,Creator,TimeTaken,Content',
            'fields[Creator]': 'Name,RealName,EmailAddress',
            # IDs of transactions are assigned in chronological order and are unique, unlike the creation time
            'orderby': 'id',
            'order': 'ASC',
        }

        async for item in self._paged_request('transactions', json_data=search_params, params=params):
            yield item

    async def _correspond(
        self,
        ticket_id: str | int,
        content: str = '',
        action: _CorrespondAction = 'correspond',
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
        *,
        extra_fields: collections.abc.Mapping[str, JSONInput] | None = None,
    ) -> list[str]:
        """Sends out the correspondence.

        :param ticket_id: ID of ticket to which message belongs
        :param content: Content of email message
        :param action: correspond or comment
        :param content_type: Content type of email message, defaults to text/plain. Alternative is text/html.
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :param extra_fields: Further fields of the request, e.g. ``{'Status': 'resolved'}``.
        :returns: List of messages returned by the backend related to the executed action.
        :raises BadRequestError: When ticket does not exist
        :raises InvalidUseError: If the `action` parameter or the `content_type` is invalid.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        if action not in _CORRESPOND_ACTIONS:
            raise InvalidUseError('action must be either "correspond" or "comment"')

        if content_type not in VALID_CONTENT_TYPES:
            raise InvalidUseError('Invalid content-type specified.')

        post_data: dict[str, JSONInput] = {
            **(extra_fields or {}),
            'Content': content,
            'ContentType': content_type,
        }

        # Adding a one-shot cc/bcc is not supported by REST2 (RT 6.0.4)
        # if cc:
        #     post_data['Cc'] = cc  # noqa: ERA001
        #
        # if bcc:
        #     post_data['Bcc'] = bcc  # noqa: ERA001

        response = await self._send('POST', _path('ticket', ticket_id, action), json_data=post_data, attachments=attachments)

        return self._list_result(response)

    @staticmethod
    def _message_fields(
        *,
        subject: str | None,
        time_taken: int | None,
        status: str | None,
        custom_fields: collections.abc.Mapping[str, JSONInput] | None,
        custom_roles: collections.abc.Mapping[str, JSONInput] | None,
        txn_custom_fields: collections.abc.Mapping[str, JSONInput] | None,
    ) -> dict[str, JSONInput]:
        """Return the fields of a reply or comment which are set, named as expected by RT."""
        fields: dict[str, JSONInput] = {
            'Subject': subject,
            'TimeTaken': time_taken,
            'Status': status,
            'CustomFields': custom_fields,
            'CustomRoles': custom_roles,
            'TxnCustomFields': txn_custom_fields,
        }
        return {name: value for name, value in fields.items() if value is not None}

    async def reply(
        self,
        ticket_id: str | int,
        content: str = '',
        *,
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
        subject: str | None = None,
        time_taken: int | None = None,
        status: str | None = None,
        custom_fields: collections.abc.Mapping[str, JSONInput] | None = None,
        custom_roles: collections.abc.Mapping[str, JSONInput] | None = None,
        txn_custom_fields: collections.abc.Mapping[str, JSONInput] | None = None,
    ) -> list[str]:
        """Sends email message to the contacts in ``Requestors`` field of
        given ticket with subject as is set in ``Subject`` field.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket to which message belongs
        :param content: Content of email message (text/plain or text/html)
        :param content_type: Content type of email message, default to text/plain
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :param subject: Subject of the reply, instead of the subject of the ticket.
        :param time_taken: Time worked on the reply in minutes, added to the time worked of the ticket.
        :param status: Status to set on the ticket after adding the reply, e.g. ``'resolved'`` (requires RT 5.0.2).
        :param custom_fields: Custom fields of the ticket to set, by name or ID, e.g. ``{'Severity': 'High'}``
                              (a list of values for custom fields with several values).
        :param custom_roles: Custom roles of the ticket to set, by name, to a user name or email address (a list of
                             them for roles with several members), e.g. ``{'Manager': 'alice'}`` (requires RT 5.0.2).
        :param txn_custom_fields: Custom fields of the transaction of the reply to set, by name or ID.
        :returns: Status messages of RT, first ``"Correspondence added"``, followed by one for each changed field or role and the
                  status. RT sets them after adding the reply, so it reports refused values only in these messages,
                  e.g. ``"Status 'x' isn't a valid status for this ticket."``. RT ignores unknown custom fields and
                  roles of the ticket.
        :raises BadRequestError: When ticket does not exist
        :raises InvalidUseError: If the `content_type` is not of a supported format.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = await self._correspond(
            ticket_id,
            content,
            'correspond',
            content_type,
            attachments,
            extra_fields=self._message_fields(
                subject=subject,
                time_taken=time_taken,
                status=status,
                custom_fields=custom_fields,
                custom_roles=custom_roles,
                txn_custom_fields=txn_custom_fields,
            ),
        )

        if not msg:
            raise UnexpectedResponseError(str(msg))

        return msg

    async def delete_ticket(self, ticket_id: str | int) -> None:
        """Mark a ticket as deleted.

        .. note:: Requires RT 5.0.0 or newer.

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
        *,
        content_type: ContentType = 'text/plain',
        attachments: typing.Sequence[Attachment] | None = None,
        subject: str | None = None,
        time_taken: int | None = None,
        status: str | None = None,
        custom_fields: collections.abc.Mapping[str, JSONInput] | None = None,
        custom_roles: collections.abc.Mapping[str, JSONInput] | None = None,
        txn_custom_fields: collections.abc.Mapping[str, JSONInput] | None = None,
    ) -> list[str]:
        """Adds comment to the given ticket.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket to which comment belongs
        :param content: Content of comment
        :param content_type: Content type of comment, default to text/plain
        :param attachments: Optional list of :py:class:`~rt.common.Attachment` objects
        :param subject: Subject of the comment, instead of the subject of the ticket.
        :param time_taken: Time worked on the comment in minutes, added to the time worked of the ticket.
        :param status: Status to set on the ticket after adding the comment, e.g. ``'resolved'`` (requires RT 5.0.2).
        :param custom_fields: Custom fields of the ticket to set, by name or ID, e.g. ``{'Severity': 'High'}``
                              (a list of values for custom fields with several values).
        :param custom_roles: Custom roles of the ticket to set, by name, to a user name or email address (a list of
                             them for roles with several members), e.g. ``{'Manager': 'alice'}`` (requires RT 5.0.2).
        :param txn_custom_fields: Custom fields of the transaction of the comment to set, by name or ID.
        :returns: Status messages of RT, first ``"Comments added"``, followed by one for each changed field or role and the
                  status. RT sets them after adding the comment, so it reports refused values only in these messages,
                  e.g. ``"Status 'x' isn't a valid status for this ticket."``. RT ignores unknown custom fields and
                  roles of the ticket.
        :raises BadRequestError: When ticket does not exist
        :raises InvalidUseError: If the `content_type` is not of a supported format.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = await self._correspond(
            ticket_id,
            content,
            'comment',
            content_type,
            attachments,
            extra_fields=self._message_fields(
                subject=subject,
                time_taken=time_taken,
                status=status,
                custom_fields=custom_fields,
                custom_roles=custom_roles,
                txn_custom_fields=txn_custom_fields,
            ),
        )

        if not msg:
            raise UnexpectedResponseError(str(msg))

        return msg

    async def get_attachments(
        self,
        ticket_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        files_only: bool = True,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the attachments (files) of a ticket.

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

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket
        :param search_params: Conditions of the search as described for :py:meth:`search_attachments`, e.g. the
                              files of a single reply or comment: ``[{'field': 'TransactionId', 'value': 42}]``.
        :param fields: Fields returned for each attachment: a comma separated string or list of fields,
                       or a dictionary with query parameters as defined by RT, e.g. ``{'fields[Creator]': 'Name'}``.
                       Defaults to Filename, ContentType and ContentLength.
        :param files_only: Set to False to also return the other parts of messages, e.g. the text of a message
                           (see :py:meth:`search_attachments`).
        :returns: Iterator of attachments belonging to given ticket.
        """
        get_params = _fields_params(fields, default_fields='Filename,ContentType,ContentLength')

        async for item in self._paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=self._attachment_conditions(search_params, files_only=files_only),
            params=get_params,
        ):
            yield item

    @staticmethod
    def _attachment_conditions(search_params: JSONSearchParams | None, *, files_only: bool) -> list[collections.abc.Mapping[str, JSONInput]]:
        """Return the conditions of a search of attachments.

        :param search_params: Conditions of the caller, which are not modified.
        :param files_only: Add a condition matching only files, i.e. attachments with a file name.
        """
        conditions = list(search_params or [])
        if files_only:
            # combined with AND also with conditions on Filename, which RT would combine with OR by default
            conditions.append({'field': 'Filename', 'operator': 'IS NOT', 'value': '', 'entry_aggregator': 'AND'})
        elif not conditions:
            # RT returns no attachment for a search without a condition
            conditions = [{'field': 'id', 'operator': '>', 'value': 0}]
        return conditions

    async def get_attachments_ids(
        self,
        ticket_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        files_only: bool = True,
    ) -> collections.abc.AsyncIterator[int]:
        """Get IDs of attachments for given ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket
        :param search_params: Conditions of the search, see :py:meth:`get_attachments`.
        :param files_only: Set to False to also return the other parts of messages, see :py:meth:`get_attachments`.
        :returns: Iterator of IDs (type int) of attachments belonging to given
                  ticket.
        """
        async for item in self._paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=self._attachment_conditions(search_params, files_only=files_only),
        ):
            attachment_id = item.get('id')
            if not isinstance(attachment_id, (str, int)):
                raise UnexpectedResponseError(f'Attachment without ID: {item}')
            yield int(attachment_id)

    async def get_attachment(self, attachment_id: str | int) -> dict[str, typing.Any]:
        """Get attachment.

        .. note:: Requires RT 5.0.0 or newer.

        :param attachment_id: ID of attachment to fetch
        :returns: Attachment as dictionary with the keys id, TransactionId, Parent, ContentType, Filename, Subject,
                  MessageId, Creator, Created, Headers, _hyperlinks and Content (base64 encoded string).
                  'Headers' holds the headers of the attachment as string (one header per line), e.g.
                  Content-Type, Content-Disposition and for emails From, To, Subject or Message-ID. Which headers
                  exist depends on the mail servers which sent the email, not on RT.

        :raises UnexpectedResponseError: If the response from RT is not as expected, e.g. if the attachment does not
                                         exist (RT returns status code 500).
        """
        return self._dict_result(await self._send('GET', _path('attachment', attachment_id)))

    async def search_attachments(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        files_only: bool = True,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search attachments across all tickets, e.g. files by name, content type or creation time.

        Example::

            >>> tracker.search_attachments(search_params=[{'field': 'Filename', 'operator': 'LIKE', 'value': '.pdf'},
            ...                                           {'field': 'Created', 'operator': '>', 'value': '2024-01-01'}])

        RT stores each message as several attachments: the parts of the email, i.e. a container, the text of the
        message and each file. By default only files (attachments with a file name) are returned. RT only returns
        attachments which the user is allowed to see.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'ContentType', 'value': 'application/pdf'}]``. Fields which can be searched
                              are e.g. Filename, ContentType, Subject, Created, Creator and TransactionId, but not
                              ContentLength (RT computes it, it is not stored). All attachments if not specified.
        :param fields: Fields returned for each attachment: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Filename, ContentType, ContentLength,
                       TransactionId and Created. Use :py:meth:`get_attachment` for the content: RT returns the field
                       Content in search results not base64 encoded, so binary content can not be represented
                       reliably. Do not request the field Parent, RT fails with HTTP status 500 for it (RT 6.0.4).
        :param files_only: Set to False to also return the other parts of messages, e.g. the text of a message.
        :returns: Iterator of the found attachments.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params = _fields_params(fields, default_fields='Filename,ContentType,ContentLength,TransactionId,Created')

        async for item in self._paged_request('attachments', json_data=self._attachment_conditions(search_params, files_only=files_only), params=params):
            yield item

    async def get_user(self, user_id: int | str) -> dict[str, typing.Any]:
        """Get user details.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of user by username (str) or user ID
                        (int)
        :returns: The user as dictionary, e.g. with the keys id, Name, RealName, EmailAddress, Privileged, Disabled,
                  Gecos, Comments, CustomFields, Memberships (the groups of the user), Created, Creator,
                  LastUpdated, LastUpdatedBy and _hyperlinks. RT only returns the fields the current user is
                  allowed to see.

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If the user does not exist.
        """
        return self._dict_result(await self._send('GET', _path('user', user_id)))

    async def user_exists(self, user_id: int | str, *, privileged: bool) -> bool:
        """Check if a given user exists.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of user by username (str) or user ID (int).
        :param privileged: True to only return True if the user exists and is privileged, False to return True
                           for any existing user (also unprivileged ones, e.g. requestors). It must be specified, as
                           RT also creates unprivileged users e.g. for everyone writing an email to RT.
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

        .. note:: Requires RT 5.0.0 or newer.

        :param user_name: Username (login for privileged, required)
        :param email_address: Email address (required)
        :param kwargs: Optional fields to set (see edit_user)
        :returns: The name of the new user, which RT returns as its ID (and which identifies it like its numeric ID).
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

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of user by username (str) or user ID
                        (int)
        :param kwargs: Other fields to edit from the following list (the fields of users in RT 5.0 and 6.0):

                          * Name
                          * Password
                          * EmailAddress
                          * RealName
                          * NickName
                          * Gecos
                          * Organization
                          * Address1, Address2, City, State, Zip, Country
                          * HomePhone, WorkPhone, MobilePhone, PagerPhone
                          * FreeformContactInfo
                          * Comments
                          * Signature
                          * Lang
                          * Timezone, e.g. ``'Europe/Berlin'``
                          * SMIMECertificate
                          * Privileged
                          * Disabled
                          * CustomFields

                       RT (6.0.4) fails with HTTP status 500 (:py:exc:`~rt.exceptions.UnexpectedResponseError`) when
                       changing the Password; it can be set when creating the user.

        :returns: List of status messages
        :raises NotFoundError: When the user does not exist
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _USER_FIELDS)

        return self._list_result(await self._send('PUT', _path('user', user_id), json_data=kwargs))

    async def delete_user(self, user_id: str | int) -> None:
        """Disable a user.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of a user by name (str) or ID (int)
        :raises NotFoundError: If the user does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('user', user_id))

    async def search_users(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        privileged: bool | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search users.

        Example::

            >>> tracker.search_users(search_params=[{'field': 'EmailAddress', 'operator': 'LIKE', 'value': '@example.com'}])

        .. note:: Requires RT 5.0.0 or newer, *privileged* requires RT 5.0.8 or newer (or any RT 6.0).

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'alice'}]``. All users if not specified.
        :param privileged: ``True`` to search only privileged users, ``False`` only unprivileged users,
                           ``None`` (default) all users.
        :param fields: Fields returned for each user: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, RealName, EmailAddress and Disabled.
        :param include_disabled: Set to True to also return disabled users.
        :returns: Iterator of the found users.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if privileged is None:
            selector = 'users'
        else:
            selector = _path('users', 'privileged' if privileged else 'unprivileged')

        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields='Name,RealName,EmailAddress,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._paged_request(selector, json_data=list(search_params or []), params=params):
            yield item

    async def get_user_groups(self, user_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the groups which a user is a direct member of.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of the user by name (str) or ID (int).
        :returns: Iterator of the groups, each a dictionary with the keys id, type and _url.
        :raises NotFoundError: If the user does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._paged_request(_path('user', user_id, 'groups')):
            yield item

    async def add_user_to_group(self, user_id: str | int, group_id: str | int) -> list[str]:
        """Add a user to a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of the user by name (str) or ID (int).
        :param group_id: ID of the group (RT does not support group names here).
        :returns: Status messages of RT, e.g. ``['Member added: alice']``.
        :raises NotFoundError: If the user or the group does not exist.
        :raises InvalidUseError: If RT refused to add the user, e.g. if the user is already a member of the group.
        :raises NotAllowedError: If the user is not allowed to change the members of the group.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('PUT', _path('user', user_id, 'groups'), json_data=[group_id])
        result = self._decode_json(response)

        # RT returns a status (1 for success, 0 for failure) and a message for each group
        if not isinstance(result, list) or len(result) != 2:
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        status, message = result
        if not isinstance(status, int) or not isinstance(message, str):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        if not status:
            if message.endswith('not found') or message == "Couldn't find that principal":
                raise NotFoundError(message)
            raise _refusal_error(message)

        return [message]

    async def remove_user_from_group(self, user_id: str | int, group_id: str | int) -> None:
        """Remove a user from a group.

        RT also confirms the removal if the user is not a member of the group.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of the user by name (str) or ID (int).
        :param group_id: ID of the group (RT does not support group names here).
        :raises NotFoundError: If the user does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('user', user_id, 'group', group_id))

    async def remove_user_from_all_groups(self, user_id: str | int) -> None:
        """Remove a user from all groups which the user is a direct member of.

        .. note:: Requires RT 5.0.0 or newer.

        :param user_id: Identification of the user by name (str) or ID (int).
        :raises NotFoundError: If the user does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('user', user_id, 'groups'))

    async def search_groups(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search groups.

        RT 6.0 returns only user defined groups, RT 5.0 also internal groups (e.g. system and role groups).

        Example::

            >>> tracker.search_groups(search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Staff'}])

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'Staff'}]``. All groups if not specified.
        :param fields: Fields returned for each group: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description and Disabled.
        :param include_disabled: Set to True to also return disabled groups.
        :returns: Iterator of the found groups.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields='Name,Description,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._paged_request('groups', json_data=list(search_params or []), params=params):
            yield item

    async def get_group(self, group_id: str | int) -> dict[str, typing.Any]:
        """Get a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :returns: The group as dictionary, including its direct members in the key Members (users by name,
                  groups by ID).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('group', group_id)))

    async def create_group(self, name: str, **kwargs: JSONInput) -> int:
        """Create a user defined group.

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Name of the group, which must be unique.
        :param kwargs: Other fields to set, e.g. Description.
        :returns: ID of the new group.
        :raises BadRequestError: If RT rejects the request, e.g. if a group with the name exists.
        :raises NotAllowedError: If the user is not allowed to create groups.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', 'group', json_data={'Name': name, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_group(self, group_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param kwargs: Fields to set, e.g. Name, Description, Disabled. RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('group', group_id), json_data=kwargs))

    async def delete_group(self, group_id: str | int) -> None:
        """Disable a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('group', group_id))

    async def get_group_members(
        self,
        group_id: str | int,
        *,
        recursive: bool = False,
        users: bool = True,
        groups: bool = True,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the members of a group.

        RT returns only the ID, type (user or group) and _url of each member, :py:meth:`get_group`
        returns the direct members with the names of users.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param recursive: Set to True to also return the members of member groups. RT then also returns the group
                          itself, and users which are members of several of the groups more than once.
        :param users: Set to False to not return users.
        :param groups: Set to False to not return groups.
        :returns: Iterator of the members.
        :raises InvalidUseError: If both *users* and *groups* are False.
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if not users and not groups:
            raise InvalidUseError('At least one of users and groups must be True.')

        params: dict[str, str | int] = {}
        if recursive:
            params['recursively'] = 1
        if not users:
            params['users'] = 0
        if not groups:
            params['groups'] = 0

        async for item in self._paged_request(_path('group', group_id, 'members'), params=params):
            yield item

    async def add_group_member(self, group_id: str | int, principal_id: str | int) -> list[str]:
        """Add a user or group as member to a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param principal_id: ID of the user or group to add (RT does not support names here).
        :returns: Status messages of RT, e.g. ``['Member added: alice']``.
        :raises NotFoundError: If the group or the member does not exist.
        :raises InvalidUseError: If RT refused to add the member, e.g. if it is already a member of the group.
        :raises NotAllowedError: If the user is not allowed to change the members of the group.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('group', group_id, 'members'), json_data=[principal_id]))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        if not msg[0].startswith('Member added'):
            # RT reports a group which is not user defined (e.g. a system group) as not found
            if msg[0] == "Couldn't find that principal" or msg[0].endswith('not found'):
                raise NotFoundError(msg[0])
            raise _refusal_error(msg[0])

        return msg

    async def remove_group_member(self, group_id: str | int, principal_id: str | int) -> None:
        """Remove a user or group from the members of a group.

        RT also confirms the removal if the principal is not a member of the group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param principal_id: ID of the user or group to remove (RT does not support names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('group', group_id, 'member', principal_id))

    async def remove_all_group_members(self, group_id: str | int) -> None:
        """Remove all direct members of a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('group', group_id, 'members'))

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

        .. note:: Requires RT 5.0.0 or newer.

        :param queue_id: Identification of queue by name (str) or queue ID
                         (int)
        :returns: Queue details as a dictionary

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: In case the queue does not exist
        """
        return self._dict_result(await self._send('GET', _path('queue', queue_id)))

    async def get_all_queues(self, *, include_disabled: bool = False) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
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

        .. note:: Requires RT 5.0.0 or newer.

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

    async def search_queues(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search queues.

        Example::

            >>> tracker.search_queues(search_params=[{'field': 'Lifecycle', 'value': 'default'}])

        Unlike for other objects, RT combines several conditions on the same field with AND for queues. Add
        ``'entry_aggregator': 'OR'`` to a condition to combine it with the previous one with OR.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'Support'}]``. All queues if not
                              specified.
        :param fields: Fields returned for each queue: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description, Lifecycle and Disabled.
        :param include_disabled: Set to True to also return disabled queues.
        :returns: Iterator of the found queues.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._search_objects('queues', search_params, fields, 'Name,Description,Lifecycle,Disabled', include_disabled=include_disabled):
            yield item

    async def edit_queue(self, queue_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit queue.

        .. note:: Requires RT 5.0.0 or newer.

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
                          * SubjectTag
                          * CustomFields (custom fields of the queue itself, e.g. ``{'Region': 'EU'}``)
                          * Cc, AdminCc (watchers of all tickets of the queue: user names, email addresses, principal
                            IDs or groups as ``'group:Name'``, replacing the current watchers)

        :returns: List of status messages
        :raises NotFoundError: When queue does not exist
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _QUEUE_FIELDS)

        return self._list_result(await self._send('PUT', _path('queue', queue_id), json_data=kwargs))

    async def create_queue(self, name: str, **kwargs: JSONInput) -> int:
        """Create queue.

        .. note:: Requires RT 5.0.0 or newer.

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

        .. note:: Requires RT 5.0.0 or newer.

        :param queue_id: Identification of queue by name (str) or ID (int)
        :raises NotFoundError: If the queue does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('queue', queue_id))

    async def get_links(self, ticket_id: str | int) -> list[dict[str, typing.Any]]:
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

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ticket ID
        :returns: The links of the ticket, each a dictionary with the keys ref (the kind of link: depends-on,
                  depended-on-by, parent, child, refers-to or referred-to-by), type (ticket, or external for a link
                  to a URL), _url and id (the ID of the linked ticket, only for tickets).
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        ticket = await self.get_ticket(ticket_id)

        return [link for link in ticket['_hyperlinks'] if link.get('ref') in _LINK_REFS]

    async def edit_link(
        self,
        ticket_id: str | int,
        link_name: TicketLinkName,
        link_value: str | int,
        *,
        delete: bool = False,
    ) -> list[str]:
        """Creates or deletes a link between the specified tickets.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket to edit
        :param link_name: Name of link to edit ('Parent', 'Child', 'RefersTo',
                          'ReferredToBy', 'DependsOn', 'DependedOnBy')
        :param link_value: Either ticket ID or external link.
        :param delete: if True the link is deleted instead of created
        :returns: Status messages of RT, e.g. ``['Ticket 2 refers to Ticket 1.']``.
        :raises NotFoundError: If the ticket or the linked ticket does not exist.
        :raises InvalidUseError: If the link name is not supported or RT does not allow the link,
                                 e.g. to a deleted ticket or from a ticket to itself, or if RT
                                 could not create or delete the link.
        :raises NotAllowedError: If the user is not allowed to change the links of the ticket.
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
            if 'not allowed' in msg[0] or msg[0].startswith(('Link could not be created', 'Link could not be deleted')):
                raise InvalidUseError(msg[0])
            if msg[0].endswith('Permission Denied'):
                raise _refusal_error(msg[0])

        return msg

    async def merge_ticket(self, ticket_id: str | int, into_id: str | int) -> list[str]:
        """Merge ticket into another.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket to be merged
        :param into_id: ID of destination ticket
        :returns: Status messages of RT, i.e. ``['Merge Successful']``.
        :raises NotFoundError: If the ticket to be merged or the destination ticket does not exist.
        :raises InvalidUseError: If RT refused the merge, e.g. of a ticket into itself.
        :raises NotAllowedError: If the user is not allowed to merge the tickets.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id), json_data={'MergeInto': into_id}))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        if msg[0].lower() != 'merge successful':
            if msg[0] == "New ticket doesn't exist":
                raise NotFoundError(msg[0])
            raise _refusal_error(msg[0])

        return msg

    async def _change_owner(self, ticket_id: str | int, action: typing.Literal['take', 'untake', 'steal']) -> list[str]:
        """Take, untake or steal a ticket.

        :param ticket_id: ID of ticket
        :param action: The action to execute
        :returns: Status messages of RT, e.g. ``['Owner changed from Nobody to root']``.
        :raises InvalidUseError: If RT refused to change the owner.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        msg = self._list_result(await self._send('PUT', _path('ticket', ticket_id, action)))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        if not msg[0].lower().startswith('owner changed'):
            raise _refusal_error(msg[0])

        return msg

    async def take(self, ticket_id: str | int) -> list[str]:
        """Take ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be taken
        :returns: Status messages of RT, e.g. ``['Owner changed from Nobody to root']``.
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the user already owns the ticket.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'take')

    async def untake(self, ticket_id: str | int) -> list[str]:
        """Untake ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be untaken
        :returns: Status messages of RT, e.g. ``['Owner changed from root to Nobody']``.
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the ticket is not owned.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'untake')

    async def steal(self, ticket_id: str | int) -> list[str]:
        """Steal ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be stolen
        :returns: Status messages of RT, e.g. ``['Owner changed from Nobody to root']``.
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the ticket is not owned by another user.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return await self._change_owner(ticket_id, 'steal')

    async def get_catalog(self, catalog_id: str | int) -> dict[str, typing.Any]:
        """Get catalog.

        .. note:: Requires RT 5.0.0 or newer.

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

    async def get_all_catalogs(self, *, include_disabled: bool = False) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get all catalogs which the user can see.

        .. note:: Requires RT 5.0.0 or newer.

        :param include_disabled: Set to True to also return disabled catalogs.
        :returns: Iterator of the catalogs, each a dictionary with the keys id, type, _url, Name, Description,
                  Lifecycle and Disabled.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int] = {'fields': 'Name,Description,Lifecycle,Disabled', 'find_disabled_rows': int(include_disabled)}

        async for item in self._paged_request('catalogs/all', params=params):
            yield item

    async def search_catalogs(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search catalogs.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'Laptops'}]``. All catalogs if not
                              specified.
        :param fields: Fields returned for each catalog: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description, Lifecycle and Disabled.
        :param include_disabled: Set to True to also return disabled catalogs.
        :returns: Iterator of the found catalogs.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        search_params = list(search_params or [])
        if not search_params:
            # RT returns no catalog for a search without a condition
            search_params = [{'field': 'id', 'operator': '>', 'value': 0}]

        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields='Name,Description,Lifecycle,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._paged_request('catalogs', json_data=search_params, params=params):
            yield item

    async def create_catalog(self, name: str, **kwargs: JSONInput) -> int:
        """Create a catalog.

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Name of the catalog, which must be unique.
        :param kwargs: Other fields to set, e.g. Description or Lifecycle (an asset lifecycle, ``'assets'`` by default).
        :returns: ID of the new catalog.
        :raises BadRequestError: If RT rejects the request, e.g. if a catalog with the name exists or the lifecycle
                                 is invalid.
        :raises NotAllowedError: If the user is not allowed to create catalogs.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', 'catalog', json_data={'Name': name, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_catalog(self, catalog_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit a catalog.

        .. note:: Requires RT 5.0.0 or newer.

        :param catalog_id: Identification of the catalog by name (str) or ID (int).
        :param kwargs: Fields to set, e.g. Name, Description, Lifecycle, Disabled. RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
        :raises NotFoundError: If the catalog does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('catalog', catalog_id), json_data=kwargs))

    async def delete_catalog(self, catalog_id: str | int) -> None:
        """Disable a catalog.

        .. note:: Requires RT 5.0.0 or newer.

        :param catalog_id: Identification of the catalog by name (str) or ID (int).
        :raises NotFoundError: If the catalog does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('catalog', catalog_id))

    async def get_asset(self, asset_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get asset.

        .. note:: Requires RT 5.0.0 or newer.

        :param asset_id: Asset ID.
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Catalog]': 'Name'}``. RT always returns all fields of the asset itself.
        :returns: Asset as dictionary, with these keys:

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
        return self._dict_result(await self._send('GET', _path('asset', asset_id), params=fields or {}))

    async def create_asset(self, name: str, catalog: str | int, **kwargs: JSONInput) -> int:
        """Create a new asset in a catalog.

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Asset name.
        :param catalog: Catalog name or ID.
        :param kwargs: Other fields to set, e.g. Description, Status, CustomFields, RefersTo.
        :returns: ID of the new asset.
        :raises BadRequestError: If RT rejects the request as invalid.
        :raises NotAllowedError: If the user is not allowed to create assets in the catalog,
                                 or the catalog does not exist (RT returns status code 403 for both).
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', 'asset', json_data={'Name': name, 'Catalog': catalog, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_asset(self, asset_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit an existing asset.

        .. note:: Requires RT 5.0.0 or newer.

        :param asset_id: Asset ID.
        :param kwargs: Fields to set, e.g. Name, Description, Status, CustomFields, RefersTo.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
        :raises NotFoundError: If the asset does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('asset', asset_id), json_data=kwargs))

    async def delete_asset(self, asset_id: str | int) -> None:
        """Mark an asset as deleted by setting its status to ``deleted``.

        Assets can not be deleted in RT, so the endpoint ``DELETE /asset/:id`` of REST2 always fails
        (with HTTP status 500), while setting the status works as intended by RT.

        .. note:: Requires RT 5.0.0 or newer.

        :param asset_id: Asset ID.
        :raises NotFoundError: If the asset does not exist.
        :raises NotAllowedError: If the user is not allowed to change the asset.
        :raises InvalidUseError: If RT refused to change the status, e.g. if the lifecycle of the catalog does not
                                 allow it.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        msg = self._list_result(await self._send('PUT', _path('asset', asset_id), json_data={'Status': 'deleted'}))

        # RT returns no message if the asset is already deleted
        for message in msg:
            if not message.endswith('Asset deleted'):
                raise _refusal_error(message)

    async def search_assets(
        self,
        *,
        catalog_id: str | int | None = None,
        search_params: collections.abc.Sequence[collections.abc.Mapping[str, JSONInput]] | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        raw_query: str | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search assets in a catalog, with conditions or an AssetSQL query.

        Example::

            >>> client = AsyncRt(...)
            >>> params = [{"field": "Name", "value": "NameOfMyAsset"}]
            >>> client.search_assets(catalog_id=1, search_params=params, fields="Owner,Status")
            >>> client.search_assets(catalog_id=1, search_params=params, fields=["Owner", "Status"])
            >>> client.search_assets(catalog_id=1, search_params=params, fields={"fields": "Owner,Status", "fields[Owner]": "id,Name"})
            >>> client.search_assets(raw_query="Catalog = 'General assets' AND 'CF.{Asset Type}' LIKE 'Computer'")

        The following is returned for each asset by default (when `fields` is `None`)::

            {
                'Description': '',
                'id': '1',
                '_url': 'http://localhost:8080/REST/2.0/asset/1',
                'Owner': {'_url': 'http://localhost:8080/REST/2.0/user/Nobody', 'id': 'Nobody', 'type': 'user'},
                'Status': 'new',
                'type': 'asset'
            }

        .. note:: Requires RT 5.0.0 or newer.

        :param catalog_id: Catalog ID. Use `None` to search all catalogs.
        :param search_params: Params used to filter the results. Each param is a dictionary with the keys:

            - field: str
            - value: str | int
            - operator: Literal[">", "<", "=", "!=", "LIKE", "NOT LIKE", ">=", "<="] | None

        :param fields: Fields returned for each asset: a comma separated string or list of fields,
                       or a dictionary with query parameters as defined by RT.
        :param raw_query: AssetSQL query, used instead of *catalog_id* and *search_params* (requires RT 5.0.2).
                          It is passed to RT as is, so never include untrusted input in it. RT ignores an invalid
                          query and then returns all assets (RT 6.0.4).
        :returns: Iterator of the found assets.
        :raises InvalidUseError: If *raw_query* is empty or combined with *catalog_id* or *search_params*.
        """
        get_params = _fields_params(fields, default_fields='Owner,Description,Status')

        if raw_query is not None:
            if catalog_id is not None or search_params is not None:
                raise InvalidUseError('raw_query can not be combined with catalog_id or search_params.')
            if not raw_query.strip():
                # RT would return all assets for an empty query
                raise InvalidUseError('raw_query must not be empty.')

            # sent in the body like the TicketSQL query of search()
            async for item in self._paged_request('assets', params=get_params, form_data={'query': raw_query}):
                yield item
            return

        # copy the search parameters, so the list passed by the caller is not modified
        search_params = list(search_params or [])
        if catalog_id is not None:
            # combined with AND also with conditions on Catalog, which RT would combine with OR by default
            search_params.append({'field': 'Catalog', 'value': catalog_id, 'operator': '=', 'entry_aggregator': 'AND'})
        elif not search_params:
            # RT returns no asset for a search without a condition
            search_params = [{'field': 'id', 'operator': '>', 'value': 0}]

        async for item in self._paged_request('assets', json_data=search_params, params=get_params):
            yield item

    async def get_asset_history(self, asset_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get asset history.

        .. note:: Requires RT 5.0.0 or newer.

        :param asset_id: Asset ID.
        :returns: Iterator of transactions, each a dictionary with the same keys as for
                  :py:meth:`get_ticket_history`. Empty if the asset does not exist.
        """
        async for transaction in self._paged_request(
            _path('asset', asset_id, 'history'),
            params={
                'fields': _HISTORY_FIELDS,
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
            },
        ):
            yield transaction

    async def get_all_classes(self, *, include_disabled: bool = False) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get all classes of articles which the user can see.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param include_disabled: Set to True to also return disabled classes.
        :returns: Iterator of the classes, each a dictionary with the keys id, type, _url, Name, Description and
                  Disabled.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int] = {'fields': 'Name,Description,Disabled', 'find_disabled_rows': int(include_disabled)}

        async for item in self._paged_request('classes/all', params=params):
            yield item

    async def search_classes(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search classes of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'FAQ'}]``. All classes if not specified.
        :param fields: Fields returned for each class: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description and Disabled.
        :param include_disabled: Set to True to also return disabled classes.
        :returns: Iterator of the found classes.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._search_objects('classes', search_params, fields, 'Name,Description,Disabled', include_disabled=include_disabled):
            yield item

    async def get_class(self, class_id: str | int) -> dict[str, typing.Any]:
        """Get a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :returns: The class as dictionary, e.g. with the keys id, Name, Description, Disabled and
                  ArticleCustomFields (the custom fields of its articles, e.g. Content).
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('class', class_id)))

    async def create_class(self, name: str, **kwargs: JSONInput) -> int:
        """Create a class of articles.

        RT applies the custom field Content for the text of articles to new classes.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param name: Name of the class, which must be unique.
        :param kwargs: Other fields to set, e.g. Description or SortOrder.
        :returns: ID of the new class.
        :raises BadRequestError: If RT rejects the request, e.g. if a class with the name exists.
        :raises NotAllowedError: If the user is not allowed to create classes.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', 'class', json_data={'Name': name, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_class(self, class_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :param kwargs: Fields to set, e.g. Name, Description, SortOrder, Disabled. RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('class', class_id), json_data=kwargs))

    async def delete_class(self, class_id: str | int) -> None:
        """Disable a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('class', class_id))

    async def search_articles(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search articles.

        Example::

            >>> tracker.search_articles(search_params=[{'field': 'Class', 'value': 1}, {'field': 'Name', 'operator': 'LIKE', 'value': 'VPN'}])

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'VPN'}]``. All articles if not
                              specified.
        :param fields: Fields returned for each article: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Summary, Class and Disabled.
        :param include_disabled: Set to True to also return disabled (deleted) articles.
        :returns: Iterator of the found articles.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._search_objects('articles', search_params, fields, 'Name,Summary,Class,Disabled', include_disabled=include_disabled):
            yield item

    async def get_article(self, article_id: str | int) -> dict[str, typing.Any]:
        """Get an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :returns: The article as dictionary, e.g. with the keys id, Name, Summary, Class, Disabled and CustomFields,
                  which contain its text in the custom field Content.
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('article', article_id)))

    async def create_article(self, name: str, class_id: str | int, **kwargs: JSONInput) -> int:
        """Create an article.

        Example::

            >>> tracker.create_article('VPN setup', 'FAQ', Summary='How to set up the VPN', CustomFields={'Content': 'Install ...'})

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param name: Name of the article, which must be unique in its class.
        :param class_id: Identification of the class by name (str) or ID (int).
        :param kwargs: Other fields to set, e.g. Summary, SortOrder, or CustomFields, e.g.
                       ``CustomFields={'Content': 'Text of the article'}``.
        :returns: ID of the new article.
        :raises BadRequestError: If RT rejects the request, e.g. if an article with the name exists in the class
                                 (RT reports this only as "Create failed for unknown reason").
        :raises NotAllowedError: If the user is not allowed to create articles in the class, or the class does not
                                 exist (RT returns status code 403 for both).
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', 'article', json_data={'Name': name, 'Class': class_id, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_article(self, article_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :param kwargs: Fields to set, e.g. Name, Summary, SortOrder, or CustomFields, e.g.
                       ``CustomFields={'Content': 'New text'}``. RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('article', article_id), json_data=kwargs))

    async def delete_article(self, article_id: str | int) -> None:
        """Delete (disable) an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected, e.g. if the article is already
                                         deleted (RT fails with HTTP status 500 then).
        """
        await self._delete(_path('article', article_id))

    async def get_article_history(self, article_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the history of an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :returns: Iterator of transactions, each a dictionary with the same keys as for
                  :py:meth:`get_ticket_history`. Empty if the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for transaction in self._paged_request(
            _path('article', article_id, 'history'),
            params={
                'fields': _HISTORY_FIELDS,
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
            },
        ):
            yield transaction

    async def search_custom_fields(
        self,
        *,
        object_type: CustomFieldObjectType | None = None,
        object_id: str | int | None = None,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search custom fields, all or those applied to a queue, catalog or class.

        Example::

            >>> tracker.search_custom_fields(object_type='queue', object_id=1)
            >>> tracker.search_custom_fields(search_params=[{'field': 'LookupType', 'value': 'RT::Queue-RT::Ticket'}])

        .. note:: Requires RT 5.0.0 or newer.

        :param object_type: ``'queue'``, ``'catalog'`` or ``'class'`` to search only the custom fields applied to
                            the object *object_id*, ``None`` (default) to search all custom fields.
        :param object_id: ID of the queue, catalog or class (RT does not support names here).
        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'Severity'}]``. All custom fields if not specified.
        :param fields: Fields returned for each custom field: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Name, Type, Description,
                       LookupType, MaxValues and Disabled.
        :param include_disabled: Set to True to also return disabled custom fields.
        :returns: Iterator of the found custom fields.
        :raises InvalidUseError: If *object_type* is not supported, or only one of *object_type* and *object_id*
                                 is specified.
        :raises NotFoundError: If the queue, catalog or class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if (object_type is None) != (object_id is None):
            raise InvalidUseError('object_type and object_id must be specified together.')

        if object_type is None:
            selector = 'customfields'
        else:
            if object_type not in VALID_CUSTOM_FIELD_OBJECT_TYPES:
                raise InvalidUseError(f'Unsupported object type. Use one of "{", ".join(VALID_CUSTOM_FIELD_OBJECT_TYPES)}".')
            selector = _path(object_type, typing.cast('str | int', object_id), 'customfields')

        search_params = list(search_params or [])
        if not search_params and object_type is None:
            # RT returns no custom field for a search of all custom fields without a condition
            search_params = [{'field': 'id', 'operator': '>', 'value': 0}]

        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields='Name,Type,Description,LookupType,MaxValues,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._paged_request(selector, json_data=search_params, params=params):
            yield item

    async def get_custom_field(self, custom_field_id: str | int) -> dict[str, typing.Any]:
        """Get a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :returns: The custom field as dictionary, including the names of its values in the key Values for the
                  type Select.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('customfield', custom_field_id)))

    async def create_custom_field(self, name: str, field_type: str, lookup_type: str, **kwargs: JSONInput) -> int:
        """Create a custom field.

        Example::

            >>> tracker.create_custom_field('Severity', 'Select', 'RT::Queue-RT::Ticket', MaxValues=1, Queue='General')

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Name of the custom field. RT does not require it to be unique.
        :param field_type: Type of the custom field, e.g. Freeform, Select, Text, Wikitext, Image, Binary, Combobox,
                           Autocomplete, Date, DateTime, IPAddress or IPAddressRange.
        :param lookup_type: Type of the objects the custom field is for, e.g. ``'RT::Queue-RT::Ticket'`` (tickets),
                            ``'RT::Queue-RT::Ticket-RT::Transaction'`` (ticket transactions), ``'RT::Queue'``,
                            ``'RT::User'``, ``'RT::Group'``, ``'RT::Catalog-RT::Asset'`` (assets) or
                            ``'RT::Class-RT::Article'`` (articles).
        :param kwargs: Other fields to set, e.g. Description, MaxValues (0 for unlimited, 1 for a single value),
                       Pattern, EntryHint, SortOrder, or Queue (name or ID of a single queue to apply a ticket custom
                       field to, see :py:meth:`apply_custom_field` for more and for other lookup types).
        :returns: ID of the new custom field.
        :raises InvalidUseError: If Queue is specified for another lookup type than ``'RT::Queue-RT::Ticket'``,
                                 as RT would then silently create a ticket custom field.
        :raises BadRequestError: If RT rejects the request, e.g. for an invalid type or an unknown queue.
        :raises NotAllowedError: If the user is not allowed to create custom fields.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if 'Queue' in kwargs and lookup_type != 'RT::Queue-RT::Ticket':
            raise InvalidUseError('Queue can only be specified for ticket custom fields, use apply_custom_field() for other lookup types.')

        response = await self._send('POST', 'customfield', json_data={'Name': name, 'Type': field_type, 'LookupType': lookup_type, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_custom_field(self, custom_field_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param kwargs: Fields to set, e.g. Name, Description, MaxValues, Pattern, EntryHint, SortOrder, Disabled.
                       RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed or rejected field (empty if nothing was changed).
                  RT reports invalid values only in these messages, e.g. ``'CustomField 1: Illegal value for Type'``,
                  while the other fields are still changed.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('customfield', custom_field_id), json_data=kwargs))

    async def delete_custom_field(self, custom_field_id: str | int) -> None:
        """Disable a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('customfield', custom_field_id))

    async def get_custom_field_applies_to(self, custom_field_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the objects which a custom field is applied to.

        This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :returns: Iterator of the objects, each a dictionary with the keys ObjectId, ObjectType, ObjectName and _url,
                  e.g. ``{'ObjectId': 1, 'ObjectType': 'RT::Queue', 'ObjectName': 'General', ...}``, or
                  ``{'ObjectId': 0, 'Global': True}`` if the custom field is applied globally.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._paged_request(_path('customfield', custom_field_id, 'appliesto')):
            yield item

    async def apply_custom_field(self, custom_field_id: str | int, object_id: int) -> list[str]:
        """Apply a custom field to an object, e.g. a ticket custom field to a queue.

        The type of the object is determined by the lookup type of the custom field, e.g. a queue for a ticket
        custom field. This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param object_id: ID of the object (RT does not support names here), or 0 to apply the custom field
                          globally, which removes it from all objects it was applied to.
        :returns: Status messages of RT, e.g. ``['Added custom field Severity to General.']``.
        :raises BadRequestError: If RT rejects the request, e.g. if the object or the custom field does not exist.
        :raises ConflictError: If the custom field is already applied to the object.
        :raises NotAllowedError: If the user is not allowed to apply the custom field.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', _path('customfield', custom_field_id, 'appliesto'), json_data={'ObjectId': object_id})
        result = self._dict_result(response)

        message = result.get('message')
        if not isinstance(message, str):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        return [message]

    async def unapply_custom_field(self, custom_field_id: str | int, object_id: int) -> None:
        """Remove a custom field from an object it is applied to.

        This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param object_id: ID of the object (RT does not support names here), or 0 to remove the global application.
        :raises NotFoundError: If the custom field is not applied to the object.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('customfield', custom_field_id, 'appliesto', 'object', object_id))

    async def get_custom_field_values(
        self,
        custom_field_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the values of a custom field, e.g. the selectable values of the type Select.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'High'}]``. All values if not specified.
        :returns: Iterator of the values, each a dictionary with the keys id, name, type and _url.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._paged_request(_path('customfield', custom_field_id, 'values'), json_data=list(search_params or [])):
            yield item

    async def get_custom_field_value(self, custom_field_id: str | int, value_id: str | int) -> dict[str, typing.Any]:
        """Get a value of a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :returns: The value as dictionary, e.g. with the keys id, Name, Description, Category and SortOrder.
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('customfield', custom_field_id, 'value', value_id)))

    async def add_custom_field_value(self, custom_field_id: str | int, name: str, **kwargs: JSONInput) -> int:
        """Add a value to a custom field, e.g. a selectable value of the type Select.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param name: The value. RT does not require it to be unique.
        :param kwargs: Other fields to set, e.g. Description, Category, SortOrder.
        :returns: ID of the new value.
        :raises BadRequestError: If RT rejects the request.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('POST', _path('customfield', custom_field_id, 'value'), json_data={'Name': name, **kwargs})

        return int(self._created_id(self._dict_result(response)))

    async def edit_custom_field_value(self, custom_field_id: str | int, value_id: str | int, **kwargs: JSONInput) -> list[str]:
        """Edit a value of a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :param kwargs: Fields to set, e.g. Name, Description, Category, SortOrder. RT ignores unknown fields.
        :returns: Status messages of RT, one for each changed field (empty if nothing was changed).
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._list_result(await self._send('PUT', _path('customfield', custom_field_id, 'value', value_id), json_data=kwargs))

    async def delete_custom_field_value(self, custom_field_id: str | int, value_id: str | int) -> None:
        """Remove a value from a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._delete(_path('customfield', custom_field_id, 'value', value_id))

    async def get_custom_field_file(self, value_id: str | int) -> bytes:
        """Get the content of a file stored as value of an Image or Binary custom field of an object, e.g. a ticket.

        The custom field values of a ticket or asset contain a ``_url`` like ``.../REST/2.0/download/cf/12`` for
        each file, its last part is the ID. To set a file as value, pass an :py:class:`~rt.common.Attachment`
        converted with ``to_dict()``, e.g. ``edit_ticket(1, CustomFields={'Screenshot': attachment.to_dict()})``.

        .. note:: Requires RT 5.0.0 or newer.

        :param value_id: ID of the custom field value of the object (not of a value of the custom field).
        :returns: Content of the file.
        :raises NotAllowedError: If the value does not exist or the user is not allowed to see it
                                 (RT returns status code 403 for both).
        :raises RtConnectionError: In case of a connection error.
        """
        response = await self._send('GET', _path('download', 'cf', value_id))

        return response.content

    async def search_custom_roles(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search custom roles.

        Custom roles can only be read with REST2, not created or changed.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`search_assets`, e.g.
                              ``[{'field': 'Name', 'value': 'Manager'}]``. All custom roles if not specified.
        :param fields: Fields returned for each custom role: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Name, Description, MaxValues,
                       LookupType and Disabled.
        :param include_disabled: Set to True to also return disabled custom roles.
        :returns: Iterator of the found custom roles.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._search_objects(
            'customroles', search_params, fields, 'Name,Description,MaxValues,LookupType,Disabled', include_disabled=include_disabled
        ):
            yield item

    async def get_custom_role(self, custom_role_id: str | int) -> dict[str, typing.Any]:
        """Get a custom role.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_role_id: ID of the custom role (RT does not support names here).
        :returns: The custom role as dictionary, e.g. with the keys id, Name, Description, MaxValues (1 for a single
                  member, 0 for several), LookupType, EntryHint and Disabled.
        :raises NotFoundError: If the custom role does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', _path('customrole', custom_role_id)))

    @staticmethod
    def _rights_object(object_type: RightsObjectType, object_id: str | int | None) -> tuple[str | int, ...]:
        """Return the path segments of the object of rights.

        :raises InvalidUseError: If the object type is not supported, or the object ID is missing or specified for
                                 global rights.
        """
        if object_type not in VALID_RIGHTS_OBJECT_TYPES:
            raise InvalidUseError(f'Unsupported object type. Use one of "{", ".join(VALID_RIGHTS_OBJECT_TYPES)}".')

        if object_type == 'global':
            if object_id is not None:
                raise InvalidUseError('object_id must not be specified for global rights.')
            return ('global',)

        if object_id is None or object_id == '':
            raise InvalidUseError(f'object_id is required for rights on a {object_type}.')

        return (object_type, object_id)

    @staticmethod
    def _principal(user: str | int | None, group: str | int | None) -> tuple[typing.Literal['user', 'group'], str | int]:
        """Return the type and the identification of the user or group given for rights.

        :raises InvalidUseError: If not exactly one of user and group is specified.
        """
        if (user is None) == (group is None):
            raise InvalidUseError('Specify either user or group.')

        if user is not None:
            return 'user', user

        return 'group', typing.cast('str | int', group)

    async def get_rights(
        self,
        object_type: RightsObjectType,
        object_id: str | int | None = None,
        *,
        user: str | int | None = None,
        group: str | int | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the rights granted on an object or globally.

        Example::

            >>> tracker.get_rights('queue', 'General')
            >>> tracker.get_rights('global', user='alice')

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param object_type: Type of the object: ``'queue'``, ``'group'``, ``'class'``, ``'catalog'``,
                            ``'customfield'``, or ``'global'`` for the rights granted on the whole system.
        :param object_id: Name or ID of the queue, class or catalog, or ID of the group or custom field.
                          Not specified for global rights.
        :param user: Only return the rights granted to this user, identified by name (str) or ID (int). No rights
                     are returned for a user which does not exist.
        :param group: Only return the rights granted to this group, identified by ID (RT does not support names here,
                      a name matches no rights).
        :returns: Iterator of the granted rights, each a dictionary with the key Right and either User or Group,
                  e.g. ``{'Right': 'CreateTicket', 'Group': {'id': 7, 'Name': 'Staff', '_url': '...'}}``.
        :raises InvalidUseError: If the object type is not supported, the object ID is missing or specified for
                                 global rights, or both user and group are specified.
        :raises NotFoundError: If the object does not exist.
        :raises NotAllowedError: If the user is not allowed to see the rights.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        selector = _path(*self._rights_object(object_type, object_id), 'rights')

        if user is not None and group is not None:
            raise InvalidUseError('Specify either user or group, but not both.')

        params: dict[str, str | int] = {}
        if user is not None:
            params['user'] = user
        if group is not None:
            params['group'] = group

        async for item in self._paged_request(selector, params=params):
            # RT ignores the filter for a user which does not exist and returns all rights, so check the user as well
            if user is not None and not self._is_rights_user(item, user):
                continue
            yield item

    @staticmethod
    def _is_rights_user(item: dict[str, typing.Any], user: str | int) -> bool:
        """Check whether a granted right returned by RT is granted to the given user (by ID or by name)."""
        principal = item.get('User')
        if not isinstance(principal, dict):
            return False

        if isinstance(user, int) or user.isdigit():
            return str(principal.get('id')) == str(user)

        # RT loads users by name case insensitively
        return str(principal.get('Name', '')).casefold() == user.casefold()

    async def get_available_rights(self, object_type: RightsObjectType, object_id: str | int | None = None) -> dict[str, dict[str, str]]:
        """Get the rights which can be granted on an object or globally, grouped by category.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param object_type: Type of the object, see :py:meth:`get_rights`.
        :param object_id: Identification of the object, see :py:meth:`get_rights`. Not specified for global rights.
        :returns: Dictionary of the categories (e.g. General, Staff, Admin, Status), each a dictionary of the rights
                  and their descriptions, e.g. ``{'General': {'CreateTicket': 'Create tickets in this queue', ...}}``.
        :raises InvalidUseError: If the object type is not supported, or the object ID is missing or specified for
                                 global rights.
        :raises NotFoundError: If the object does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._send('GET', _path(*self._rights_object(object_type, object_id), 'rights', 'available'))
        result = self._dict_result(response)

        categories: dict[str, dict[str, str]] = {}
        for category, rights in result.items():
            if not isinstance(rights, dict) or not all(isinstance(description, str) for description in rights.values()):
                raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)
            categories[category] = typing.cast('dict[str, str]', rights)

        return categories

    async def grant_right(
        self,
        object_type: RightsObjectType,
        object_id: str | int | None,
        right: str,
        *,
        user: str | int | None = None,
        group: str | int | None = None,
    ) -> dict[str, typing.Any]:
        """Grant a right on an object or globally to a user or group.

        Example::

            >>> tracker.grant_right('queue', 'General', 'CreateTicket', group=7)
            >>> tracker.grant_right('global', None, 'SuperUser', user='alice')

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param object_type: Type of the object, see :py:meth:`get_rights`.
        :param object_id: Identification of the object, see :py:meth:`get_rights`. ``None`` for global rights.
        :param right: Name of the right, e.g. CreateTicket (see :py:meth:`get_available_rights`).
        :param user: User to grant the right to, identified by name (str) or ID (int).
        :param group: Group to grant the right to, identified by ID (only IDs are supported, as RT does not
                      support group names when revoking rights).
        :returns: The granted right, e.g. ``{'Right': 'CreateTicket', 'Group': {'id': 7, 'Name': 'Staff', ...}}``.
        :raises InvalidUseError: If the object type is not supported, the object ID is missing or specified for
                                 global rights, or not exactly one of user and group is specified.
        :raises BadRequestError: If RT rejects the request, e.g. for an unknown right, user or group.
        :raises ConflictError: If the right is already granted.
        :raises NotFoundError: If the object does not exist.
        :raises NotAllowedError: If the user is not allowed to grant rights on the object.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        selector = _path(*self._rights_object(object_type, object_id), 'rights')
        principal_type, principal = self._principal(user, group)

        if principal_type == 'user' and isinstance(principal, str):
            json_data: dict[str, JSONInput] = {'Right': right, 'User': principal}
        else:
            json_data = {'Right': right, principal_type.capitalize(): {'id': principal}}

        return self._dict_result(await self._send('POST', selector, json_data=json_data))

    async def revoke_right(
        self,
        object_type: RightsObjectType,
        object_id: str | int | None,
        right: str,
        *,
        user: str | int | None = None,
        group: str | int | None = None,
    ) -> None:
        """Revoke a right on an object or globally from a user or group.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param object_type: Type of the object, see :py:meth:`get_rights`.
        :param object_id: Identification of the object, see :py:meth:`get_rights`. ``None`` for global rights.
        :param right: Name of the right, e.g. CreateTicket.
        :param user: User to revoke the right from, identified by name (str) or ID (int).
        :param group: Group to revoke the right from, identified by ID (RT does not support group names here).
        :raises InvalidUseError: If the object type is not supported, the object ID is missing or specified for
                                 global rights, or not exactly one of user and group is specified.
        :raises NotFoundError: If the right is not granted to the user or group, or the object, user or group
                               does not exist (RT returns status code 404 for all of them).
        :raises NotAllowedError: If the user is not allowed to revoke rights on the object.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        principal_type, principal = self._principal(user, group)

        await self._delete(_path(*self._rights_object(object_type, object_id), 'rights', right, principal_type, principal))

    async def get_system_info(self) -> dict[str, typing.Any]:
        """Get information about the RT system.

        .. note:: Requires RT 5.0.0 or newer.

        :returns: Dictionary with the RT version and the installed plugins, e.g.
                  ``{'Version': '6.0.4', 'Plugins': []}``.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._dict_result(await self._send('GET', 'rt'))
