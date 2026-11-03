"""Common code shared by the sync and async REST2 implementations."""

import base64
import collections.abc
import dataclasses
import re
import typing
import urllib.parse

from ._messages import Kind, classify
from .exceptions import InvalidUseError, NotAllowedError, NotFoundError

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


# The Literal types are used for type checking, the tuples derived from them for checks at runtime.
TicketLinkName: typing.TypeAlias = typing.Literal['Parent', 'Child', 'RefersTo', 'ReferredToBy', 'DependsOn', 'DependedOnBy']
VALID_TICKET_LINK_NAMES: tuple[str, ...] = typing.get_args(TicketLinkName)

ContentType: typing.TypeAlias = typing.Literal['text/plain', 'text/html']
VALID_CONTENT_TYPES: tuple[str, ...] = typing.get_args(ContentType)

# Formats of the results of a ticket search: only IDs, IDs and subjects, or many fields.
SearchFormat: typing.TypeAlias = typing.Literal['i', 's', 'l']

# Fields returned for each ticket by a ticket search with format 'l'.
_SEARCH_LONG_FORMAT_FIELDS = (
    'Owner,Status,Created,Subject,Queue,CustomFields,Requestor,Cc,AdminCc,Started,TimeEstimated,Due,Type,InitialPriority,Priority,TimeLeft,LastUpdated'
)

# Objects on which rights can be granted with REST2; 'global' grants rights on the whole system.
RightsObjectType: typing.TypeAlias = typing.Literal['queue', 'group', 'class', 'catalog', 'customfield', 'global']
VALID_RIGHTS_OBJECT_TYPES: tuple[str, ...] = typing.get_args(RightsObjectType)

# Objects whose custom fields can be searched with REST2.
CustomFieldObjectType: typing.TypeAlias = typing.Literal['queue', 'catalog', 'class']
VALID_CUSTOM_FIELD_OBJECT_TYPES: tuple[str, ...] = typing.get_args(CustomFieldObjectType)

# Actions for adding a message to a ticket.
_CorrespondAction: typing.TypeAlias = typing.Literal['correspond', 'comment']
_CORRESPOND_ACTIONS: tuple[str, ...] = typing.get_args(_CorrespondAction)

# JSON data as decoded from a response of RT.
JSONValue: typing.TypeAlias = str | int | float | bool | None | list['JSONValue'] | dict[str, 'JSONValue']

# JSON data sent to RT. The read-only collection types also accept e.g. a ``dict[str, str]`` or ``list[str]``.
JSONInput: typing.TypeAlias = str | int | float | bool | None | collections.abc.Sequence['JSONInput'] | collections.abc.Mapping[str, 'JSONInput']

# Query parameters added to the URL of a request.
QueryParams: typing.TypeAlias = collections.abc.Mapping[str, str | int]

# Conditions of a JSON search of REST2, e.g. ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'Support'}]``.
JSONSearchParams: typing.TypeAlias = collections.abc.Sequence[collections.abc.Mapping[str, JSONInput]]

# Fields of the transactions returned by the history methods. RT returns the field Description always empty in
# collections, as it is no attribute of transactions; Field, OldValue, NewValue and Data describe a change.
_HISTORY_FIELDS = 'Type,Field,OldValue,NewValue,Data,TimeTaken,Creator,Created,_hyperlinks'

# Names (ref) of the links between tickets in the hyperlinks of a ticket.
_LINK_REFS = frozenset({'depends-on', 'depended-on-by', 'parent', 'child', 'refers-to', 'referred-to-by'})

# Fields which can be set when creating or editing a user.
_USER_FIELDS = frozenset(
    {
        'Name',
        'Password',
        'EmailAddress',
        'RealName',
        'NickName',
        'Gecos',
        'Organization',
        'Address1',
        'Address2',
        'City',
        'State',
        'Zip',
        'Country',
        'HomePhone',
        'WorkPhone',
        'MobilePhone',
        'PagerPhone',
        'FreeformContactInfo',
        'Comments',
        'Signature',
        'Lang',
        'Timezone',
        'SMIMECertificate',
        'Privileged',
        'Disabled',
        'CustomFields',
    }
)

# Fields which can be set when creating or editing a queue.
_QUEUE_FIELDS = frozenset(
    {
        'Name',
        'Description',
        'CorrespondAddress',
        'CommentAddress',
        'Disabled',
        'SLADisabled',
        'Lifecycle',
        'SortOrder',
        'SubjectTag',
        'CustomFields',
        'Cc',
        'AdminCc',
    }
)

# Request headers which are not written to the debug log, as they contain credentials.
_REDACTED_HEADERS = frozenset({'authorization', 'proxy-authorization', 'cookie'})

# Operators which can be used in searches by appending their name to a field name, e.g. Subject__like='foo'.
_SEARCH_OPERATORS = {
    'exact': '=',
    'notexact': '!=',
    'gt': '>',
    'gte': '>=',
    'lt': '<',
    'lte': '<=',
    'like': ' LIKE ',
    'notlike': ' NOT LIKE ',
    'startswith': ' STARTSWITH ',
    'notstartswith': ' NOT STARTSWITH ',
    'endswith': ' ENDSWITH ',
    'notendswith': ' NOT ENDSWITH ',
    'is': ' IS ',
    'isnot': ' IS NOT ',
}


def _path(*segments: str | int) -> str:
    """Build the path of an API endpoint from its segments, e.g. ``_path('user', user_name)``.

    Each segment is percent-encoded, so IDs and names (e.g. of users or queues) can not change the requested
    endpoint, e.g. by containing "/", "?", "#" or "..".
    """
    encoded_segments = []
    for segment in segments:
        encoded_segment = urllib.parse.quote(str(segment), safe='')
        # quote() does not encode dots, but the segments "." and ".." would be resolved as relative path
        if encoded_segment in ('.', '..'):
            encoded_segment = encoded_segment.replace('.', '%2E')
        encoded_segments.append(encoded_segment)

    return '/'.join(encoded_segments)


# Field names of TicketSQL which are used without quotes, e.g. Subject or Requestor.EmailAddress.
_PLAIN_FIELD_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*')


def _quote_value(value: object) -> str:
    """Quote a value for use in a TicketSQL query.

    Backslashes and single quotes are escaped, so the value can not change the meaning of the query.
    """
    escaped = str(value).replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _build_ticket_query(queue: str | None, raw_query: str | None, conditions: collections.abc.Mapping[str, object]) -> str:
    """Build a TicketSQL query for searching tickets.

    :param queue: Queue to search in, or None to search in all queues.
    :param raw_query: TicketSQL query which is used as is instead of the conditions.
    :param conditions: Field names, optionally with an operator suffix (e.g. ``Subject__like``), and the values
                       to search for. All values and field names other than plain names like ``Subject`` or
                       ``Requestor.EmailAddress`` are quoted, so they can not change the meaning of the query.
    :returns: The query, all parts combined with AND.
    :raises InvalidUseError: If an unsupported operator is used.
    """
    query = []

    if queue is not None:
        query.append(f'Queue={_quote_value(queue)}')

    if raw_query:
        query.append(raw_query)
    else:
        for argument, value in conditions.items():
            key, separator, operator_name = argument.rpartition('__')
            if not separator:
                key, operator_name = argument, 'exact'

            operator = _SEARCH_OPERATORS.get(operator_name)
            if operator is None:
                raise InvalidUseError(f'Unsupported operator "{operator_name}" in "{argument}".')

            if operator_name in ('is', 'isnot'):
                # TicketSQL only supports IS (NOT) NULL
                if value is not None and str(value).upper() != 'NULL':
                    raise InvalidUseError(f'Operator "{operator_name}" only supports the value None in "{argument}".')
                query_value = 'NULL'
            else:
                query_value = _quote_value(value)

            if key.startswith('CF_'):
                # custom field names may contain spaces and other special characters, so quote them as well
                key = _quote_value(f'CF.{{{key[3:]}}}')
            elif not _PLAIN_FIELD_NAME.fullmatch(key):
                # e.g. 'CustomRole.{Manager}'; quoted like values, so names can not change the meaning of the query
                key = _quote_value(key)

            query.append(f'{key}{operator}{query_value}')

    return ' AND '.join(f'({part})' for part in query)


def _search_fields_params(fields: SearchFormat | list[str] | dict[str, str]) -> dict[str, str]:
    """Return the query parameters selecting the fields returned for each ticket by a ticket search.

    :param fields: 'i' (only IDs), 's' (IDs and subjects), 'l' (many fields), a list of fields,
                   or a dictionary with the query parameters to use.
    """
    if isinstance(fields, list):
        return {'fields': ','.join(field.strip() for field in fields)}

    if isinstance(fields, dict):
        return dict(fields)

    if fields == 'l':
        return {'fields': _SEARCH_LONG_FORMAT_FIELDS, 'fields[Queue]': 'Name'}

    if fields == 's':
        return {'fields': 'Subject'}

    # 'i': only the IDs are returned
    return {}


def _fields_params(fields: str | list[str] | dict[str, str] | None, default_fields: str) -> dict[str, str]:
    """Return the query parameters selecting the fields returned for each item.

    :param fields: A comma separated string or a list of fields, which replace the default fields,
                   or a dictionary with query parameters, which are added to the default fields.
    :param default_fields: Fields returned if *fields* is None.
    """
    params = {'fields': default_fields}

    if isinstance(fields, dict):
        params.update(fields)
    elif isinstance(fields, list):
        params['fields'] = ','.join(field.strip() for field in fields)
    elif isinstance(fields, str):
        # RT does not strip spaces, e.g. 'Name, Description' would request the unknown field ' Description'
        params['fields'] = ','.join(field.strip() for field in fields.split(','))

    return params


def _check_fields(fields: collections.abc.Iterable[str], valid_fields: frozenset[str]) -> None:
    """Check that all given field names are supported.

    :raises InvalidUseError: If any of the fields is not supported.
    """
    invalid_fields = [field for field in fields if field not in valid_fields]
    if invalid_fields:
        raise InvalidUseError(f'Unsupported names of fields: {", ".join(invalid_fields)}.')


_ERROR_TYPES: dict[Kind, type[NotFoundError | NotAllowedError | InvalidUseError]] = {
    Kind.NOT_FOUND: NotFoundError,
    Kind.DENIED: NotAllowedError,
    Kind.REFUSED: InvalidUseError,
}


def _message_error_type(message: str) -> type[NotFoundError | NotAllowedError | InvalidUseError] | None:
    """Return the exception type for a status message of RT which reports a refused change.

    :param message: Status message of RT, e.g. "Ticket 1: Queue Support does not exist".
    :returns: The exception type, or ``None`` if the message is a success or not in the catalog of messages
              (:py:mod:`rt._messages`), i.e. unrecognized.
    """
    kind = classify(message)

    return _ERROR_TYPES.get(kind) if kind else None


def _refusal_error(message: str) -> NotFoundError | NotAllowedError | InvalidUseError:
    """Return the exception for an action which RT refused, e.g. with the status ``0`` of a group member.

    :param message: Status message of RT, e.g. "That user already owns that ticket".
    :returns: :py:exc:`NotAllowedError` if RT denied the permission, :py:exc:`NotFoundError` if an object does not
              exist, else :py:exc:`InvalidUseError` (also for messages which are not in the catalog).
    """
    return (_message_error_type(message) or InvalidUseError)(message)


def _raise_for_messages(messages: collections.abc.Iterable[str]) -> None:
    """Raise an exception if one of the status messages of RT reports a refused change.

    Messages which are not in the catalog of messages are not an error.
    RT changes all fields it accepts and reports the others only as message, so the other changes were made anyway.

    :param messages: Status messages of RT returned for a change.
    :raises NotFoundError: If an object (e.g. a user or queue) does not exist.
    :raises NotAllowedError: If the permission was denied.
    :raises InvalidUseError: If RT refused a value, e.g. an invalid status.
    """
    refused = [(error_type, message) for message in messages if (error_type := _message_error_type(message))]

    if refused:
        # the most specific error first: not found, permission, other
        error_type = next((t for t in (NotFoundError, NotAllowedError, InvalidUseError) if any(r[0] is t for r in refused)), InvalidUseError)
        raise error_type('; '.join(message for _, message in refused))


@dataclasses.dataclass(frozen=True, slots=True)
class ActionResult:
    """Result of a change, returned by all methods which change something.

    RT answers a change with HTTP status 200 and status messages, also if it refused all or a part of it. RT changes
    all fields it accepts and reports the ones it refuses (e.g. an invalid status) only as message. The result is
    always true, i.e. ``if tracker.tickets.comment(...)`` means that the request was executed by RT, like the ``bool`` returned
    in earlier versions. Methods which change one thing (e.g. ``take()``) raise an exception if RT refuses the change,
    as nothing was changed; the other methods (e.g. ``tickets.edit()``, ``reply()``) do not, as parts of the change were
    made. Use :py:attr:`complete`, :py:attr:`refused` or :py:meth:`raise_for_refused` to find out if RT refused a part
    of the change.

    A message of RT which is not in the catalog of the library is neither a success nor a refusal, it is listed in
    :py:attr:`unrecognized`. It is no error for the methods which can change something partly (e.g. ``tickets.edit()``);
    the methods which change one thing and where the message is the only information about the result (e.g. ``take()``)
    raise :py:exc:`~rt.exceptions.UnexpectedResponseError`, as the change may not have been made.

    .. note:: The messages of RT are recognized in English only. The language of the user of the API in RT must
              be set to English (``en``), else refused parts are not detected: :py:attr:`refused` is empty and all
              messages are :py:attr:`unrecognized`.

    Instances are immutable.

    Example::

        >>> result = tracker.tickets.edit(1, Subject='New', Status='invalid')
        >>> bool(result)  # RT changed the subject
        True
        >>> result.complete
        False
        >>> result.refused
        ("Ticket 1: Status 'invalid' isn't a valid status for this ticket.",)
        >>> result.raise_for_refused()
        Traceback (most recent call last):
        rt.exceptions.InvalidUseError: Ticket 1: Status 'invalid' isn't a valid status for this ticket.
    """

    messages: tuple[str, ...]
    """All status messages returned by RT, e.g. ``("Ticket 1: Subject changed from 'a' to 'b'",)``. Empty if nothing was changed."""

    refused: tuple[str, ...] = dataclasses.field(init=False, repr=False, compare=False)
    """The messages of RT which report a refused part of the change (empty if RT refused nothing)."""

    unrecognized: tuple[str, ...] = dataclasses.field(init=False, repr=False, compare=False)
    """The messages of RT which are not known to the library (e.g. a new message of a newer RT, or in another language)."""

    def __post_init__(self) -> None:
        """Classify the messages once, the instance is immutable."""
        object.__setattr__(self, 'refused', tuple(message for message in self.messages if _message_error_type(message)))
        object.__setattr__(self, 'unrecognized', tuple(message for message in self.messages if classify(message) is None))

    def __bool__(self) -> bool:
        """Return ``True``: RT executed the request, also if it refused a part of it."""
        return True

    @property
    def complete(self) -> bool:
        """``True`` if RT did not refuse a part of the change."""
        return not self.refused

    def raise_for_refused(self) -> None:
        """Raise an exception if RT refused a part of the change.

        The accepted parts were changed anyway. If several parts were refused, the exception of the most specific
        kind is raised and its message contains all refused messages.

        :raises NotFoundError: If an object (e.g. a user or queue) does not exist.
        :raises NotAllowedError: If the permission was denied.
        :raises InvalidUseError: If RT refused a value, e.g. an invalid status.
        """
        _raise_for_messages(self.messages)


@dataclasses.dataclass(frozen=True, slots=True)
class Attachment:
    """An attachment to add to a ticket, e.g. when creating, replying to or commenting on it.

    Instances are immutable.
    """

    file_name: str
    file_type: str
    file_content: bytes

    def to_dict(self) -> dict[str, str]:
        """Convert to a dictionary for submitting to the REST API."""
        return {
            'FileName': self.file_name,
            'FileType': self.file_type,
            'FileContent': base64.b64encode(self.file_content).decode('utf-8'),
        }

    def multipart_form_element(self) -> tuple[str, bytes, str]:
        """Convert to a tuple as required for multipart-form-data submission."""
        return (
            self.file_name,
            self.file_content,
            self.file_type,
        )
