"""Tickets of the REST2 client: the tickets and their history, messages, attachments and links, and the actions on them."""

import collections.abc
import datetime as dt
import re
import typing

from rt._rest2_async.transport import _AsyncTransport
from rt.common import (
    _CORRESPOND_ACTIONS,
    _HISTORY_FIELDS,
    _LINK_REFS,
    _TICKET_FIELDS,
    VALID_CONTENT_TYPES,
    ActionResult,
    Attachment,
    ContentType,
    JSONInput,
    JSONSearchParams,
    SearchFormat,
    SortOrder,
    TicketLinkName,
    _build_ticket_query,
    _CorrespondAction,
    _fields_params,
    _order_params,
    _path,
    _search_fields_params,
)
from rt.exceptions import (
    InvalidUseError,
    UnexpectedResponseError,
)


class AsyncTickets:
    """Tickets of RT: the tickets and their history, messages, attachments and links, and the actions on them.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.tickets``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    def new_correspondence(
        self,
        *,
        queue: str | None = None,
        order: SortOrder = '-LastUpdated',
        fields: SearchFormat | list[str] | dict[str, str] = 'l',
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed by other users than the one used for the connection.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue: Queue where to search
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``. Default: the most recently updated first.
        :param fields: Fields returned for each ticket, see :py:meth:`search`.

        :returns: Iterator of tickets which were last updated by another user than
                  the one used for the connection, ordered in decreasing order by LastUpdated.
                  Each ticket is a dictionary, the same as in
                  :py:meth:`~AsyncTickets.search`.
        """
        # RT replaces __CurrentUser__ with the user who executes the search
        return self.search(queue=queue, order=order, fields=fields, LastUpdatedBy__notexact='__CurrentUser__')

    def last_updated(
        self,
        since: str | dt.date | dt.datetime,
        *,
        queue: str | None = None,
        order: SortOrder = '-LastUpdated',
        fields: SearchFormat | list[str] | dict[str, str] = 'l',
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Obtains tickets changed after given date.

        .. note:: Requires RT 5.0.0 or newer.

        :param since: Date and optionally time after which the tickets were changed:

                      - :py:class:`datetime.datetime` with timezone: exact point in time.
                      - :py:class:`datetime.datetime` without timezone, :py:class:`datetime.date` or
                        string in form '2011-02-24', optionally followed by a time, e.g. '2011-02-24 13:45:00':
                        interpreted by RT in the timezone of the RT user (or the default timezone of RT).
        :param queue: Queue where to search
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``. Default: the most recently updated first.
        :param fields: Fields returned for each ticket, see :py:meth:`search`.

        :returns: Iterator of tickets with LastUpdated parameter later than
                  *since* ordered in decreasing order by LastUpdated.
                  Each ticket is a dictionary, the same as in
                  :py:meth:`~AsyncTickets.get`.

        :raises InvalidUseError: If the specified date is of an unsupported format.
        """
        since_value = self._date_to_string(since)
        if not self._validate_date(since_value):
            raise InvalidUseError(f'Invalid date specified - "{since}"')

        return self.search(queue=queue, order=order, fields=fields, LastUpdated__gt=since_value)

    async def get(self, ticket_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Fetch ticket by its ID.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of demanded ticket
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Owner]': 'Name,EmailAddress'}``. RT always returns all fields of
                       the ticket itself, so a list of fields as in :py:meth:`~AsyncTickets.search` is not supported.

        :returns: The ticket as dictionary with the keys id, EffectiveId, Type, Queue, Subject, Status, Owner,
                  Creator, LastUpdatedBy, Requestor, Cc, AdminCc, CustomRoles, CustomFields, Priority,
                  InitialPriority, FinalPriority, Created, LastUpdated, Starts, Started, Due, Resolved,
                  TimeEstimated, TimeWorked, TotalTimeWorked, TimeLeft and _hyperlinks.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        """
        response = await self._t.send('GET', _path('ticket', ticket_id), params={'fields[Queue]': 'Name', **(fields or {})})

        return self._t.dict_result(response)

    async def create(
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
        self._t.warn_unknown_fields(kwargs, _TICKET_FIELDS, 'tickets.create')
        if content_type not in VALID_CONTENT_TYPES:
            raise InvalidUseError('Invalid content-type specified.')

        ticket_data: dict[str, JSONInput] = {'Queue': queue}

        if subject is not None:
            ticket_data['Subject'] = subject

        if content is not None:
            ticket_data['Content'] = content
            ticket_data['ContentType'] = content_type

        ticket_data.update(kwargs)

        response = await self._t.send('POST', 'ticket', json_data=ticket_data, attachments=attachments)

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit(self, ticket_id: str | int, **kwargs: JSONInput) -> ActionResult:
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
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _TICKET_FIELDS, 'tickets.edit')
        msg = self._t.list_result(await self._t.send('PUT', _path('ticket', ticket_id), json_data=kwargs))

        return self._t.result(msg)

    async def delete(self, ticket_id: str | int) -> None:
        """Mark a ticket as deleted.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket
        :raises NotFoundError: If the ticket does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('ticket', ticket_id))

    async def search(
        self,
        *,
        queue: str | None = None,
        order: SortOrder | None = None,
        raw_query: str | None = None,
        fields: SearchFormat | list[str] | dict[str, str] = 'l',
        conditions: collections.abc.Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search arbitrary needles in given fields and queue.

        Example::

            >>> tracker.tickets.search(CF_Domain='example.com', Subject__like='warning')
            >>> tracker.tickets.search(conditions={'CF_Contact Email': 'a@example.com', 'Status': 'open'})
            >>> tracker.tickets.search(queue='General', order='Status', raw_query="id = 1 OR id = 2 OR id = 3")

        The query is sent in the body of a POST request, so it is not limited by the maximum length of URLs and does
        not appear in the access logs of RT or of proxies in front of it.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue:      Queue where to search. If you wish to search across
                           all of your queues, pass None as the argument.
        :param order:      Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'`` for the
                           newest tickets first, or a list of them, e.g. ``['Status', '-Created']``.
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
        get_params: dict[str, str | int | list[str]] = {**_order_params(order), **_search_fields_params(fields)}

        async for item in self._t.paged_request('tickets', params=get_params, form_data={'query': query}):
            yield item

    async def history(
        self,
        ticket_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get set of short history items.

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ID of ticket
        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g. only
                              the changes of the status: ``[{'field': 'Type', 'value': 'Status'}]``.
        :param fields: Fields returned for each transaction: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT, e.g. ``{'fields[Creator]': 'Name'}``.
                       Defaults to the fields listed below.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``. Default: oldest first.
        :returns: Iterator of the transactions of the ticket, oldest first, each a dictionary with the keys id, type,
                  _url, Type (e.g. Create, Correspond, Comment, Status, Set, CustomField), Field (the changed field,
                  e.g. Owner), OldValue, NewValue, Data (e.g. the subject of a message), TimeTaken, Creator (a
                  dictionary with id, Name, RealName and EmailAddress), Created and _hyperlinks. Use
                  :py:meth:`messages` for the text of messages. Empty if the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'transactions', 'tickets.history')
        async for transaction in self._t.paged_request(
            _path('ticket', ticket_id, 'history'),
            json_data=list(search_params) if search_params else None,
            params={
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
                **_fields_params(fields, default_fields=_HISTORY_FIELDS),
                **_order_params(order),
            },
        ):
            yield transaction

    async def get_transaction(self, transaction_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a transaction.

        .. note:: Requires RT 5.0.0 or newer.

        :param transaction_id: ID of transaction
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the transaction itself.
        :returns: The transaction as dictionary, e.g. with the keys id, Type, Data, Content (text of a message),
                  ContentType, TimeTaken, Object (the ticket, asset etc.), Creator, Created, CustomFields and
                  _hyperlinks (also to its attachments), and for changes Field, OldValue and NewValue.
        :raises UnexpectedResponseError: If the response from RT is not as expected,
                                         e.g. if the transaction does not exist (RT returns status code 500).
        """
        return self._t.dict_result(await self._t.send('GET', _path('transaction', transaction_id), params=fields))

    async def search_transactions(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        raw_query: str | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search transactions, e.g. of a ticket or across tickets, with conditions or a TransactionSQL query.

        Example::

            >>> tracker.tickets.search_transactions(search_params=[{'field': 'ObjectId', 'value': 1}, {'field': 'Type', 'value': 'Comment'}])
            >>> tracker.tickets.search_transactions(raw_query="Type = 'Correspond' AND Created > '2024-01-01'", fields=['Type', 'Content'])

        Conditions on different fields are combined with AND, several conditions on the same field with OR (see the
        REST2 documentation of RT on JSON searches). The query is sent in the body of a POST request like the one of
        :py:meth:`search`.

        .. note:: Requires RT 5.0.0 or newer, *raw_query* requires RT 5.0.2 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'ObjectType', 'value': 'RT::Ticket'}, {'field': 'ObjectId', 'value': 1}]``.
        :param raw_query: TransactionSQL query, used instead of *search_params*, e.g.
                          ``"ObjectType = 'RT::Ticket' AND ObjectId = 1 AND Type = 'Comment'"``. It is passed to RT
                          as is, so never include untrusted input in it.
        :param fields: Fields returned for each transaction: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Type, Created, Creator,
                       ObjectType and ObjectId. ``Content`` returns the text of messages, see
                       :py:meth:`messages`.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``.
        :returns: Iterator of the found transactions.
        :raises InvalidUseError: If not exactly one of *search_params* and *raw_query* is specified, or *raw_query* is
                                 empty.
        :raises BadRequestError: If the TransactionSQL query is invalid.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'transactions', 'tickets.search_transactions')
        if (search_params is None) == (raw_query is None):
            raise InvalidUseError('Specify either search_params or raw_query.')

        params: dict[str, str | int | list[str]] = {
            **_fields_params(fields, default_fields='Type,Created,Creator,ObjectType,ObjectId'),
            **_order_params(order),
        }

        if raw_query is not None:
            if not raw_query.strip():
                raise InvalidUseError('raw_query must not be empty.')
            transactions = self._t.paged_request('transactions', params=params, form_data={'query': raw_query})
        else:
            transactions = self._t.paged_request('transactions', json_data=list(search_params or []), params=params)

        async for item in transactions:
            yield item

    async def messages(self, ticket_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the messages of a ticket, i.e. its creation, replies and comments with their text, oldest first.

        Unlike :py:meth:`history` followed by :py:meth:`get_transaction` for each entry, this needs only one
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

        async for item in self._t.paged_request('transactions', json_data=search_params, params=params):
            yield item

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
    ) -> ActionResult:
        """Sends email message to the contacts in ``Requestors`` field of
        given ticket with subject as is set in ``Subject`` field.

        .. note:: Requires RT 5.0.0 or newer.

        There is no one-off Cc or Bcc for a single message, as REST2 does not support it: a ``Cc`` sent to RT would
        replace the Cc watchers of the ticket. Add watchers with :py:meth:`edit` (which replaces them too) or use
        the ``cc``/``bcc`` of the REST1 :py:meth:`rt.rest1.Rt.reply`.

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
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
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

        return self._t.result(msg)

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
    ) -> ActionResult:
        """Adds comment to the given ticket.

        .. note:: Requires RT 5.0.0 or newer.

        There is no one-off Cc or Bcc for a single message, as REST2 does not support it: a ``Cc`` sent to RT would
        replace the Cc watchers of the ticket. Add watchers with :py:meth:`edit` (which replaces them too) or use
        the ``cc``/``bcc`` of the REST1 :py:meth:`rt.rest1.Rt.comment`.

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
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
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

        return self._t.result(msg)

    async def get_attachments(
        self,
        ticket_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        files_only: bool = True,
        order: SortOrder | None = None,
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
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``.
        :returns: Iterator of attachments belonging to given ticket.
        :raises NotFoundError: If the ticket does not exist.
        :raises NotAllowedError: If the user is not allowed to see the ticket.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'attachments', 'tickets.get_attachments')
        get_params = {**_fields_params(fields, default_fields='Filename,ContentType,ContentLength'), **_order_params(order)}

        await self._check_ticket(ticket_id)
        async for item in self._t.paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=self._attachment_conditions(search_params, files_only=files_only),
            params=get_params,
        ):
            yield item

    async def get_attachments_ids(
        self,
        ticket_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        files_only: bool = True,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[int]:
        """Get IDs of attachments for given ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket
        :param search_params: Conditions of the search, see :py:meth:`get_attachments`.
        :param files_only: Set to False to also return the other parts of messages, see :py:meth:`get_attachments`.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``.
        :returns: Iterator of IDs (type int) of attachments belonging to given
                  ticket.
        :raises NotFoundError: If the ticket does not exist.
        :raises NotAllowedError: If the user is not allowed to see the ticket.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'attachments', 'tickets.get_attachments_ids')
        await self._check_ticket(ticket_id)
        async for item in self._t.paged_request(
            _path('ticket', ticket_id, 'attachments'),
            json_data=self._attachment_conditions(search_params, files_only=files_only),
            params=_order_params(order),
        ):
            attachment_id = item.get('id')
            if not isinstance(attachment_id, (str, int)):
                raise UnexpectedResponseError(f'Attachment without ID: {item}')
            yield int(attachment_id)

    async def get_attachment(self, attachment_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get attachment.

        .. note:: Requires RT 5.0.0 or newer.

        :param attachment_id: ID of attachment to fetch
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the attachment itself.
        :returns: Attachment as dictionary with the keys id, TransactionId, Parent, ContentType, Filename, Subject,
                  MessageId, Creator, Created, Headers, _hyperlinks and Content (base64 encoded string).
                  'Headers' holds the headers of the attachment as string (one header per line), e.g.
                  Content-Type, Content-Disposition and for emails From, To, Subject or Message-ID. Which headers
                  exist depends on the mail servers which sent the email, not on RT.

        :raises UnexpectedResponseError: If the response from RT is not as expected, e.g. if the attachment does not
                                         exist (RT returns status code 500).
        """
        return self._t.dict_result(await self._t.send('GET', _path('attachment', attachment_id), params=fields))

    async def search_attachments(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        files_only: bool = True,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search attachments across all tickets, e.g. files by name, content type or creation time.

        Example::

            >>> tracker.tickets.search_attachments(search_params=[{'field': 'Filename', 'operator': 'LIKE', 'value': '.pdf'},
            ...                                                   {'field': 'Created', 'operator': '>', 'value': '2024-01-01'}])

        RT stores each message as several attachments: the parts of the email, i.e. a container, the text of the
        message and each file. By default only files (attachments with a file name) are returned. RT only returns
        attachments which the user is allowed to see.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'ContentType', 'value': 'application/pdf'}]``. Fields which can be searched
                              are e.g. Filename, ContentType, Subject, Created, Creator and TransactionId, but not
                              ContentLength (RT computes it, it is not stored). All attachments if not specified.
        :param fields: Fields returned for each attachment: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Filename, ContentType, ContentLength,
                       TransactionId and Created. Use :py:meth:`get_attachment` for the content: RT returns the field
                       Content in search results not base64 encoded, so binary content can not be represented
                       reliably. Do not request the field Parent, RT fails with HTTP status 500 for it (RT 6.0.4).
        :param files_only: Set to False to also return the other parts of messages, e.g. the text of a message.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Status', '-Created']``.
        :returns: Iterator of the found attachments.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'attachments', 'tickets.search_attachments')
        params = {**_fields_params(fields, default_fields='Filename,ContentType,ContentLength,TransactionId,Created'), **_order_params(order)}

        async for item in self._t.paged_request('attachments', json_data=self._attachment_conditions(search_params, files_only=files_only), params=params):
            yield item

    async def get_links(self, ticket_id: str | int) -> list[dict[str, typing.Any]]:
        """Get the links of a ticket.

        Example of a return result, for a ticket depending on ticket 7 and referring to an asset and a URL:

        .. code-block:: json

            [
                {"ref": "depends-on", "type": "ticket", "id": 7, "_url": "http://localhost:8080/REST/2.0/ticket/7"},
                {"ref": "refers-to", "type": "asset", "id": 3, "_url": "http://localhost:8080/REST/2.0/asset/3"},
                {"ref": "refers-to", "type": "external", "_url": "https://wiki.example.com/printers"}
            ]

        .. note:: Requires RT 5.0.0 or newer.

        :param ticket_id: ticket ID
        :returns: The links of the ticket, each a dictionary with the keys ref (the kind of link: depends-on,
                  depended-on-by, parent, child, refers-to or referred-to-by), type (ticket, asset, or external for a
                  link to a URL), _url and id (the ID of the linked ticket or asset).
        :raises NotFoundError: If there is no ticket with the specified ticket_id.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        ticket = await self.get(ticket_id)

        return [link for link in ticket['_hyperlinks'] if link.get('ref') in _LINK_REFS]

    async def edit_link(
        self,
        ticket_id: str | int,
        link_name: TicketLinkName,
        link_value: str | int,
        *,
        delete: bool = False,
    ) -> ActionResult:
        """Add or delete a single link of a ticket, keeping its other links.

        Example::

            >>> tracker.tickets.edit_link(1, 'DependsOn', 7)
            >>> tracker.tickets.edit_link(1, 'RefersTo', 'asset:3')
            >>> tracker.tickets.edit_link(1, 'RefersTo', 'https://wiki.example.com/printers')
            >>> tracker.tickets.edit_link(1, 'DependsOn', 7, delete=True)

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 ignores the request, so
                  :py:exc:`~rt.exceptions.UnexpectedResponseError` is raised.

        :param ticket_id: ID of ticket to edit
        :param link_name: Name of link to edit ('Parent', 'Child', 'RefersTo',
                          'ReferredToBy', 'DependsOn', 'DependedOnBy')
        :param link_value: The linked object: the ID of a ticket, an asset as ``'asset:3'``, or a URL.
        :param delete: if True the link is deleted instead of created
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises NotFoundError: If the ticket or the linked object does not exist.
        :raises InvalidUseError: If the link name is not supported or RT does not allow the link,
                                 e.g. to a deleted ticket or from a ticket to itself, or if RT
                                 could not create or delete the link.
        :raises NotAllowedError: If the user is not allowed to change the links of the ticket.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        return await self._t.edit_link('ticket', ticket_id, link_name, link_value, delete=delete)

    async def merge(self, ticket_id: str | int, into_id: str | int) -> ActionResult:
        """Merge ticket into another.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 ignores the request, so
                  :py:exc:`~rt.exceptions.UnexpectedResponseError` is raised.

        :param ticket_id: ID of ticket to be merged
        :param into_id: ID of destination ticket
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises NotFoundError: If the ticket to be merged or the destination ticket does not exist.
        :raises InvalidUseError: If RT refused the merge, e.g. of a ticket into itself.
        :raises NotAllowedError: If the user is not allowed to merge the tickets.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        msg = self._t.list_result(await self._t.send('PUT', _path('ticket', ticket_id), json_data={'MergeInto': into_id}))

        if not msg:
            # RT 5.0.0 ignores MergeInto
            raise UnexpectedResponseError('RT did not merge the ticket (tickets can be merged with RT 5.0.1 or newer).')
        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        return self._t.done(msg)

    async def take(self, ticket_id: str | int) -> ActionResult:
        """Take ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be taken
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the user already owns the ticket.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        return await self._change_owner(ticket_id, 'take')

    async def untake(self, ticket_id: str | int) -> ActionResult:
        """Untake ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be untaken
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the ticket is not owned.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        return await self._change_owner(ticket_id, 'untake')

    async def steal(self, ticket_id: str | int) -> ActionResult:
        """Steal ticket.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param ticket_id: ID of ticket to be stolen
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises InvalidUseError: If RT refused to change the owner, e.g. if the ticket is not owned by another user.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises NotFoundError: If the ticket does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        return await self._change_owner(ticket_id, 'steal')

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

        # No one-shot Cc/Bcc: REST2 (up to RT 6.0.4 at least) builds the message only from Content, ContentType and
        # Subject, and passes the whole body to the update of the roles of the ticket, so "Cc" would REPLACE the Cc
        # watchers of the ticket and "Bcc" is ignored (checked with RT 6.0.4, see python-rt PR #101). The web UI uses
        # CcMessageTo/BccMessageTo of RT::Ticket->Correspond/Comment, which REST2 does not expose.

        response = await self._t.send('POST', _path('ticket', ticket_id, action), json_data=post_data, attachments=attachments)

        return self._t.list_result(response)

    async def _check_ticket(self, ticket_id: str | int) -> None:
        """Check that the ticket exists and that the user may see it.

        For ``ticket/<id>/attachments``, RT (6.0.4 at least) searches the attachments of all tickets if the ticket does
        not exist or the user may not see it, so the attachments of other tickets would be returned.

        :raises NotFoundError: If the ticket does not exist.
        :raises NotAllowedError: If the user is not allowed to see the ticket.
        """
        await self._t.send('GET', _path('ticket', ticket_id))

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

    async def _change_owner(self, ticket_id: str | int, action: typing.Literal['take', 'untake', 'steal']) -> ActionResult:
        """Take, untake or steal a ticket.

        :param ticket_id: ID of ticket
        :param action: The action to execute
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises InvalidUseError: If RT refused to change the owner.
        :raises NotAllowedError: If the user is not allowed to change the owner.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        msg = self._t.list_result(await self._t.send('PUT', _path('ticket', ticket_id, action)))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        return self._t.done(msg)
