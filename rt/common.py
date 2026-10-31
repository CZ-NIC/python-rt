"""Common code shared by the sync and async REST2 implementations."""

import base64
import collections.abc
import dataclasses
import re
import typing
import urllib.parse

from .exceptions import InvalidUseError

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
    'Owner,Status,Created,Subject,Queue,CustomFields,Requestor,Cc,AdminCc,Started,Created,TimeEstimated,Due,Type,'
    'InitialPriority,Priority,TimeLeft,LastUpdated'
)

# Actions for adding a message to a ticket.
_CorrespondAction: typing.TypeAlias = typing.Literal['correspond', 'comment']
_CORRESPOND_ACTIONS: tuple[str, ...] = typing.get_args(_CorrespondAction)

# JSON data as decoded from a response of RT.
JSONValue: typing.TypeAlias = str | int | float | bool | None | list['JSONValue'] | dict[str, 'JSONValue']

# JSON data sent to RT. The read-only collection types also accept e.g. a ``dict[str, str]`` or ``list[str]``.
JSONInput: typing.TypeAlias = (
    str | int | float | bool | None | collections.abc.Sequence['JSONInput'] | collections.abc.Mapping[str, 'JSONInput']
)

# Query parameters added to the URL of a request.
QueryParams: typing.TypeAlias = collections.abc.Mapping[str, str | int]

# Matches the messages RT returns when a referenced user, queue or resource does not exist, e.g.
# "That user does not exist" or "Ticket 1: Queue Support does not exist".
REGEX_PATTERNS = {'does_not_exist': re.compile(r'\b(?:user|queue|resource)\b(?: .+)? does not exist$', re.IGNORECASE)}

# Fields which can be set when creating or editing a user.
_USER_FIELDS = frozenset(
    {
        'Name',
        'Password',
        'EmailAddress',
        'RealName',
        'Nickname',
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
        'ContactInfo',
        'Comments',
        'Signature',
        'Lang',
        'EmailEncoding',
        'WebEncoding',
        'ExternalContactInfoId',
        'ContactInfoSystem',
        'ExternalAuthId',
        'AuthSystem',
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
    }
)

# Request headers which are not written to the debug log, as they contain credentials.
_REDACTED_HEADERS = frozenset({'authorization', 'proxy-authorization', 'cookie'})


SelfT = typing.TypeVar('SelfT')

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
                       to search for. All values are quoted, so they can not change the meaning of the query.
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

            query.append(f'{key}{operator}{query_value}')

    return ' AND '.join(f'({part})' for part in query)


def _search_fields_params(query_format: SearchFormat | list[str] | dict[str, str]) -> dict[str, str]:
    """Return the query parameters selecting the fields returned for each ticket by a ticket search.

    :param query_format: 'i' (only IDs), 's' (IDs and subjects), 'l' (many fields), a list of fields,
                         or a dictionary with the query parameters to use.
    """
    if isinstance(query_format, list):
        return {'fields': ','.join(query_format)}

    if isinstance(query_format, dict):
        return dict(query_format)

    if query_format == 'l':
        return {'fields': _SEARCH_LONG_FORMAT_FIELDS, 'fields[Queue]': 'Name'}

    if query_format == 's':
        return {'fields': 'Subject'}

    # 'i': only the IDs are returned
    return {}


def _fields_params(query_format: str | list[str] | dict[str, str] | None, default_fields: str) -> dict[str, str]:
    """Return the query parameters selecting the fields returned for each item.

    :param query_format: A comma separated string or a list of fields, which replace the default fields,
                         or a dictionary with query parameters, which are added to the default fields.
    :param default_fields: Fields returned if *query_format* is None.
    """
    params = {'fields': default_fields}

    if isinstance(query_format, dict):
        params.update(query_format)
    elif isinstance(query_format, list):
        params['fields'] = ','.join(query_format)
    elif isinstance(query_format, str):
        params['fields'] = query_format

    return params


def _check_fields(fields: collections.abc.Iterable[str], valid_fields: frozenset[str]) -> None:
    """Check that all given field names are supported.

    :raises InvalidUseError: If any of the fields is not supported.
    """
    invalid_fields = [field for field in fields if field not in valid_fields]
    if invalid_fields:
        raise InvalidUseError(f'Unsupported names of fields: {", ".join(invalid_fields)}.')


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
