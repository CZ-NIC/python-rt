"""Regression tests for fixes in the REST2 implementation.

The sync tests (test_rest2_fixes.py) are generated from the async tests (test_rest2_fixes_async.py) using unasyncd.
"""

# ruff: noqa: S101, S106

import base64
import builtins
import collections.abc
import datetime as dt
import json
import logging
import pathlib
import typing
import urllib.parse

import httpx2
import pytest

import rt.exceptions
from rt.common import _HISTORY_FIELDS
from rt.rest2_async import AsyncRt

from . import no_type_checks, random_string
from .conftest import RT_CUSTOM_FIELD, RT_CUSTOM_ROLE, RT_PASSWORD, RT_QUEUE, RT_TOKEN, RT_URL, RT_USER, requires_rt_setup

UNREACHABLE_URL = 'http://127.0.0.1:1/REST/2.0/'

T = typing.TypeVar('T')


async def _collect(iterator: collections.abc.AsyncIterator[T]) -> list[T]:
    """Return all items of an iterator as list."""
    return [item async for item in iterator]


def _mock_client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> AsyncRt:
    """Return a client which sends all requests to the given handler instead of RT."""
    return AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def _page(page: int, items: list, pages: int | None, next_page: bool = False, per_page: int = 100) -> httpx2.Response:
    """Return a paginated response like RT does."""
    result: dict[str, typing.Any] = {
        'page': page,
        'per_page': per_page,
        'pages': pages,
        'total': None if pages is None else len(items),
        'count': len(items),
        'items': items,
    }
    if next_page:
        result['next_page'] = f'{RT_URL}tickets?page={page + 1}'
    return httpx2.Response(200, json=result)


def _query(request: httpx2.Request) -> str:
    """Return the query of a search, which is sent in the form encoded body of a POST request, not in the URL."""
    assert request.method == 'POST'
    assert 'query' not in request.url.params
    (query,) = urllib.parse.parse_qs(request.content.decode(), keep_blank_values=True)['query']
    return query


def _no_request(request: httpx2.Request) -> httpx2.Response:
    """Handler for tests which must not send any request."""
    raise AssertionError('no request must be sent')


# --- search query building ---------------------------------------------------------------------------------------


async def test_search_value_with_quote_and_backslash(async_rt_connection: AsyncRt):
    subject = f"O'Brien \\ {random_string()}"
    ticket_id = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=subject, content='Test')

    found = [int(ticket['id']) async for ticket in async_rt_connection.tickets.search(queue=RT_QUEUE, Subject=subject)]

    assert found == [ticket_id]


async def test_search_value_can_not_alter_query(async_rt_connection: AsyncRt):
    await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=f'Injection test {random_string()}', content='Test')

    # without quoting this would be: Subject='x' OR Subject LIKE '' -> all tickets
    found = await _collect(async_rt_connection.tickets.search(queue=RT_QUEUE, Subject="x' OR Subject LIKE '"))

    assert found == []


async def test_search_queue_with_quote(async_rt_connection: AsyncRt):
    assert await _collect(async_rt_connection.tickets.search(queue="Gen'eral")) == []


async def test_search_custom_field(async_rt_connection: AsyncRt):
    # previously the query was malformed and RT returned an error
    assert await _collect(async_rt_connection.tickets.search(queue=RT_QUEUE, CF_Foo='bar')) == []
    assert await _collect(async_rt_connection.tickets.search(queue=RT_QUEUE, conditions={'CF_Foo Bar': "it's", 'CF_Foo__like': 'x'})) == []


@requires_rt_setup
async def test_custom_field(async_rt_connection: AsyncRt):
    # the name of the custom field contains a quote and a space, the values a quote and a backslash
    value = f"it's \\ {random_string()}"
    # the tickets of this test are found by their subject, as other tests (running in parallel) create tickets in the same queue
    tag = random_string()
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject=f'Test {tag}', content='Test', CustomFields={RT_CUSTOM_FIELD: value})
    other_id = await async_rt_connection.tickets.create(RT_QUEUE, subject=f'Test {tag}', content='Test')

    def custom_field_values(ticket: dict[str, typing.Any]) -> list[str]:
        return next(cf['values'] for cf in ticket['CustomFields'] if cf['name'] == RT_CUSTOM_FIELD)

    assert custom_field_values(await async_rt_connection.tickets.get(ticket_id)) == [value]
    assert custom_field_values(await async_rt_connection.tickets.get(other_id)) == []

    async def search(condition: str, search_value: object) -> list[int]:
        conditions = {f'CF_{RT_CUSTOM_FIELD}{condition}': search_value, 'Subject__like': tag}
        return sorted([int(ticket['id']) async for ticket in async_rt_connection.tickets.search(queue=RT_QUEUE, conditions=conditions, fields='i')])

    assert await search('', value) == [ticket_id]
    assert await search('__like', value[-8:]) == [ticket_id]
    assert await search('__notexact', value) == [other_id]
    assert await search('__is', None) == [other_id]
    assert await search('__isnot', None) == [ticket_id]

    new_value = f"o'brien {random_string()}"
    assert (await async_rt_connection.tickets.edit(ticket_id, CustomFields={RT_CUSTOM_FIELD: new_value})).complete
    assert custom_field_values(await async_rt_connection.tickets.get(ticket_id)) == [new_value]
    assert await search('', value) == []
    assert await search('', new_value) == [ticket_id]


async def test_search_query_string():
    queries = []
    orders = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(_query(request))
        orders.append((request.url.params.get('orderby'), request.url.params.get('order')))
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    await _collect(client.tickets.search(queue="Gen'eral", conditions={'CF_My Field__like': "it's", 'Priority__gt': 5}, Subject='a\\b', CF_Foo='bar'))
    await _collect(client.tickets.search(queue='General', raw_query="Status = 'open'", order='Created'))
    await _collect(client.tickets.search(queue='General', order='-id'))
    await _collect(client.tickets.new_correspondence(queue='General'))

    assert queries == [
        "(Queue='Gen\\'eral') AND ('CF.{My Field}' LIKE 'it\\'s') AND (Priority>'5') AND (Subject='a\\\\b') AND ('CF.{Foo}'='bar')",
        "(Queue='General') AND (Status = 'open')",
        "(Queue='General')",
        # RT replaces __CurrentUser__ with the user who executes the search
        "(Queue='General') AND (LastUpdatedBy!='__CurrentUser__')",
    ]
    assert orders == [(None, None), ('Created', 'ASC'), ('id', 'DESC'), ('LastUpdated', 'DESC')]

    # a condition must not be given twice, the values could differ
    with pytest.raises(rt.exceptions.InvalidUseError, match='Status'):
        await _collect(client.tickets.search(conditions={'Status': 'open', 'Subject': 'x'}, Status='new'))
    assert len(queries) == 4


async def test_search_operators(async_rt_connection: AsyncRt):
    tag = random_string()
    low = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=f'alpha-{tag}-op', content='Test', Priority=10)
    high = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=f'beta-{tag}-op', content='Test', Priority=50)

    async def search(**kwargs: typing.Any) -> list[int]:
        return sorted([int(ticket['id']) async for ticket in async_rt_connection.tickets.search(queue=RT_QUEUE, Subject__like=tag, **kwargs)])

    assert await search(Priority__gte=50) == [high]
    assert await search(Priority__lte=10) == [low]
    assert await search(Priority__gt=10) == [high]
    assert await search(Priority__lt=50) == [low]
    assert await search(Subject__startswith=f'alpha-{tag}') == [low]
    assert await search(Subject__notstartswith=f'alpha-{tag}') == [high]
    assert await search(Subject__endswith='-op') == [low, high]
    assert await search(Subject__notendswith='-op') == []
    assert await search(Resolved__is=None) == [low, high]
    assert await search(Resolved__is='NULL') == [low, high]
    assert await search(Resolved__isnot=None) == []
    assert await search(Subject__exact=f'beta-{tag}-op') == [high]
    assert await search(Subject__notexact=f'beta-{tag}-op') == [low]
    # conditions given as mapping are combined with the keyword arguments
    assert await search(conditions={'Priority__gt': 10, 'Subject__endswith': '-op'}) == [high]


async def test_search_unsupported_operator():
    client = _mock_client(_no_request)

    # previously an unknown operator silently became "="
    with pytest.raises(rt.exceptions.InvalidUseError, match='likee'):
        await _collect(client.tickets.search(Subject__likee='x'))
    with pytest.raises(rt.exceptions.InvalidUseError, match='None'):
        await _collect(client.tickets.search(Resolved__is='2024-01-01'))


async def test_search_operator_query_string():
    queries = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(_query(request))
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    await _collect(client.tickets.search(Priority__gte=5, Subject__notstartswith="a'b", Resolved__isnot=None, CF_my__field__exact='x'))

    assert queries == ["(Priority>='5') AND (Subject NOT STARTSWITH 'a\\'b') AND (Resolved IS NOT NULL) AND ('CF.{my__field}'='x')"]


async def test_search_parameters_in_url():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _page(1, [], pages=0)

    await _collect(_mock_client(handler).tickets.search(queue='General', order='-Created', fields=['Subject']))

    # only the query is sent in the body, the other parameters are sent in the URL as before
    (request,) = requests
    assert _query(request) == "(Queue='General')"
    assert dict(request.url.params) == {'orderby': 'Created', 'order': 'DESC', 'fields': 'Subject', 'page': '1', 'per_page': '100'}
    assert request.headers['Content-Type'] == 'application/x-www-form-urlencoded'


async def test_search_non_ascii(async_rt_connection: AsyncRt):
    subject = f'Grüße ✓ {random_string()}'
    ticket_id = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=subject, content='Test')

    found = [(int(ticket['id']), ticket['Subject']) async for ticket in async_rt_connection.tickets.search(queue=RT_QUEUE, Subject=subject)]

    assert found == [(ticket_id, subject)]


async def test_search_long_query(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject='Long query', content='Test')
    # a query of about 40 KB, which is longer than many web servers and proxies accept in a URL
    raw_query = ' OR '.join(f"id = '{ticket_id + offset}'" for offset in range(3000))

    found = [int(ticket['id']) async for ticket in async_rt_connection.tickets.search(raw_query=raw_query, fields='i')]

    assert ticket_id in found


# --- URL paths ---------------------------------------------------------------------------------------------------


async def test_names_can_not_change_the_endpoint(async_rt_connection: AsyncRt):
    # previously this returned ticket 1 instead of looking up a user
    for user_name in ('../ticket/1', '..', '../../../Admin/'):
        with pytest.raises(rt.exceptions.NotFoundError):
            await async_rt_connection.users.get(user_name)

    queue_name = f'Queue with spaces & special chars {random_string()}'
    queue_id = await async_rt_connection.queues.create(queue_name)
    assert int((await async_rt_connection.queues.get(queue_name))['id']) == queue_id
    assert int((await async_rt_connection.queues.get(queue_id))['id']) == queue_id


# --- last updated -------------------------------------------------------------------------------------------------


async def test_last_updated_with_date_objects(async_rt_connection: AsyncRt):
    queue_name = f'LastUpdated {random_string()}'
    await async_rt_connection.queues.create(queue_name)
    ticket_id = await async_rt_connection.tickets.create(queue=queue_name, subject='Last updated test', content='Test')
    last_updated = (await async_rt_connection.tickets.get(ticket_id))['LastUpdated']
    updated = dt.datetime.strptime(last_updated, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.UTC)

    async def found(since: dt.date) -> list[int]:
        return [int(ticket['id']) async for ticket in async_rt_connection.tickets.last_updated(since, queue=queue_name)]

    assert await found(dt.date(2000, 1, 2)) == [ticket_id]
    assert await found(dt.datetime(2000, 1, 2, 12, 0, 0)) == [ticket_id]  # noqa: DTZ001  # naive datetime on purpose

    # a datetime with timezone is an exact point in time, in any timezone
    plus_two_hours = dt.timezone(dt.timedelta(hours=2))
    for timezone in (dt.UTC, plus_two_hours):
        assert await found((updated - dt.timedelta(minutes=1)).astimezone(timezone)) == [ticket_id]
        assert await found((updated + dt.timedelta(minutes=1)).astimezone(timezone)) == []

    with pytest.raises(rt.exceptions.InvalidUseError):
        async_rt_connection.tickets.last_updated(dt.date(1960, 1, 1))


async def test_last_updated_date_formats():
    queries = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(_query(request))
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    plus_two_hours = dt.timezone(dt.timedelta(hours=2))
    for since in (
        '2024-01-02',
        dt.date(2024, 1, 2),
        dt.datetime(2024, 1, 2, 10, 11, 12),  # noqa: DTZ001  # naive datetime on purpose
        dt.datetime(2024, 1, 2, 10, 11, 12, tzinfo=plus_two_hours),
    ):
        await _collect(client.tickets.last_updated(since))

    assert queries == [
        "(LastUpdated>'2024-01-02')",
        "(LastUpdated>'2024-01-02')",
        "(LastUpdated>'2024-01-02 10:11:12')",
        "(LastUpdated>'2024-01-02T08:11:12Z')",
    ]


async def test_last_updated_validates_date_immediately(async_rt_connection: AsyncRt):
    # the date is validated when calling the method, not when iterating over the results
    for invalid_date in ('foo', '2024-02-30', '24-01-01', '1970-01-01', '2100-01-01'):
        with pytest.raises(rt.exceptions.InvalidUseError):
            async_rt_connection.tickets.last_updated(invalid_date)

    # use a new queue, so only the ticket created here is returned (and not all tickets ever created)
    queue_name = f'LastUpdated {random_string()}'
    await async_rt_connection.queues.create(queue_name)
    ticket_id = await async_rt_connection.tickets.create(queue=queue_name, subject='Last updated test', content='Test')

    # no await needed, like for all other methods returning multiple results
    assert [int(ticket['id']) async for ticket in async_rt_connection.tickets.last_updated('2000-01-02', queue=queue_name)] == [ticket_id]
    assert [int(ticket['id']) async for ticket in async_rt_connection.tickets.last_updated('2000-01-02 12:00:00', queue=queue_name)] == [ticket_id]
    # the ticket was last updated by the user of the connection, so it is no new correspondence
    assert [int(ticket['id']) async for ticket in async_rt_connection.tickets.new_correspondence(queue=queue_name)] == []


# --- content types and link names --------------------------------------------------------------------------------


async def test_invalid_content_type():
    client = _mock_client(_no_request)

    for invalid_content_type in ('text/markdown', 'TEXT/PLAIN', ''):
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.tickets.reply(1, 'Test', content_type=invalid_content_type)  # type: ignore[arg-type]
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.tickets.comment(1, 'Test', content_type=invalid_content_type)  # type: ignore[arg-type]
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.tickets.create(RT_QUEUE, content='Test', content_type=invalid_content_type)  # type: ignore[arg-type]


async def test_valid_content_types_are_sent():
    content_types = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        content_types.append(json.loads(request.content)['ContentType'])
        return httpx2.Response(200, json=['Message recorded'])

    client = _mock_client(handler)
    assert await client.tickets.reply(1, 'Test', content_type='text/html')
    assert await client.tickets.comment(1, 'Test')

    assert content_types == ['text/html', 'text/plain']


async def test_invalid_link_name():
    with no_type_checks(), pytest.raises(rt.exceptions.InvalidUseError, match='Parent, Child, RefersTo, ReferredToBy, DependsOn, DependedOnBy'):
        await _mock_client(_no_request).tickets.edit_link(1, 'MemberOf', 2)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ('delete', 'message', 'expected'),
    [
        (False, "Link could not be created: Can't link a ticket to itself", rt.exceptions.InvalidUseError),
        (True, 'Link could not be deleted: Permission Denied', rt.exceptions.NotAllowedError),
        (False, 'Permission Denied', rt.exceptions.NotAllowedError),
        (False, 'Permission denied', rt.exceptions.NotAllowedError),
        (True, 'Permission denied', rt.exceptions.NotAllowedError),
        (False, 'Refused to add link which would create a circular relationship', rt.exceptions.InvalidUseError),
    ],
)
async def test_edit_link_failed(delete: bool, message: str, expected: type[rt.exceptions.RtError]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[message])

    with pytest.raises(expected, match=message):
        await _mock_client(handler).tickets.edit_link(1, 'DependsOn', 2, delete=delete)


# --- order, fields and search_params of listing methods ---------------------------------------------------------

_LISTING_METHODS = [
    ('tickets', 'search', ()),
    ('tickets', 'new_correspondence', ()),
    ('tickets', 'last_updated', ('2024-01-01',)),
    ('tickets', 'search_transactions', ()),
    ('tickets', 'history', (1,)),
    ('tickets', 'get_attachments', (1,)),
    ('tickets', 'get_attachments_ids', (1,)),
    ('tickets', 'search_attachments', ()),
    ('users', 'search', ()),
    ('users', 'get_groups', ('root',)),
    ('groups', 'search', ()),
    ('groups', 'get_members', (1,)),
    ('queues', 'all', ()),
    ('queues', 'search', ()),
    ('assets', 'search', ()),
    ('assets', 'history', (1,)),
    ('catalogs', 'all', ()),
    ('catalogs', 'search', ()),
    ('articles', 'search', ()),
    ('articles', 'history', (1,)),
    ('classes', 'all', ()),
    ('classes', 'search', ()),
    ('custom_fields', 'search', ()),
    ('custom_fields', 'get_values', (1,)),
    ('custom_roles', 'search', ()),
]


def _custom_field_lookup(request: httpx2.Request) -> list | None:
    """Return the conditions if the request is the lookup of a custom field of conditions, else None."""
    if request.url.path != '/REST/2.0/customfields' or request.url.params.get('per_page') != '1':
        return None
    conditions = json.loads(request.content)
    return conditions if any(condition['field'] == 'LookupType' for condition in conditions) else None


def _listing_handler(requests: list[httpx2.Request], custom_fields: frozenset[str] = frozenset()) -> typing.Callable[[httpx2.Request], httpx2.Response]:
    """Handler answering listings with an empty page; custom fields of conditions exist if their name is in *custom_fields*."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == '/REST/2.0/ticket/1':
            # the check of the ticket before its attachments are searched
            return httpx2.Response(200, json={'id': 1})
        lookup = _custom_field_lookup(request)
        if lookup is not None:
            name = lookup[0]['value']
            return _page(1, [{'id': 7, 'Name': name}] if name in custom_fields else [], pages=1 if name in custom_fields else 0)
        requests.append(request)
        return _page(1, [], pages=0)

    return handler


@pytest.mark.parametrize(('area', 'method', 'args'), _LISTING_METHODS)
async def test_listing_order(area: str, method: str, args: tuple):
    requests: list[httpx2.Request] = []
    client = _mock_client(_listing_handler(requests))
    kwargs = {'search_params': [{'field': 'Type', 'value': 'Comment'}]} if method == 'search_transactions' else {}

    await _collect(getattr(getattr(client, area), method)(*args, order=['Status', '-Created'], **kwargs))

    (request,) = requests
    # RT pairs each orderby with the order at the same position
    assert request.url.params.get_list('orderby') == ['Status', 'Created']
    assert request.url.params.get_list('order') == ['ASC', 'DESC']

    with pytest.raises(rt.exceptions.InvalidUseError):
        await _collect(getattr(getattr(client, area), method)(*args, order='-', **kwargs))


@pytest.mark.parametrize(
    ('area', 'method', 'args', 'default_fields'),
    [
        ('tickets', 'history', (1,), _HISTORY_FIELDS),
        ('assets', 'history', (1,), _HISTORY_FIELDS),
        ('articles', 'history', (1,), _HISTORY_FIELDS),
        ('queues', 'all', (), 'Name,Description,CorrespondAddress,CommentAddress,InitialPriority,FinalPriority,DefaultDueIn'),
        ('catalogs', 'all', (), 'Name,Description,Lifecycle,Disabled'),
        ('classes', 'all', (), 'Name,Description,Disabled'),
    ],
)
async def test_listing_fields(area: str, method: str, args: tuple, default_fields: str):
    requests: list[httpx2.Request] = []
    client = _mock_client(_listing_handler(requests))
    listing = getattr(getattr(client, area), method)

    await _collect(listing(*args))
    await _collect(listing(*args, fields=['Type', 'Created']))
    await _collect(listing(*args, fields={'fields[Creator]': 'Name'}))

    assert [request.url.params['fields'] for request in requests] == [default_fields, 'Type,Created', default_fields]
    assert requests[2].url.params['fields[Creator]'] == 'Name'
    # without conditions, the listing is requested with GET as before
    assert {request.method for request in requests} == {'GET'}


@pytest.mark.parametrize(('area', 'args'), [('tickets', (1,)), ('assets', (1,)), ('articles', (1,))])
async def test_history_search_params(area: str, args: tuple):
    requests: list[httpx2.Request] = []
    client = _mock_client(_listing_handler(requests))
    conditions = [{'field': 'Type', 'value': 'Status'}]

    await _collect(getattr(client, area).history(*args, search_params=conditions))

    (request,) = requests
    assert request.method == 'POST'
    assert json.loads(request.content) == conditions
    # the history keeps the fields and the creator details
    assert request.url.params['fields'] == _HISTORY_FIELDS
    assert request.url.params['fields[Creator]'] == 'id,Name,RealName,EmailAddress'


@pytest.mark.parametrize(
    ('area', 'method', 'args', 'known'),
    [
        ('tickets', 'create', ('General',), 'Subject'),
        ('tickets', 'edit', (1,), 'Subject'),
        ('assets', 'create', ('Laptop', 1), 'Description'),
        ('assets', 'edit', (1,), 'Description'),
        ('catalogs', 'create', ('Hardware',), 'Description'),
        ('catalogs', 'edit', (1,), 'Description'),
        ('groups', 'create', ('Staff',), 'Description'),
        ('groups', 'edit', (1,), 'Description'),
        ('articles', 'create', ('VPN', 1), 'Summary'),
        ('articles', 'edit', (1,), 'Summary'),
        ('classes', 'create', ('FAQ',), 'Description'),
        ('classes', 'edit', (1,), 'Description'),
        ('custom_fields', 'create', ('Severity', 'Select', 'RT::Queue-RT::Ticket'), 'Description'),
        ('custom_fields', 'edit', (1,), 'Description'),
        ('custom_fields', 'add_value', (1, 'High'), 'Description'),
        ('custom_fields', 'edit_value', (1, 2), 'Description'),
    ],
)
async def test_unknown_fields_are_sent_with_warning(area: str, method: str, args: tuple, known: str, caplog: pytest.LogCaptureFixture):
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == 'POST':
            return httpx2.Response(201, json={'id': 1, 'type': 'x', '_url': f'{RT_URL}x/1'})
        return httpx2.Response(200, json=[])

    client = _mock_client(handler)
    with caplog.at_level(logging.WARNING, logger=AsyncRt.__module__):
        await getattr(getattr(client, area), method)(*args, **{known: 'known'}, Descripton='typo')

    # RT ignores unknown fields, newer versions of RT may know them: sent as they are, with a warning for the typo only
    (request,) = requests
    assert json.loads(request.content)['Descripton'] == 'typo'
    (record,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert f'{area}.{method}' in record.getMessage()
    assert record.getMessage().endswith(': Descripton')


@pytest.mark.parametrize(
    ('area', 'method', 'args'),
    [
        ('users', 'search', ()),
        ('groups', 'search', ()),
        ('queues', 'search', ()),
        ('assets', 'search', ()),
        ('catalogs', 'search', ()),
        ('articles', 'search', ()),
        ('classes', 'search', ()),
        ('custom_fields', 'search', ()),
        ('custom_roles', 'search', ()),
        ('custom_fields', 'get_values', (1,)),
        ('tickets', 'search_transactions', ()),
        ('tickets', 'history', (1,)),
        ('assets', 'history', (1,)),
        ('articles', 'history', (1,)),
        ('tickets', 'get_attachments', (1,)),
        ('tickets', 'get_attachments_ids', (1,)),
        ('tickets', 'search_attachments', ()),
    ],
)
async def test_unknown_condition_fields_are_sent_with_warning(area: str, method: str, args: tuple, caplog: pytest.LogCaptureFixture):
    requests: list[httpx2.Request] = []
    client = _mock_client(_listing_handler(requests, custom_fields=frozenset({'Severity'})))
    conditions = [{'field': 'id', 'operator': '>', 'value': 0}, {'field': 'Nmae', 'value': 'x'}, {'field': 'CF.{Severity}', 'value': 'High'}]

    with caplog.at_level(logging.WARNING, logger=AsyncRt.__module__):
        await _collect(getattr(getattr(client, area), method)(*args, search_params=conditions))

    # RT ignores conditions on fields it can not search: sent as they are, with a warning for the unknown field only
    (request,) = requests
    assert {'field': 'Nmae', 'value': 'x'} in json.loads(request.content)
    (record,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert f'{area}.{method}' in record.getMessage()
    assert record.getMessage().endswith(': Nmae')


async def test_unknown_custom_field_of_conditions_is_sent_with_warning(caplog: pytest.LogCaptureFixture):
    lookups: list[httpx2.Request] = []
    requests: list[httpx2.Request] = []
    handler = _listing_handler(requests, custom_fields=frozenset({'Severity', '12'}))

    def recording_handler(request: httpx2.Request) -> httpx2.Response:
        if _custom_field_lookup(request) is not None:
            lookups.append(request)
        return handler(request)

    client = _mock_client(recording_handler)
    conditions = [
        {'field': 'CF.{Severity}', 'value': 'High'},
        {'field': 'CustomField.{Severity}', 'value': 'Low'},
        {'field': 'CF.{Sevrity}', 'value': 'High'},
        {'field': 'CF.{12}', 'value': 'x'},
    ]

    with caplog.at_level(logging.WARNING, logger=AsyncRt.__module__):
        await _collect(client.users.search(search_params=conditions))

    # RT ignores conditions on custom fields it can not load: sent as they are, with a warning for the missing one
    (request,) = requests
    assert json.loads(request.content) == conditions
    (record,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert 'users.search' in record.getMessage()
    assert record.getMessage().endswith(': Sevrity')
    # each custom field is looked up once, like RT does it: by name or ID, of the lookup type of the searched objects
    assert [json.loads(lookup.content) for lookup in lookups] == [
        [{'field': 'Name', 'value': 'Severity'}, {'field': 'LookupType', 'value': 'RT::User'}],
        [{'field': 'Name', 'value': 'Sevrity'}, {'field': 'LookupType', 'value': 'RT::User'}],
        [{'field': 'id', 'value': '12'}, {'field': 'LookupType', 'value': 'RT::User'}],
    ]
    assert {lookup.url.params['find_disabled_rows'] for lookup in lookups} == {'1'}


async def test_custom_field_of_conditions_live(async_rt_connection: AsyncRt, caplog: pytest.LogCaptureFixture):
    """RT and the library agree: a condition on an existing user custom field filters, one on a missing custom field is reported."""
    field_name = f'cf-{random_string()}'
    field_id = await async_rt_connection.custom_fields.create(field_name, 'Freeform', 'RT::User')
    await async_rt_connection.custom_fields.apply(field_id, 0)
    user_name = f'user-{random_string()}'
    await async_rt_connection.users.create(user_name, f'{user_name}@example.com', CustomFields={field_name: 'marker'})

    with caplog.at_level(logging.WARNING, logger=AsyncRt.__module__):
        found = [item['id'] async for item in async_rt_connection.users.search(search_params=[{'field': f'CF.{{{field_name}}}', 'value': 'marker'}])]
    assert found == [user_name]
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]

    with caplog.at_level(logging.WARNING, logger=AsyncRt.__module__):
        searched = async_rt_connection.users.search(search_params=[{'field': f'CF.{{{field_name}-typo}}', 'value': 'marker'}])
        assert await searched.__anext__()  # RT ignores the condition and returns users
    assert f'{field_name}-typo' in caplog.text


async def test_listing_order_fields_and_conditions(async_rt_connection: AsyncRt):
    """RT sorts, selects fields and filters the listings as requested (only objects of this test are compared)."""
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject=f'Listing {random_string()}', content='Test')
    for number in range(3):
        await async_rt_connection.tickets.comment(ticket_id, f'Comment {number}')

    ascending = [int(item['id']) async for item in async_rt_connection.tickets.history(ticket_id)]
    descending = [int(item['id']) async for item in async_rt_connection.tickets.history(ticket_id, order='-id')]
    assert len(ascending) >= 4
    assert ascending == sorted(ascending)
    assert descending == ascending[::-1]

    comments = [item async for item in async_rt_connection.tickets.history(ticket_id, search_params=[{'field': 'Type', 'value': 'Comment'}], fields=['Type'])]
    assert [item['Type'] for item in comments] == ['Comment'] * 3
    assert 'Creator' not in comments[0]

    field_id = await async_rt_connection.custom_fields.create(f'cf-{random_string()}', 'Select', 'RT::Queue-RT::Ticket')
    for name in ('b', 'c', 'a'):
        await async_rt_connection.custom_fields.add_value(field_id, name)
    assert [item['name'] async for item in async_rt_connection.custom_fields.get_values(field_id, order='-Name')] == ['c', 'b', 'a']

    user_name = f'user-{random_string()}'
    await async_rt_connection.users.create(user_name, f'{user_name}@example.com')
    group_ids = [await async_rt_connection.groups.create(f'group-{random_string()}') for _ in range(3)]
    for group_id in group_ids:
        await async_rt_connection.users.add_to_group(user_name, group_id)
    assert [int(item['id']) async for item in async_rt_connection.users.get_groups(user_name, order='-id')] == sorted(group_ids, reverse=True)

    prefix = f'listing-{random_string()}'
    class_ids = [await async_rt_connection.classes.create(f'{prefix}-{number}') for number in range(3)]
    found = [int(item['id']) async for item in async_rt_connection.classes.all(order='-Name', fields=['Name']) if str(item.get('Name', '')).startswith(prefix)]
    assert found == class_ids[::-1]
    searched = async_rt_connection.classes.search(search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': prefix}], order='-id')
    assert [int(item['id']) async for item in searched] == class_ids[::-1]


# --- fields of linked objects in get() ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('area', 'method', 'args', 'path'),
    [
        ('catalogs', 'get', (1,), '/catalog/1'),
        ('groups', 'get', (5,), '/group/5'),
        ('custom_fields', 'get', (2,), '/customfield/2'),
        ('custom_fields', 'get_value', (2, 3), '/customfield/2/value/3'),
        ('custom_roles', 'get', (1,), '/customrole/1'),
        ('articles', 'get', (1,), '/article/1'),
        ('classes', 'get', (1,), '/class/1'),
        ('queues', 'get', ('General',), '/queue/General'),
        ('users', 'get', ('root',), '/user/root'),
        ('tickets', 'get_transaction', (7,), '/transaction/7'),
        ('tickets', 'get_attachment', (8,), '/attachment/8'),
    ],
)
async def test_get_fields_of_linked_objects(area: str, method: str, args: tuple, path: str):
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={'id': 1})

    client = _mock_client(handler)
    await getattr(getattr(client, area), method)(*args)
    await getattr(getattr(client, area), method)(*args, fields={'fields[Creator]': 'Name,EmailAddress'})

    assert [request.url.path for request in requests] == [f'/REST/2.0{path}'] * 2
    assert dict(requests[0].url.params) == {}
    assert dict(requests[1].url.params) == {'fields[Creator]': 'Name,EmailAddress'}


# --- error messages of edit operations --------------------------------------------------------------------------


async def test_edit_ticket_refused_field_changes_other_fields(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=f'Refused field {random_string()}', content='Test')
    new_subject = f'Changed {random_string()}'

    # RT answers HTTP 200 and reports the refused status only in a message, but still changes the other fields
    result = await async_rt_connection.tickets.edit(ticket_id, Subject=new_subject, Status='invalid')
    assert result
    assert not result.complete
    assert len(result.refused) == 1
    assert "isn't a valid status" in result.refused[0]
    assert any('Subject changed' in message for message in result.messages)
    with pytest.raises(rt.exceptions.InvalidUseError, match="isn't a valid status"):
        result.raise_for_refused()

    ticket = await async_rt_connection.tickets.get(ticket_id)
    assert ticket['Subject'] == new_subject
    assert ticket['Status'] == 'new'

    # the most specific error is raised if several fields were refused
    result = await async_rt_connection.tickets.edit(ticket_id, Status='invalid', Owner=f'nosuchuser{random_string()}')
    with pytest.raises(rt.exceptions.NotFoundError, match=r'(?s)(?=.*valid status)(?=.*does not exist)'):
        result.raise_for_refused()

    # unknown fields and unknown custom fields are ignored by RT without any message
    result = await async_rt_connection.tickets.edit(ticket_id, Unknown='x', CustomFields={'Unknown': 'x'})
    assert result.complete
    assert result.messages == ()


# --- pagination -----------------------------------------------------------------------------------------------


async def test_search_multiple_pages(async_rt_connection: AsyncRt):
    subject = f'Paging test {random_string()}'
    ticket_ids = sorted([await async_rt_connection.tickets.create(queue=RT_QUEUE, subject=subject, content='Test') for _ in range(5)])

    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), per_page=2) as tracker:
        found = [int(ticket['id']) async for ticket in tracker.tickets.search(queue=RT_QUEUE, Subject=subject)]

    assert sorted(found) == ticket_ids


async def test_per_page_is_requested():
    requested = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requested.append(request.url.params['per_page'])
        return _page(1, [], pages=0)

    await _collect(_mock_client(handler).tickets.search())
    client = AsyncRt(url=RT_URL, per_page=25, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    await _collect(client.tickets.search())

    assert requested == ['100', '25']


@pytest.mark.parametrize('per_page', [0, -1, 101])
async def test_invalid_per_page(per_page: int):
    with pytest.raises(ValueError, match='per_page'):
        AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), per_page=per_page)


async def test_init_parameters_are_keyword_only():
    with pytest.raises(TypeError):
        AsyncRt(RT_URL)  # type: ignore[call-arg]


async def test_paging_with_unknown_page_count():
    """RT >= 5.0.5 does not return the number of pages for users who are not allowed to see all results."""
    responses = {
        1: _page(1, [{'id': '1'}, {'id': '2'}], pages=None, next_page=True),
        2: _page(2, [], pages=None, next_page=True),  # all items of this page are hidden from the user
        3: _page(3, [{'id': '3'}], pages=None),
        4: _page(4, [], pages=None),
    }
    requested_pages = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params['page'])
        requested_pages.append(page)
        return responses[page]

    assert [ticket['id'] async for ticket in _mock_client(handler).tickets.search()] == ['1', '2', '3']
    assert requested_pages == [1, 2, 3, 4]


async def test_paging_with_unknown_page_count_and_no_results():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _page(1, [], pages=None)

    # previously a NotFoundError was raised
    assert await _collect(_mock_client(handler).tickets.search()) == []


async def test_paging_stops_if_rt_returns_last_page_again():
    """RT returns the last page again if a page after the last one is requested, e.g. after items were deleted."""

    requested_pages = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params['page'])
        requested_pages.append(page)
        if page == 1:
            return _page(1, [{'id': '1'}], pages=3, per_page=1)
        # page 3 vanished after page 2 was requested, so RT returns page 2 again for page 3
        return _page(2, [{'id': '2'}], pages=3 if page == 2 else 2, per_page=1)

    assert [ticket['id'] async for ticket in _mock_client(handler).tickets.search()] == ['1', '2']
    assert requested_pages == [1, 2, 3]


async def test_paging_unexpected_result():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={'id': '1'})

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await _collect(_mock_client(handler).tickets.search())


async def test_search_assets_does_not_modify_search_params(async_rt_connection: AsyncRt):
    search_params = [{'field': 'Name', 'value': f'nonexistent {random_string()}'}]
    expected = [dict(param) for param in search_params]

    assert await _collect(async_rt_connection.assets.search(search_params=search_params)) == []
    assert await _collect(async_rt_connection.assets.search(catalog_id=1, search_params=search_params)) == []

    assert search_params == expected


# --- responses which are not as expected ------------------------------------------------------------------------


async def test_invalid_json_response():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text='<html>Login</html>', headers={'Content-Type': 'text/html'})

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError) as exc_info:
        await client.tickets.get(1)
    assert exc_info.value.status_code == 200
    assert exc_info.value.response_message == '<html>Login</html>'

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.tickets.edit(1, Subject='x')
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await _collect(client.tickets.search())
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.tickets.delete(1)


async def test_delete_response_handling():
    responses: list[httpx2.Response] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses.pop(0)

    client = _mock_client(handler)

    responses.append(httpx2.Response(204))
    await client.tickets.delete(1)

    responses.append(httpx2.Response(200, json=['Ticket deleted']))
    await client.users.delete('user')

    responses.append(httpx2.Response(200, text='<html>Login</html>'))
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.queues.delete('queue')


async def test_unexpected_response_type():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == 'GET':
            return httpx2.Response(200, json=['not', 'a', 'dict'])
        return httpx2.Response(200, json={'not': 'a list'})

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.users.get('root')
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.tickets.take(1)


async def test_response_content_validation():
    responses = {
        'PUT': httpx2.Response(200, json=['Owner changed', 5]),  # status messages must be strings
        'POST': httpx2.Response(201, json={'type': 'ticket'}),  # created object without ID
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses[request.method]

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.tickets.take(1)
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.tickets.create(RT_QUEUE, subject='x')


@pytest.mark.parametrize(
    'result',
    [
        {'page': 1, 'per_page': 100, 'pages': 1, 'items': ['not a dict']},
        {'page': 1, 'per_page': 100, 'pages': '1', 'items': []},
        {'page': 1, 'per_page': 100, 'pages': 1, 'items': [{'type': 'attachment'}]},  # attachment without ID
    ],
)
async def test_paging_content_validation(result: dict):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=result)

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await _collect(_mock_client(handler).tickets.get_attachments_ids(1))


async def test_created_ids_are_returned(async_rt_connection: AsyncRt):
    user_name = f'user_{random_string()}'

    assert await async_rt_connection.users.create(user_name, f'{user_name}@example.com') == user_name
    assert isinstance(await async_rt_connection.queues.create(f'Queue {random_string()}'), int)
    assert isinstance(await async_rt_connection.tickets.create(RT_QUEUE, subject='Created ID test'), int)


async def test_bad_request_messages():
    responses = [
        httpx2.Response(400, json={'message': 'Invalid value'}),
        httpx2.Response(400, json={'unexpected': 'format'}),
        httpx2.Response(400, text='<html>Bad request</html>'),
        httpx2.Response(400, json=['Invalid', 'values']),
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses.pop(0)

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.BadRequestError, match='Invalid value'):
        await client.tickets.get(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='unexpected'):
        await client.tickets.get(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='Bad request'):
        await client.tickets.get(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='Invalid'):
        await client.tickets.get(1)


@pytest.mark.parametrize(
    ('response', 'expected'),
    [
        (httpx2.Response(401), rt.exceptions.AuthorizationError),
        (httpx2.Response(403, json={'message': 'Forbidden'}), rt.exceptions.NotAllowedError),
        (httpx2.Response(404), rt.exceptions.NotFoundError),
        (httpx2.Response(500, text='Internal Server Error'), rt.exceptions.UnexpectedResponseError),
        (httpx2.Response(302, headers={'Location': 'http://localhost/login'}), rt.exceptions.UnexpectedResponseError),
        (httpx2.ReadTimeout('timed out'), rt.exceptions.RtConnectionError),
    ],
)
async def test_error_responses(response: httpx2.Response | httpx2.TransportError, expected: type[rt.exceptions.RtError]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(response, Exception):
            raise response
        return response

    with pytest.raises(expected) as exc_info:
        await _mock_client(handler).tickets.get(1)

    if isinstance(response, httpx2.Response):
        # errors caused by a response of RT carry its status code and body
        assert exc_info.value.status_code == response.status_code
        assert exc_info.value.response_message == response.text
    else:
        assert isinstance(exc_info.value, rt.exceptions.RtConnectionError)
        assert exc_info.value.cause is response
        assert exc_info.value.status_code is None


async def test_forbidden_message():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, json={'message': "No permission to create tickets in the queue 'General'"})

    with pytest.raises(rt.exceptions.NotAllowedError, match='No permission to create tickets') as exc_info:
        await _mock_client(handler).tickets.create(RT_QUEUE, subject='x')
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('That user already owns that ticket', rt.exceptions.InvalidUseError),
        ('You can only steal a ticket owned by someone else', rt.exceptions.InvalidUseError),
        ('Permission Denied', rt.exceptions.NotAllowedError),
    ],
)
async def test_owner_change_refused(message: str, expected: type[Exception]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[message])

    with pytest.raises(expected, match=message):
        await _mock_client(handler).tickets.take(1)


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ("New ticket doesn't exist", rt.exceptions.NotFoundError),
        ("Can't merge a ticket into itself", rt.exceptions.InvalidUseError),
        ('Only tickets can be merged', rt.exceptions.InvalidUseError),
        ('Permission Denied', rt.exceptions.NotAllowedError),
    ],
)
async def test_merge_refused(message: str, expected: type[Exception]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[message])

    with pytest.raises(expected, match=message):
        await _mock_client(handler).tickets.merge(1, 2)


UNRECOGNIZED_MESSAGES = ['Ein neuer Text von RT', 'Besitzer geändert von Nobody zu root', 'Something RT has not said before']


@pytest.mark.parametrize('message', UNRECOGNIZED_MESSAGES)
async def test_unrecognized_message_is_no_error_for_changes_made_partly(message: str):
    """RT answers with HTTP status 200 also for refusals, so a message which is not known does not raise for edits, replies, ..."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(201 if request.method == 'POST' else 200, json=[message])

    client = _mock_client(handler)

    for action in (
        lambda: client.tickets.edit(1, Subject='x'),
        lambda: client.users.edit('root', RealName='x'),
        lambda: client.tickets.reply(1, 'x'),
        lambda: client.tickets.comment(1, 'x'),
    ):
        result = await action()

        assert result
        assert result.complete
        assert result.refused == ()
        assert result.unrecognized == (message,)
        result.raise_for_refused()


@pytest.mark.parametrize('message', UNRECOGNIZED_MESSAGES)
async def test_unrecognized_message_fails_actions(message: str):
    """The message is the only information about the result of an action: if it is not known, the action may not have been made."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[message])

    client = _mock_client(handler)

    for action in (
        lambda: client.tickets.take(1),
        lambda: client.tickets.untake(1),
        lambda: client.tickets.steal(1),
        lambda: client.tickets.merge(1, 2),
        lambda: client.tickets.edit_link(1, 'RefersTo', 2),
        lambda: client.assets.edit_link(1, 'RefersTo', 2),
        lambda: client.groups.add_member(1, 2),
    ):
        # not InvalidUseError: RT did not refuse the action as far as the library knows
        with pytest.raises(rt.exceptions.UnexpectedResponseError, match='not known to the library') as exc_info:
            await action()

        assert not isinstance(exc_info.value, rt.exceptions.InvalidUseError)
        assert message in str(exc_info.value)


@pytest.mark.parametrize('message', UNRECOGNIZED_MESSAGES)
async def test_unrecognized_message_is_no_error_if_rt_tells_the_result(message: str):
    """RT tells the result of adding a user to a group with a status, and of applying a custom field with the HTTP status."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith('/groups'):
            return httpx2.Response(200, json=[1, message])
        return httpx2.Response(201, json={'message': message})

    client = _mock_client(handler)

    for action in (lambda: client.users.add_to_group('root', 1), lambda: client.custom_fields.apply(1, 2)):
        result = await action()

        assert result
        assert result.unrecognized == (message,)


async def test_known_refusal_raises_for_actions_only():
    """A known refusal raises for actions, as nothing was changed, but not for edits, as parts of them were made."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=['That user does not exist'])

    client = _mock_client(handler)

    # nothing was changed by an action, parts of an edit were changed
    with pytest.raises(rt.exceptions.NotFoundError):
        await client.tickets.take(1)
    with pytest.raises(rt.exceptions.NotFoundError):
        await client.tickets.merge(1, 2)

    result = await client.tickets.edit(1, Owner='nobody')
    assert result
    assert result.refused == ('That user does not exist',)
    assert result.unrecognized == ()


async def test_unexpected_number_of_status_messages():
    messages: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=messages)

    client = _mock_client(handler)

    # RT returns no status message if nothing was changed
    result = await client.tickets.edit(1, Subject='unchanged')
    assert result
    assert result.complete
    assert result.messages == ()

    for action in (
        lambda: client.tickets.reply(1, 'x'),
        lambda: client.tickets.comment(1, 'x'),
        lambda: client.tickets.merge(1, 2),
        lambda: client.tickets.steal(1),
    ):
        with pytest.raises(rt.exceptions.UnexpectedResponseError):
            await action()

    messages.extend(['Merge Successful', 'Owner changed from Nobody to root'])
    for action in (lambda: client.tickets.merge(1, 2), lambda: client.tickets.take(1)):
        with pytest.raises(rt.exceptions.UnexpectedResponseError):
            await action()


# --- connection handling ---------------------------------------------------------------------------------------


async def test_context_manager():
    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD)) as tracker:
        assert (await tracker.users.get(RT_USER))['Name'] == RT_USER

    assert tracker.session.is_closed


async def test_close():
    tracker = AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD))
    assert await tracker.users.exists(RT_USER, privileged=True)

    await tracker.aclose()

    assert tracker.session.is_closed


async def test_token_and_http_auth_are_exclusive():
    with pytest.raises(ValueError, match='either'):
        AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), token='secret')


@requires_rt_setup
async def test_token_authentication(caplog: pytest.LogCaptureFixture):
    async with AsyncRt(url=RT_URL, token=RT_TOKEN) as tracker:
        with caplog.at_level(logging.DEBUG, logger=AsyncRt.__module__):
            assert (await tracker.users.get(RT_USER))['Name'] == RT_USER
            assert await _collect(tracker.tickets.search(queue=RT_QUEUE, id=0)) == []

    assert RT_TOKEN not in caplog.text
    assert '[redacted]' in caplog.text

    # an unknown token of the same form is rejected
    owner, _, _ = RT_TOKEN.rpartition('-')
    async with AsyncRt(url=RT_URL, token=f'{owner}-{"0" * 32}') as tracker:
        with pytest.raises(rt.exceptions.AuthorizationError) as exc_info:
            await tracker.users.get(RT_USER)
    assert exc_info.value.status_code == 401


async def test_connection_error():
    tracker = AsyncRt(url=UNREACHABLE_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD))

    with pytest.raises(rt.exceptions.RtConnectionError) as exc_info:
        await tracker.users.get(RT_USER)

    # can be caught as builtin ConnectionError (as before) as well as RtError
    assert isinstance(exc_info.value, builtins.ConnectionError)
    assert isinstance(exc_info.value, rt.exceptions.RtError)
    assert isinstance(exc_info.value.cause, httpx2.ConnectError)

    with pytest.raises(rt.exceptions.RtConnectionError):
        await _collect(tracker.tickets.search())


async def test_own_client():
    http_client = httpx2.AsyncClient(auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), timeout=30)

    async with AsyncRt(url=RT_URL, client=http_client) as tracker:
        assert tracker.session is http_client
        assert (await tracker.users.get(RT_USER))['Name'] == RT_USER

    # the client is owned by the caller and must not be closed
    assert not http_client.is_closed
    await tracker.aclose()
    assert not http_client.is_closed

    async with AsyncRt(url=RT_URL, client=http_client) as tracker:
        assert await tracker.users.exists(RT_USER, privileged=True)

    await http_client.aclose()


async def test_verify_cert_ca_bundle(tmp_path: pathlib.Path):
    # a path is used as CA bundle, so it must exist
    with pytest.raises(FileNotFoundError):
        AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), verify_cert=str(tmp_path / 'missing-ca.pem'))


@pytest.mark.parametrize(
    'settings',
    [
        {'proxy': 'http://proxy:3128'},
        {'verify_cert': False},
        {'verify_cert': '/path/to/ca.pem'},
        {'http_auth': httpx2.BasicAuth(RT_USER, RT_PASSWORD)},
        {'token': 'secret'},
        {'http_timeout': 60},
        {'http_timeout': None},
    ],
)
async def test_own_client_with_connection_settings(settings: dict):
    with pytest.raises(ValueError, match='client'):
        AsyncRt(url=RT_URL, client=httpx2.AsyncClient(), **settings)


# --- debug logging --------------------------------------------------------------------------------------------


async def test_debug_log_does_not_contain_credentials(caplog: pytest.LogCaptureFixture):
    tracker = AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD))
    user_password = f'Secret-{random_string()}'

    with caplog.at_level(logging.DEBUG, logger=AsyncRt.__module__):
        assert (await tracker.users.get(RT_USER))['Name'] == RT_USER
        await tracker.users.create(f'user_{random_string()}', f'{random_string()}@example.com', Password=user_password)

    encoded_credentials = base64.b64encode(f'{RT_USER}:{RT_PASSWORD}'.encode()).decode()
    assert '[redacted]' in caplog.text
    assert encoded_credentials not in caplog.text
    assert user_password not in caplog.text
    assert 'Response status code: 200' in caplog.text


async def test_no_debug_log_if_disabled(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger=AsyncRt.__module__):
        await _mock_client(lambda request: httpx2.Response(200, json={'id': 1})).tickets.get(1)

    assert caplog.text == ''


# --- users -----------------------------------------------------------------------------------------------------


async def test_user_exists(async_rt_connection: AsyncRt):
    assert await async_rt_connection.users.exists(RT_USER, privileged=True)
    assert not await async_rt_connection.users.exists(f'nosuchuser{random_string()}', privileged=True)
    assert not await async_rt_connection.users.exists(f'nosuchuser{random_string()}', privileged=False)

    unprivileged_user = f'user_{random_string()}'
    await async_rt_connection.users.create(unprivileged_user, f'{unprivileged_user}@example.com', Privileged=0)
    assert not await async_rt_connection.users.exists(unprivileged_user, privileged=True)
    assert await async_rt_connection.users.exists(unprivileged_user, privileged=False)


async def test_user_exists_privileged_is_required():
    with no_type_checks(), pytest.raises(TypeError):
        await _mock_client(_no_request).users.exists('root')  # type: ignore[call-arg]


async def test_user_exists_privileged_as_string():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=json.dumps({'id': 1, 'Privileged': '1'}))

    assert await _mock_client(handler).users.exists('root', privileged=True)


async def test_invalid_fields(async_rt_connection: AsyncRt):
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo, Bar.'):
        await async_rt_connection.users.create('user', 'user@example.com', Foo=1, Bar=2)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.users.edit(RT_USER, Foo=1)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.queues.create('queue', Foo=1)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.queues.edit(RT_QUEUE, Foo=1)


# --- review of the major release -----------------------------------------------------------------------------------


async def test_search_field_names_are_quoted():
    queries = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(_query(request))
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    # plain names are used as they are, other names are quoted, so they can not change the meaning of the query
    await _collect(client.tickets.search(conditions={'Requestor.EmailAddress__like': 'a', 'CustomRole.{Some Role}': 'b', "Subject='x') OR (id": 1}))

    assert queries == ["(Requestor.EmailAddress LIKE 'a') AND ('CustomRole.{Some Role}'='b') AND ('Subject=\\'x\\') OR (id'='1')"]


@requires_rt_setup
async def test_search_custom_role(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(
        RT_QUEUE, subject=f'Custom role {random_string()}', content='Test', CustomRoles={RT_CUSTOM_ROLE: RT_USER}
    )

    found = [
        int(ticket['id'])
        async for ticket in async_rt_connection.tickets.search(queue=RT_QUEUE, conditions={f'CustomRole.{{{RT_CUSTOM_ROLE}}}.Name': RT_USER, 'id': ticket_id})
    ]

    assert found == [ticket_id]


async def test_search_raw_query_with_conditions():
    client = _mock_client(_no_request)

    with pytest.raises(rt.exceptions.InvalidUseError, match='raw_query'):
        await _collect(client.tickets.search(raw_query="Status = 'open'", Subject='x'))
    with pytest.raises(rt.exceptions.InvalidUseError, match='raw_query'):
        await _collect(client.tickets.search(raw_query="Status = 'open'", conditions={'Subject': 'x'}))


async def test_search_assets_catalog_condition(async_rt_connection: AsyncRt):
    catalog_name = f'catalog-{random_string()}'
    catalog_id = await async_rt_connection.catalogs.create(catalog_name)
    asset_id = await async_rt_connection.assets.create(f'asset-{random_string()}', catalog_id)
    # assets in other catalogs exist, e.g. of other tests
    await async_rt_connection.assets.create(f'asset-{random_string()}', 1)

    # previously RT combined the catalog conditions with OR and returned the assets of all catalogs
    by_condition = [int(asset['id']) async for asset in async_rt_connection.assets.search(search_params=[{'field': 'Catalog', 'value': catalog_id}])]
    by_catalog_id = [int(asset['id']) async for asset in async_rt_connection.assets.search(catalog_id=catalog_id)]
    both = [int(asset['id']) async for asset in async_rt_connection.assets.search(catalog_id=1, search_params=[{'field': 'Catalog', 'value': catalog_id}])]

    assert by_condition == by_catalog_id == [asset_id]
    assert both == []
    assert len([asset async for asset in async_rt_connection.assets.search()]) > 1


async def test_get_links_external(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='External link', content='Test')
    other_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Linked ticket', content='Test')
    await async_rt_connection.tickets.edit_link(ticket_id, 'RefersTo', 'https://example.com/document')
    await async_rt_connection.tickets.edit_link(ticket_id, 'DependsOn', other_id)

    links = sorted((link['ref'], link['type'], link['_url']) for link in await async_rt_connection.tickets.get_links(ticket_id))

    assert links == [('depends-on', 'ticket', f'{RT_URL}ticket/{other_id}'), ('refers-to', 'external', 'https://example.com/document')]


async def test_edit_queue_fields(async_rt_connection: AsyncRt):
    queue_name = f'queue-{random_string()}'
    queue_id = await async_rt_connection.queues.create(queue_name, SubjectTag='tag')
    field_name = f'cf-{random_string()}'
    field_id = await async_rt_connection.custom_fields.create(field_name, 'Freeform', 'RT::Queue', MaxValues=1)
    await async_rt_connection.custom_fields.apply(field_id, queue_id)

    assert (await async_rt_connection.queues.edit(queue_id, SubjectTag='other', CustomFields={field_name: 'value'}, AdminCc=RT_USER)).complete

    queue = await async_rt_connection.queues.get(queue_id)
    assert queue['SubjectTag'] == 'other'
    assert [field['values'] for field in queue['CustomFields'] if field['name'] == field_name] == [['value']]
    assert [watcher['id'] for watcher in queue['AdminCc']] == [RT_USER]


async def test_create_ticket_queue_id(async_rt_connection: AsyncRt):
    queue_id = int((await async_rt_connection.queues.get(RT_QUEUE))['id'])

    ticket_id = await async_rt_connection.tickets.create(queue_id, subject='Queue by ID', content='Test')

    assert (await async_rt_connection.tickets.get(ticket_id))['Queue']['Name'] == RT_QUEUE


async def test_not_found_on_edit(async_rt_connection: AsyncRt):
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.users.edit(f'missing-{random_string()}', RealName='x')
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.queues.edit(999999, Description='x')


async def test_unexpected_status_message():
    client = _mock_client(lambda request: httpx2.Response(500, json={'message': 'Internal Server Error'}))

    with pytest.raises(rt.exceptions.UnexpectedResponseError, match='Received status code 500 instead of 200: Internal Server Error') as exc_info:
        await client.tickets.get(1)
    assert exc_info.value.status_code == 500

    client = _mock_client(lambda request: httpx2.Response(502, text=''))
    with pytest.raises(rt.exceptions.UnexpectedResponseError, match=r'Received status code 502 instead of 200\.$'):
        await client.tickets.get(1)


# --- check against the source of RT ------------------------------------------------------------------------------


async def test_user_fields(async_rt_connection: AsyncRt):
    user_name = f'user-{random_string()}'
    await async_rt_connection.users.create(user_name, f'{user_name}@example.com', NickName='Nick')

    assert (await async_rt_connection.users.edit(user_name, FreeformContactInfo='Room 2', Timezone='Europe/Berlin')).complete

    user = await async_rt_connection.users.get(user_name)
    assert (user['NickName'], user['FreeformContactInfo'], user['Timezone']) == ('Nick', 'Room 2', 'Europe/Berlin')
    # the names of fields of RT before 5.0, which RT ignores
    for name in ('Nickname', 'ContactInfo', 'EmailEncoding', 'ExternalAuthId'):
        with pytest.raises(rt.exceptions.InvalidUseError, match=name):
            await async_rt_connection.users.edit(user_name, **{name: 'x'})


async def test_history_fields(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='History fields', content='Test')
    await async_rt_connection.tickets.edit(ticket_id, Status='open')

    history = [item async for item in async_rt_connection.tickets.history(ticket_id)]

    # previously the history contained only the field Description, which RT returns always empty
    status = [(item['Field'], item['OldValue'], item['NewValue']) for item in history if item['Type'] == 'Status']
    assert status == [('Status', 'new', 'open')]
    assert history[0]['Type'] == 'Create'
    assert history[0]['Creator']['Name'] == RT_USER


async def test_fields_with_spaces():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    await _collect(client.queues.search(fields='Name, Description'))
    await _collect(client.queues.search(fields=['Name', ' Description ']))
    await _collect(client.tickets.search(fields=['Subject', ' Status']))

    # RT does not strip spaces around field names
    assert [request.url.params['fields'] for request in requests] == ['Name,Description', 'Name,Description', 'Subject,Status']


async def test_queue_watcher_group(async_rt_connection: AsyncRt):
    group_name = f'group-{random_string()}'
    group_id = await async_rt_connection.groups.create(group_name)
    queue_id = await async_rt_connection.queues.create(f'queue-{random_string()}')

    await async_rt_connection.queues.edit(queue_id, AdminCc=f'group:{group_name}')

    assert [int(watcher['id']) for watcher in (await async_rt_connection.queues.get(queue_id))['AdminCc']] == [group_id]


async def test_ticket_dates_are_utc(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Dates', content='Test', Due='2030-01-31 12:00:00')

    assert (await async_rt_connection.tickets.get(ticket_id))['Due'] == '2030-01-31T12:00:00Z'
