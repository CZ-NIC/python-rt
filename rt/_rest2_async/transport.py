"""Transport of the REST2 client: sends the requests to RT and decodes its responses, shared by all areas."""

import collections.abc
import datetime as dt
import json
import logging
import ssl
import types
import typing
from urllib.parse import urljoin

import httpx2

from rt.common import (
    _REDACTED_HEADERS,
    _SEARCHABLE_FIELDS,
    VALID_TICKET_LINK_NAMES,
    ActionResult,
    Attachment,
    JSONInput,
    JSONSearchParams,
    JSONValue,
    QueryParams,
    SortOrder,
    TicketLinkName,
    _fields_params,
    _message_error_type,
    _order_params,
    _path,
    _unknown_fields,
)
from rt.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    InvalidUseError,
    NotAllowedError,
    NotFoundError,
    RtConnectionError,
    UnexpectedResponseError,
)


class _AsyncTransport:
    """Sends the requests to RT and decodes its responses.

    The areas of the API (tickets, users, ...) use it, the user of the library uses :py:class:`AsyncRt`.
    """

    def __init__(
        self,
        *,
        logger: logging.Logger,
        url: str,
        proxy: str | None = None,
        verify_cert: str | bool = True,
        http_auth: httpx2.Auth | None = None,
        token: str | None = None,
        http_timeout: float | None = 20,
        per_page: int = 100,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        """Initialization, see :py:class:`AsyncRt` for the parameters."""
        self.logger = logger

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

    async def send(
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
        :raises NotAllowedError: The user is not allowed to execute the request (HTTP/403, or HTTP/400 with the message
                                 "Permission Denied").
        :raises NotFoundError: Resource was not found.
        :raises ConflictError: The request conflicts with the state of the resource (HTTP/409), e.g. a right is
                               already granted.
        :raises UnexpectedResponseError: Server returned an unexpected status code.
        """
        status_code = response.status_code
        text = response.text

        if status_code == 400:
            message = cls._error_message(response, 'Bad request')

            # RT answers with HTTP status 400 if the user may not add a message to a ticket
            if _message_error_type(message) is NotAllowedError:
                raise NotAllowedError(message, status_code=status_code, response_message=text)

            raise BadRequestError(message, status_code=status_code, response_message=text)

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
    def decode_json(response: httpx2.Response) -> JSONValue:
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
    def dict_result(cls, response: httpx2.Response) -> dict[str, JSONValue]:
        """Return the JSON body of a response, which must be a dictionary.

        :raises UnexpectedResponseError: If the body is not a JSON object.
        """
        result = cls.decode_json(response)

        if not isinstance(result, dict):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        return result

    @classmethod
    def list_result(cls, response: httpx2.Response) -> list[str]:
        """Return the JSON body of a response, which must be a list of strings (e.g. status messages).

        :raises UnexpectedResponseError: If the body is not a JSON array of strings.
        """
        result = cls.decode_json(response)

        if not isinstance(result, list):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        messages = []
        for message in result:
            if not isinstance(message, str):
                raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)
            messages.append(message)

        return messages

    def warn_unknown_fields(self, fields: collections.abc.Iterable[str], known: frozenset[str], method: str) -> None:
        """Log a warning for field names of a create or edit which are not known to the library.

        The fields are sent to RT as they are: newer versions of RT or extensions may support them. RT ignores fields
        it does not know without any message.

        :param fields: The names of the fields to set.
        :param known: The field names known to the library.
        :param method: Name of the method, for the message, e.g. ``tickets.edit``.
        """
        unknown = _unknown_fields(fields, known)
        if unknown:
            self.logger.warning(
                '%s: field(s) not known to the library, sent to RT as they are (RT ignores fields it does not know): %s',
                method,
                ', '.join(unknown),
            )

    def warn_unknown_conditions(self, search_params: JSONSearchParams | None, collection: str, method: str) -> None:
        """Log a warning for fields of search conditions which are not known to the library.

        RT ignores conditions on fields it can not search, so the search may return more objects than intended (for
        users and groups even all of them). The conditions are sent to RT as they are: newer versions of RT may
        support more fields.

        :param search_params: The conditions of the search.
        :param collection: The endpoint of the search, e.g. ``users``, which selects the known fields.
        :param method: Name of the method, for the message, e.g. ``users.search``.
        """
        names = [condition['field'] for condition in search_params or [] if isinstance(condition.get('field'), str)]
        unknown = _unknown_fields(typing.cast('list[str]', names), _SEARCHABLE_FIELDS[collection], conditions=True)
        if unknown:
            self.logger.warning(
                '%s: condition(s) on field(s) not known to the library, sent to RT as they are (RT ignores conditions on fields '
                'it can not search, so more objects may be found): %s',
                method,
                ', '.join(unknown),
            )

    def result(self, messages: list[str]) -> ActionResult:
        """Log the status messages of RT for a change which RT may have applied only partly and return the result."""
        self.logger.debug('RT status messages: %s', messages)

        return ActionResult(tuple(messages))

    def done(self, messages: list[str]) -> ActionResult:
        """Return the result of an action which RT makes completely or not at all, e.g. taking a ticket.

        RT answers with HTTP status 200 also if it refuses the action and the messages are the only information, so all
        of them must be known to the library: an exception is raised for a refusal, and for a message which is not in the
        catalog (e.g. of another language of RT or a newer RT), as the action may not have been made.

        :param messages: Status messages of RT.
        :raises NotFoundError: If RT reports that an object does not exist.
        :raises NotAllowedError: If RT reports that the permission was denied.
        :raises InvalidUseError: If RT reports that it refused the action.
        :raises UnexpectedResponseError: If RT answers with a message which is not known to the library.
        """
        result = self.confirmed(messages)

        if result.unrecognized:
            raise UnexpectedResponseError(
                f'RT answered with a message which is not known to the library, the action may not have been made (is the language of the user English?): {list(result.unrecognized)}'
            )

        return result

    def confirmed(self, messages: list[str]) -> ActionResult:
        """Return the result of an action for which RT tells if it succeeded without the messages (a status, or an HTTP error).

        An exception is raised for a refusal known to the library. Other messages are no error, they are listed in
        :py:attr:`~rt.common.ActionResult.unrecognized`.

        :param messages: Status messages of RT.
        :raises NotFoundError: If RT reports that an object does not exist.
        :raises NotAllowedError: If RT reports that the permission was denied.
        :raises InvalidUseError: If RT reports that it refused the action.
        """
        result = self.result(messages)
        result.raise_for_refused()

        return result

    @staticmethod
    def created_id(result: dict[str, JSONValue]) -> str:
        """Return the ID of an object created by RT, which is returned as string.

        :raises UnexpectedResponseError: If the result does not contain an ID.
        """
        object_id = result.get('id')

        if not isinstance(object_id, (str, int)):
            raise UnexpectedResponseError(f'Response does not contain the ID of the created object: {result}')

        return str(object_id)

    async def delete(self, selector: str) -> None:
        """Send a DELETE request to the :term:`API`.

        :param selector: End part of URL which completes self.url parameter
                           set during class initialization.
                           E.g.: ``ticket/123456``
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self.send('DELETE', selector)

        # RT confirms a deletion with 204 (No Content). Any other successful response must
        # still be valid JSON, so e.g. an HTML page returned by a proxy is not taken as success.
        if response.status_code != 204:
            self.decode_json(response)

    async def paged_request(
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
            result = self.dict_result(await self.send(method, selector, params=page_params, json_data=json_data, form_data=form_data))

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

    async def search_objects(
        self,
        selector: str,
        search_params: JSONSearchParams | None,
        fields: str | list[str] | dict[str, str] | None,
        default_fields: str,
        *,
        include_disabled: bool = False,
        order: SortOrder | None = None,
        method: str,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search objects with a JSON search, e.g. queues or classes.

        :param selector: Endpoint of the search, e.g. ``queues``.
        :param search_params: Conditions of the search. All objects if not specified: RT returns no object for a
                              search without a condition, so a condition matching all objects is sent instead.
        :param fields: Fields returned for each object, see :py:meth:`~AsyncAssets.search`.
        :param default_fields: Fields returned if *fields* is not specified.
        :param include_disabled: Set to True to also return disabled objects.
        :param order: Sort order, e.g. ``'-Created'`` or ``['Status', '-Created']``.
        :param method: Name of the calling method, for the warning about unknown fields, e.g. ``queues.search``.
        :returns: Iterator of the found objects.
        """
        self.warn_unknown_conditions(search_params, selector, method)
        conditions = list(search_params or [])
        if not conditions:
            conditions = [{'field': 'id', 'operator': '>', 'value': 0}]

        params: dict[str, str | int | list[str]] = {
            **_fields_params(fields, default_fields=default_fields),
            **_order_params(order),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self.paged_request(selector, json_data=conditions, params=params):
            yield item

    async def edit_link(
        self,
        object_type: typing.Literal['ticket', 'asset'],
        object_id: str | int,
        link_name: TicketLinkName,
        link_value: str | int,
        *,
        delete: bool,
    ) -> ActionResult:
        """Add or delete a single link of a ticket or asset, see :py:meth:`~AsyncTickets.edit_link`."""
        if link_name not in VALID_TICKET_LINK_NAMES:
            raise InvalidUseError(f'Unsupported link name. Use one of "{", ".join(VALID_TICKET_LINK_NAMES)}".')

        # Add<link name> and Delete<link name> change single links; the link name alone replaces all links of the type
        json_data = {f'{"Delete" if delete else "Add"}{link_name}': link_value}

        msg = self.list_result(await self.send('PUT', _path(object_type, object_id), json_data=json_data))

        # RT always reports the result for a link, so an empty result means RT ignored the request (RT 5.0.0)
        if not msg:
            raise UnexpectedResponseError('RT did not change the link (links can be changed with RT 5.0.1 or newer).')

        # RT reports a link which exists (or does not exist when deleting) as message, this is not a refusal.
        # "Permission denied" is returned if StrictLinkACL is enabled and the user may not change the linked object.
        return self.done(msg)
