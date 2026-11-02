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

import httpx2
import pytest

import rt.exceptions
from rt.rest2_async import AsyncRt

from . import no_type_checks, random_string
from .conftest import RT_CUSTOM_FIELD, RT_PASSWORD, RT_QUEUE, RT_TOKEN, RT_URL, RT_USER, requires_rt_setup

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


def _no_request(request: httpx2.Request) -> httpx2.Response:
    """Handler for tests which must not send any request."""
    raise AssertionError('no request must be sent')


# --- search query building ---------------------------------------------------------------------------------------


async def test_search_value_with_quote_and_backslash(async_rt_connection: AsyncRt):
    subject = f"O'Brien \\ {random_string()}"
    ticket_id = await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=subject, content='Test')

    found = [int(ticket['id']) async for ticket in async_rt_connection.search(queue=RT_QUEUE, Subject=subject)]

    assert found == [ticket_id]


async def test_search_value_can_not_alter_query(async_rt_connection: AsyncRt):
    await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=f'Injection test {random_string()}', content='Test')

    # without quoting this would be: Subject='x' OR Subject LIKE '' -> all tickets
    found = await _collect(async_rt_connection.search(queue=RT_QUEUE, Subject="x' OR Subject LIKE '"))

    assert found == []


async def test_search_queue_with_quote(async_rt_connection: AsyncRt):
    assert await _collect(async_rt_connection.search(queue="Gen'eral")) == []


async def test_search_custom_field(async_rt_connection: AsyncRt):
    # previously the query was malformed and RT returned an error
    assert await _collect(async_rt_connection.search(queue=RT_QUEUE, CF_Foo='bar')) == []
    assert await _collect(async_rt_connection.search(queue=RT_QUEUE, conditions={'CF_Foo Bar': "it's", 'CF_Foo__like': 'x'})) == []


@requires_rt_setup
async def test_custom_field(async_rt_connection: AsyncRt):
    # the name of the custom field contains a quote and a space, the values a quote and a backslash
    value = f"it's \\ {random_string()}"
    ticket_id = await async_rt_connection.create_ticket(RT_QUEUE, subject='Test', content='Test', CustomFields={RT_CUSTOM_FIELD: value})
    other_id = await async_rt_connection.create_ticket(RT_QUEUE, subject='Test', content='Test')

    def custom_field_values(ticket: dict[str, typing.Any]) -> list[str]:
        return next(cf['values'] for cf in ticket['CustomFields'] if cf['name'] == RT_CUSTOM_FIELD)

    assert custom_field_values(await async_rt_connection.get_ticket(ticket_id)) == [value]
    assert custom_field_values(await async_rt_connection.get_ticket(other_id)) == []

    async def search(condition: str, search_value: object) -> list[int]:
        conditions = {f'CF_{RT_CUSTOM_FIELD}{condition}': search_value, 'id__gte': min(ticket_id, other_id)}
        return sorted([int(ticket['id']) async for ticket in async_rt_connection.search(queue=RT_QUEUE, conditions=conditions, fields='i')])

    assert await search('', value) == [ticket_id]
    assert await search('__like', value[-8:]) == [ticket_id]
    assert await search('__notexact', value) == [other_id]
    assert await search('__is', None) == [other_id]
    assert await search('__isnot', None) == [ticket_id]

    new_value = f"o'brien {random_string()}"
    assert await async_rt_connection.edit_ticket(ticket_id, CustomFields={RT_CUSTOM_FIELD: new_value}) == [f'{RT_CUSTOM_FIELD} {value} changed to {new_value}']
    assert custom_field_values(await async_rt_connection.get_ticket(ticket_id)) == [new_value]
    assert await search('', value) == []
    assert await search('', new_value) == [ticket_id]


async def test_search_query_string():
    queries = []
    orders = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(request.url.params['query'])
        orders.append((request.url.params.get('orderby'), request.url.params.get('order')))
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    await _collect(client.search(queue="Gen'eral", conditions={'CF_My Field__like': "it's", 'Priority__gt': 5}, Subject='a\\b', CF_Foo='bar'))
    await _collect(client.search(queue='General', raw_query="Status = 'open'", order='Created', conditions={'Subject': 'ignored'}))
    await _collect(client.search(queue='General', order='-id'))
    await _collect(client.new_correspondence(queue='General'))

    assert queries == [
        "(Queue='Gen\\'eral') AND ('CF.{My Field}' LIKE 'it\\'s') AND (Priority>'5') AND (Subject='a\\\\b') AND ('CF.{Foo}'='bar')",
        "(Queue='General') AND (Status = 'open')",
        "(Queue='General')",
        # RT replaces __CurrentUser__ with the user who executes the search
        "(Queue='General') AND (LastUpdatedBy!='__CurrentUser__')",
    ]
    assert orders == [(None, None), ('Created', None), ('id', 'DESC'), ('LastUpdated', 'DESC')]

    # a condition must not be given twice, the values could differ
    with pytest.raises(rt.exceptions.InvalidUseError, match='Status'):
        await _collect(client.search(conditions={'Status': 'open', 'Subject': 'x'}, Status='new'))
    assert len(queries) == 4


async def test_search_operators(async_rt_connection: AsyncRt):
    tag = random_string()
    low = await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=f'alpha-{tag}-op', content='Test', Priority=10)
    high = await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=f'beta-{tag}-op', content='Test', Priority=50)

    async def search(**kwargs: typing.Any) -> list[int]:
        return sorted([int(ticket['id']) async for ticket in async_rt_connection.search(queue=RT_QUEUE, Subject__like=tag, **kwargs)])

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
        await _collect(client.search(Subject__likee='x'))
    with pytest.raises(rt.exceptions.InvalidUseError, match='None'):
        await _collect(client.search(Resolved__is='2024-01-01'))


async def test_search_operator_query_string():
    queries = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(request.url.params['query'])
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    await _collect(client.search(Priority__gte=5, Subject__notstartswith="a'b", Resolved__isnot=None, CF_my__field__exact='x'))

    assert queries == ["(Priority>='5') AND (Subject NOT STARTSWITH 'a\\'b') AND (Resolved IS NOT NULL) AND ('CF.{my__field}'='x')"]


# --- URL paths ---------------------------------------------------------------------------------------------------


async def test_names_can_not_change_the_endpoint(async_rt_connection: AsyncRt):
    # previously this returned ticket 1 instead of looking up a user
    for user_name in ('../ticket/1', '..', '../../../Admin/'):
        with pytest.raises(rt.exceptions.NotFoundError):
            await async_rt_connection.get_user(user_name)

    queue_name = f'Queue with spaces & special chars {random_string()}'
    queue_id = await async_rt_connection.create_queue(queue_name)
    assert int((await async_rt_connection.get_queue(queue_name))['id']) == queue_id
    assert int((await async_rt_connection.get_queue(queue_id))['id']) == queue_id


# --- last updated -------------------------------------------------------------------------------------------------


async def test_last_updated_with_date_objects(async_rt_connection: AsyncRt):
    queue_name = f'LastUpdated {random_string()}'
    await async_rt_connection.create_queue(queue_name)
    ticket_id = await async_rt_connection.create_ticket(queue=queue_name, subject='Last updated test', content='Test')
    last_updated = (await async_rt_connection.get_ticket(ticket_id))['LastUpdated']
    updated = dt.datetime.strptime(last_updated, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.UTC)

    async def found(since: dt.date) -> list[int]:
        return [int(ticket['id']) async for ticket in async_rt_connection.last_updated(since, queue=queue_name)]

    assert await found(dt.date(2000, 1, 2)) == [ticket_id]
    assert await found(dt.datetime(2000, 1, 2, 12, 0, 0)) == [ticket_id]  # noqa: DTZ001  # naive datetime on purpose

    # a datetime with timezone is an exact point in time, in any timezone
    plus_two_hours = dt.timezone(dt.timedelta(hours=2))
    for timezone in (dt.UTC, plus_two_hours):
        assert await found((updated - dt.timedelta(minutes=1)).astimezone(timezone)) == [ticket_id]
        assert await found((updated + dt.timedelta(minutes=1)).astimezone(timezone)) == []

    with pytest.raises(rt.exceptions.InvalidUseError):
        async_rt_connection.last_updated(dt.date(1960, 1, 1))


async def test_last_updated_date_formats():
    queries = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        queries.append(request.url.params['query'])
        return _page(1, [], pages=0)

    client = _mock_client(handler)
    plus_two_hours = dt.timezone(dt.timedelta(hours=2))
    for since in (
        '2024-01-02',
        dt.date(2024, 1, 2),
        dt.datetime(2024, 1, 2, 10, 11, 12),  # noqa: DTZ001  # naive datetime on purpose
        dt.datetime(2024, 1, 2, 10, 11, 12, tzinfo=plus_two_hours),
    ):
        await _collect(client.last_updated(since))

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
            async_rt_connection.last_updated(invalid_date)

    # use a new queue, so only the ticket created here is returned (and not all tickets ever created)
    queue_name = f'LastUpdated {random_string()}'
    await async_rt_connection.create_queue(queue_name)
    ticket_id = await async_rt_connection.create_ticket(queue=queue_name, subject='Last updated test', content='Test')

    # no await needed, like for all other methods returning multiple results
    assert [int(ticket['id']) async for ticket in async_rt_connection.last_updated('2000-01-02', queue=queue_name)] == [ticket_id]
    assert [int(ticket['id']) async for ticket in async_rt_connection.last_updated('2000-01-02 12:00:00', queue=queue_name)] == [ticket_id]
    # the ticket was last updated by the user of the connection, so it is no new correspondence
    assert [int(ticket['id']) async for ticket in async_rt_connection.new_correspondence(queue=queue_name)] == []


# --- content types and link names --------------------------------------------------------------------------------


async def test_invalid_content_type():
    client = _mock_client(_no_request)

    for invalid_content_type in ('text/markdown', 'TEXT/PLAIN', ''):
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.reply(1, 'Test', content_type=invalid_content_type)  # type: ignore[arg-type]
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.comment(1, 'Test', content_type=invalid_content_type)  # type: ignore[arg-type]
        with no_type_checks(), pytest.raises(ValueError, match='content-type'):
            await client.create_ticket(RT_QUEUE, content='Test', content_type=invalid_content_type)  # type: ignore[arg-type]


async def test_valid_content_types_are_sent():
    content_types = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        content_types.append(json.loads(request.content)['ContentType'])
        return httpx2.Response(200, json=['Message recorded'])

    client = _mock_client(handler)
    assert await client.reply(1, 'Test', content_type='text/html')
    assert await client.comment(1, 'Test')

    assert content_types == ['text/html', 'text/plain']


async def test_invalid_link_name():
    with no_type_checks(), pytest.raises(rt.exceptions.InvalidUseError, match='Parent, Child, RefersTo, ReferredToBy, DependsOn, DependedOnBy'):
        await _mock_client(_no_request).edit_link(1, 'MemberOf', 2)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ('delete', 'message', 'expected'),
    [
        (False, "Link could not be created: Can't link a ticket to itself", rt.exceptions.InvalidUseError),
        (True, 'Link could not be deleted: Permission Denied', rt.exceptions.InvalidUseError),
        (False, 'Permission Denied', rt.exceptions.NotAllowedError),
    ],
)
async def test_edit_link_failed(delete: bool, message: str, expected: type[rt.exceptions.RtError]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[message])

    with pytest.raises(expected, match=message):
        await _mock_client(handler).edit_link(1, 'DependsOn', 2, delete=delete)


# --- error messages of edit operations --------------------------------------------------------------------------


async def test_edit_ticket_nonexistent_queue_and_owner(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=f'Edit test {random_string()}', content='Test')

    # queue names containing the letters d, o, e or s were not detected before
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_ticket(ticket_id, Queue=f'Support Desk {random_string()}')

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_ticket(ticket_id, Owner=f'nosuchuser{random_string()}')

    assert (await async_rt_connection.get_ticket(ticket_id))['Queue']['Name'] == RT_QUEUE


# --- pagination -----------------------------------------------------------------------------------------------


async def test_search_multiple_pages(async_rt_connection: AsyncRt):
    subject = f'Paging test {random_string()}'
    ticket_ids = sorted([await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=subject, content='Test') for _ in range(5)])

    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), per_page=2) as tracker:
        found = [int(ticket['id']) async for ticket in tracker.search(queue=RT_QUEUE, Subject=subject)]

    assert sorted(found) == ticket_ids


async def test_per_page_is_requested():
    requested = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requested.append(request.url.params['per_page'])
        return _page(1, [], pages=0)

    await _collect(_mock_client(handler).search())
    client = AsyncRt(url=RT_URL, per_page=25, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    await _collect(client.search())

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

    assert [ticket['id'] async for ticket in _mock_client(handler).search()] == ['1', '2', '3']
    assert requested_pages == [1, 2, 3, 4]


async def test_paging_with_unknown_page_count_and_no_results():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _page(1, [], pages=None)

    # previously a NotFoundError was raised
    assert await _collect(_mock_client(handler).search()) == []


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

    assert [ticket['id'] async for ticket in _mock_client(handler).search()] == ['1', '2']
    assert requested_pages == [1, 2, 3]


async def test_paging_unexpected_result():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={'id': '1'})

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await _collect(_mock_client(handler).search())


async def test_search_assets_does_not_modify_search_params(async_rt_connection: AsyncRt):
    search_params = [{'field': 'Name', 'value': f'nonexistent {random_string()}'}]
    expected = [dict(param) for param in search_params]

    assert await _collect(async_rt_connection.search_assets(search_params=search_params)) == []
    assert await _collect(async_rt_connection.search_assets(catalog_id=1, search_params=search_params)) == []

    assert search_params == expected


# --- responses which are not as expected ------------------------------------------------------------------------


async def test_invalid_json_response():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text='<html>Login</html>', headers={'Content-Type': 'text/html'})

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError) as exc_info:
        await client.get_ticket(1)
    assert exc_info.value.status_code == 200
    assert exc_info.value.response_message == '<html>Login</html>'

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.edit_ticket(1, Subject='x')
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await _collect(client.search())
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.delete_ticket(1)


async def test_delete_response_handling():
    responses: list[httpx2.Response] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses.pop(0)

    client = _mock_client(handler)

    responses.append(httpx2.Response(204))
    await client.delete_ticket(1)

    responses.append(httpx2.Response(200, json=['Ticket deleted']))
    await client.delete_user('user')

    responses.append(httpx2.Response(200, text='<html>Login</html>'))
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.delete_queue('queue')


async def test_unexpected_response_type():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == 'GET':
            return httpx2.Response(200, json=['not', 'a', 'dict'])
        return httpx2.Response(200, json={'not': 'a list'})

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.get_user('root')
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.take(1)


async def test_response_content_validation():
    responses = {
        'PUT': httpx2.Response(200, json=['Owner changed', 5]),  # status messages must be strings
        'POST': httpx2.Response(201, json={'type': 'ticket'}),  # created object without ID
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses[request.method]

    client = _mock_client(handler)

    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.take(1)
    with pytest.raises(rt.exceptions.UnexpectedResponseError):
        await client.create_ticket(RT_QUEUE, subject='x')


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
        await _collect(_mock_client(handler).get_attachments_ids(1))


async def test_created_ids_are_returned(async_rt_connection: AsyncRt):
    user_name = f'user_{random_string()}'

    assert await async_rt_connection.create_user(user_name, f'{user_name}@example.com') == user_name
    assert isinstance(await async_rt_connection.create_queue(f'Queue {random_string()}'), int)
    assert isinstance(await async_rt_connection.create_ticket(RT_QUEUE, subject='Created ID test'), int)


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
        await client.get_ticket(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='unexpected'):
        await client.get_ticket(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='Bad request'):
        await client.get_ticket(1)
    with pytest.raises(rt.exceptions.BadRequestError, match='Invalid'):
        await client.get_ticket(1)


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
        await _mock_client(handler).get_ticket(1)

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
        await _mock_client(handler).create_ticket(RT_QUEUE, subject='x')
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
        await _mock_client(handler).take(1)


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
        await _mock_client(handler).merge_ticket(1, 2)


async def test_unexpected_number_of_status_messages():
    messages: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=messages)

    client = _mock_client(handler)

    # RT returns no status message if nothing was changed
    assert await client.edit_ticket(1, Subject='unchanged') == []

    for action in (lambda: client.reply(1, 'x'), lambda: client.comment(1, 'x'), lambda: client.merge_ticket(1, 2), lambda: client.steal(1)):
        with pytest.raises(rt.exceptions.UnexpectedResponseError):
            await action()

    messages.extend(['Merge Successful', 'Owner changed from Nobody to root'])
    for action in (lambda: client.merge_ticket(1, 2), lambda: client.take(1)):
        with pytest.raises(rt.exceptions.UnexpectedResponseError):
            await action()


# --- connection handling ---------------------------------------------------------------------------------------


async def test_context_manager():
    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD)) as tracker:
        assert (await tracker.get_user(RT_USER))['Name'] == RT_USER

    assert tracker.session.is_closed


async def test_close():
    tracker = AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD))
    assert await tracker.user_exists(RT_USER)

    await tracker.aclose()

    assert tracker.session.is_closed


async def test_token_and_http_auth_are_exclusive():
    with pytest.raises(ValueError, match='either'):
        AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), token='secret')


@requires_rt_setup
async def test_token_authentication(caplog: pytest.LogCaptureFixture):
    async with AsyncRt(url=RT_URL, token=RT_TOKEN) as tracker:
        with caplog.at_level(logging.DEBUG, logger=AsyncRt.__module__):
            assert (await tracker.get_user(RT_USER))['Name'] == RT_USER
            assert await _collect(tracker.search(queue=RT_QUEUE, id=0)) == []

    assert RT_TOKEN not in caplog.text
    assert '[redacted]' in caplog.text

    # an unknown token of the same form is rejected
    owner, _, _ = RT_TOKEN.rpartition('-')
    async with AsyncRt(url=RT_URL, token=f'{owner}-{"0" * 32}') as tracker:
        with pytest.raises(rt.exceptions.AuthorizationError) as exc_info:
            await tracker.get_user(RT_USER)
    assert exc_info.value.status_code == 401


async def test_connection_error():
    tracker = AsyncRt(url=UNREACHABLE_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD))

    with pytest.raises(rt.exceptions.RtConnectionError) as exc_info:
        await tracker.get_user(RT_USER)

    # can be caught as builtin ConnectionError (as before) as well as RtError
    assert isinstance(exc_info.value, builtins.ConnectionError)
    assert isinstance(exc_info.value, rt.exceptions.RtError)
    assert isinstance(exc_info.value.cause, httpx2.ConnectError)

    with pytest.raises(rt.exceptions.RtConnectionError):
        await _collect(tracker.search())


async def test_own_client():
    http_client = httpx2.AsyncClient(auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), timeout=30)

    async with AsyncRt(url=RT_URL, client=http_client) as tracker:
        assert tracker.session is http_client
        assert (await tracker.get_user(RT_USER))['Name'] == RT_USER

    # the client is owned by the caller and must not be closed
    assert not http_client.is_closed
    await tracker.aclose()
    assert not http_client.is_closed

    async with AsyncRt(url=RT_URL, client=http_client) as tracker:
        assert await tracker.user_exists(RT_USER)

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
        assert (await tracker.get_user(RT_USER))['Name'] == RT_USER
        await tracker.create_user(f'user_{random_string()}', f'{random_string()}@example.com', Password=user_password)

    encoded_credentials = base64.b64encode(f'{RT_USER}:{RT_PASSWORD}'.encode()).decode()
    assert '[redacted]' in caplog.text
    assert encoded_credentials not in caplog.text
    assert user_password not in caplog.text
    assert 'Response status code: 200' in caplog.text


async def test_no_debug_log_if_disabled(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger=AsyncRt.__module__):
        await _mock_client(lambda request: httpx2.Response(200, json={'id': 1})).get_ticket(1)

    assert caplog.text == ''


# --- users -----------------------------------------------------------------------------------------------------


async def test_user_exists(async_rt_connection: AsyncRt):
    assert await async_rt_connection.user_exists(RT_USER)
    assert not await async_rt_connection.user_exists(f'nosuchuser{random_string()}')
    assert not await async_rt_connection.user_exists(f'nosuchuser{random_string()}', privileged=False)

    unprivileged_user = f'user_{random_string()}'
    await async_rt_connection.create_user(unprivileged_user, f'{unprivileged_user}@example.com', Privileged=0)
    assert not await async_rt_connection.user_exists(unprivileged_user)
    assert await async_rt_connection.user_exists(unprivileged_user, privileged=False)


async def test_user_exists_privileged_as_string():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=json.dumps({'id': 1, 'Privileged': '1'}))

    assert await _mock_client(handler).user_exists('root')


async def test_invalid_fields(async_rt_connection: AsyncRt):
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo, Bar.'):
        await async_rt_connection.create_user('user', 'user@example.com', Foo=1, Bar=2)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.edit_user(RT_USER, Foo=1)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.create_queue('queue', Foo=1)
    with pytest.raises(rt.exceptions.InvalidUseError, match='Unsupported names of fields: Foo.'):
        await async_rt_connection.edit_queue(RT_QUEUE, Foo=1)
