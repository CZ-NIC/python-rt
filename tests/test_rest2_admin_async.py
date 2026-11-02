"""Tests of the REST2 administration features: users, groups, custom fields, rights and system information.

The sync tests (test_rest2_admin.py) are generated from the async tests (test_rest2_admin_async.py) using unasyncd.
"""

# ruff: noqa: S101, S106

import collections.abc
import typing
import urllib.parse

import httpx2
import pytest

import rt.exceptions
from rt.common import Attachment, RightsObjectType
from rt.rest2_async import AsyncRt

from . import no_type_checks, random_string
from .conftest import RT_PASSWORD, RT_URL, RT_USER

T = typing.TypeVar('T')


async def _collect(iterator: collections.abc.AsyncIterator[T]) -> list[T]:
    """Return all items of an iterator as list."""
    return [item async for item in iterator]


def _mock_client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> AsyncRt:
    """Return a client which sends all requests to the given handler instead of RT."""
    return AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def _no_request(request: httpx2.Request) -> httpx2.Response:
    """Handler for tests which must not send any request."""
    raise AssertionError('no request must be sent')


def _small_pages_client() -> AsyncRt:
    """Return a client requesting 2 items per page, to test results split into several pages."""
    return AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), http_timeout=None, per_page=2)


async def _create_user(connection: AsyncRt, **kwargs: typing.Any) -> tuple[str, int]:
    """Create a user with a random name and return its name and ID."""
    name = f'user-{random_string()}'
    await connection.create_user(name, f'{name}@example.com', **kwargs)
    user = await connection.get_user(name)
    return name, int(user['id'])


async def _create_group(connection: AsyncRt) -> int:
    """Create a group with a random name and return its ID."""
    return await connection.create_group(f'group-{random_string()}', Description='python-rt test')


async def _create_queue(connection: AsyncRt) -> tuple[str, int]:
    """Create a queue with a random name and return its name and ID."""
    name = f'queue-{random_string()}'
    return name, await connection.create_queue(name)


# --- system --------------------------------------------------------------------------------------------------------


async def test_get_system_info(async_rt_connection: AsyncRt):
    info = await async_rt_connection.get_system_info()

    assert isinstance(info['Version'], str)
    assert info['Version']
    assert isinstance(info['Plugins'], list)


# --- conflicts -----------------------------------------------------------------------------------------------------


async def test_conflict_error():
    async with _mock_client(lambda request: httpx2.Response(409, json={'message': 'already granted'})) as tracker:
        with pytest.raises(rt.exceptions.ConflictError, match='already granted') as exc_info:
            await tracker.get_system_info()

    # ConflictError is a subclass of the exception raised for status 409 before
    assert isinstance(exc_info.value, rt.exceptions.UnexpectedResponseError)
    assert exc_info.value.status_code == 409


# --- users ---------------------------------------------------------------------------------------------------------


async def test_search_users(async_rt_connection: AsyncRt):
    name, _ = await _create_user(async_rt_connection, RealName='Search Test')

    found = await _collect(async_rt_connection.search_users(search_params=[{'field': 'Name', 'value': name}]))

    assert [user['Name'] for user in found] == [name]
    assert found[0]['RealName'] == 'Search Test'
    assert found[0]['EmailAddress'] == f'{name}@example.com'
    assert 'Disabled' in found[0]


async def test_search_users_privileged(async_rt_connection: AsyncRt):
    privileged_name, _ = await _create_user(async_rt_connection, Privileged=1)
    unprivileged_name, _ = await _create_user(async_rt_connection)
    condition = [{'field': 'Name', 'operator': 'LIKE', 'value': 'user-'}]

    privileged = [user['Name'] async for user in async_rt_connection.search_users(search_params=condition, privileged=True)]
    unprivileged = [user['Name'] async for user in async_rt_connection.search_users(search_params=condition, privileged=False)]

    assert privileged_name in privileged
    assert privileged_name not in unprivileged
    assert unprivileged_name in unprivileged
    assert unprivileged_name not in privileged


async def test_search_users_disabled(async_rt_connection: AsyncRt):
    name, _ = await _create_user(async_rt_connection)
    await async_rt_connection.delete_user(name)
    condition = [{'field': 'Name', 'value': name}]

    assert await _collect(async_rt_connection.search_users(search_params=condition)) == []
    assert [user['Name'] async for user in async_rt_connection.search_users(search_params=condition, include_disabled=True)] == [name]


async def test_search_users_all_pages(async_rt_connection: AsyncRt):
    await _create_user(async_rt_connection)
    await _create_user(async_rt_connection)

    all_users = [user['id'] async for user in async_rt_connection.search_users()]
    async with _small_pages_client() as tracker:
        paged_users = [user['id'] async for user in tracker.search_users()]

    assert len(all_users) > 2
    assert sorted(paged_users) == sorted(all_users)


# --- groups --------------------------------------------------------------------------------------------------------


async def test_group(async_rt_connection: AsyncRt):
    name = f'group-{random_string()}'
    group_id = await async_rt_connection.create_group(name, Description='first')

    group = await async_rt_connection.get_group(group_id)
    assert group['Name'] == name
    assert group['Description'] == 'first'

    found = await _collect(async_rt_connection.search_groups(search_params=[{'field': 'Name', 'value': name}]))
    assert [(int(item['id']), item['Name'], item['Description']) for item in found] == [(group_id, name, 'first')]

    messages = await async_rt_connection.edit_group(group_id, Description='second')
    assert len(messages) == 1
    assert 'Description' in messages[0]
    assert (await async_rt_connection.get_group(group_id))['Description'] == 'second'

    with pytest.raises(rt.exceptions.BadRequestError, match='already in use'):
        await async_rt_connection.create_group(name)


async def test_delete_group(async_rt_connection: AsyncRt):
    name = f'group-{random_string()}'
    group_id = await async_rt_connection.create_group(name)
    condition = [{'field': 'Name', 'value': name}]

    await async_rt_connection.delete_group(group_id)

    assert (await async_rt_connection.get_group(group_id))['Disabled'] == '1'
    assert await _collect(async_rt_connection.search_groups(search_params=condition)) == []
    assert [int(item['id']) async for item in async_rt_connection.search_groups(search_params=condition, include_disabled=True)] == [group_id]


async def test_group_not_found(async_rt_connection: AsyncRt):
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.get_group(999999)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_group(999999, Description='x')


async def test_group_members(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    inner_group_id = await _create_group(async_rt_connection)
    user_name, user_id = await _create_user(async_rt_connection)
    _, inner_user_id = await _create_user(async_rt_connection)

    assert await async_rt_connection.add_group_member(group_id, user_id) == [f'Member added: {user_name}']
    await async_rt_connection.add_group_member(group_id, inner_group_id)
    await async_rt_connection.add_group_member(inner_group_id, inner_user_id)

    async def member_ids(**kwargs: bool) -> set[tuple[str, int]]:
        return {(member['type'], int(member['id'])) async for member in async_rt_connection.get_group_members(group_id, **kwargs)}

    assert await member_ids() == {('user', user_id), ('group', inner_group_id)}
    assert await member_ids(users=False) == {('group', inner_group_id)}
    assert await member_ids(groups=False) == {('user', user_id)}
    assert await member_ids(recursive=True, groups=False) == {('user', user_id), ('user', inner_user_id)}

    # get_group returns the direct members with the names of users
    members = (await async_rt_connection.get_group(group_id))['Members']
    assert {str(member['id']) for member in members} == {user_name, str(inner_group_id)}

    await async_rt_connection.remove_group_member(group_id, user_id)
    assert await member_ids() == {('group', inner_group_id)}
    # RT also confirms removing a principal which is not a member
    await async_rt_connection.remove_group_member(group_id, user_id)

    await async_rt_connection.remove_all_group_members(group_id)
    assert await member_ids() == set()


async def test_group_members_all_pages(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    user_ids = set()
    for _ in range(5):
        _, user_id = await _create_user(async_rt_connection)
        await async_rt_connection.add_group_member(group_id, user_id)
        user_ids.add(user_id)

    # RT does not return the number of pages for members
    async with _small_pages_client() as tracker:
        members = [int(member['id']) async for member in tracker.get_group_members(group_id)]

    assert sorted(members) == sorted(user_ids)


async def test_add_group_member_refused(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    _, user_id = await _create_user(async_rt_connection)
    await async_rt_connection.add_group_member(group_id, user_id)

    with pytest.raises(rt.exceptions.InvalidUseError, match='already has member'):
        await async_rt_connection.add_group_member(group_id, user_id)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.add_group_member(group_id, 999999)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.add_group_member(999999, user_id)


async def test_get_group_members_users_and_groups_excluded():
    async with _mock_client(_no_request) as tracker:
        with pytest.raises(rt.exceptions.InvalidUseError):
            await _collect(tracker.get_group_members(1, users=False, groups=False))


async def test_user_groups(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    other_group_id = await _create_group(async_rt_connection)
    user_name, _ = await _create_user(async_rt_connection)

    assert await async_rt_connection.add_user_to_group(user_name, group_id) == [f'Member added: {user_name}']
    await async_rt_connection.add_user_to_group(user_name, other_group_id)
    assert {int(group['id']) async for group in async_rt_connection.get_user_groups(user_name)} == {group_id, other_group_id}

    await async_rt_connection.remove_user_from_group(user_name, group_id)
    assert [int(group['id']) async for group in async_rt_connection.get_user_groups(user_name)] == [other_group_id]
    # RT also confirms removing a user which is not a member
    await async_rt_connection.remove_user_from_group(user_name, group_id)

    await async_rt_connection.remove_user_from_all_groups(user_name)
    assert await _collect(async_rt_connection.get_user_groups(user_name)) == []


async def test_add_user_to_group_refused(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    user_name, _ = await _create_user(async_rt_connection)
    await async_rt_connection.add_user_to_group(user_name, group_id)

    with pytest.raises(rt.exceptions.InvalidUseError, match='already has member'):
        await async_rt_connection.add_user_to_group(user_name, group_id)

    with pytest.raises(rt.exceptions.NotFoundError, match='not found'):
        await async_rt_connection.add_user_to_group(user_name, 999999)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.add_user_to_group(f'missing-{random_string()}', group_id)


@pytest.mark.parametrize('result', [[], [1], ['1', 'Member added'], [1, 2], {'message': 'x'}])
async def test_add_user_to_group_unexpected_response(result: typing.Any):
    async with _mock_client(lambda request: httpx2.Response(200, json=result)) as tracker:
        with pytest.raises(rt.exceptions.UnexpectedResponseError):
            await tracker.add_user_to_group('alice', 1)


# --- custom fields -------------------------------------------------------------------------------------------------


async def test_custom_field(async_rt_connection: AsyncRt):
    queue_name, queue_id = await _create_queue(async_rt_connection)
    name = f'cf-{random_string()}'

    cf_id = await async_rt_connection.create_custom_field(name, 'Select', 'RT::Queue-RT::Ticket', MaxValues=1, Queue=queue_name)

    custom_field = await async_rt_connection.get_custom_field(cf_id)
    assert (custom_field['Name'], custom_field['Type'], custom_field['LookupType']) == (name, 'Select', 'RT::Queue-RT::Ticket')

    by_name = await _collect(async_rt_connection.search_custom_fields(search_params=[{'field': 'Name', 'value': name}]))
    assert [(int(item['id']), item['Name'], item['Type']) for item in by_name] == [(cf_id, name, 'Select')]
    assert cf_id in [int(item['id']) async for item in async_rt_connection.search_custom_fields()]
    assert [int(item['id']) async for item in async_rt_connection.search_custom_fields(object_type='queue', object_id=queue_id)] == [cf_id]

    messages = await async_rt_connection.edit_custom_field(cf_id, Description='edited')
    assert len(messages) == 1
    assert 'Description' in messages[0]
    # RT reports invalid values only in the messages
    messages = await async_rt_connection.edit_custom_field(cf_id, Type='Invalid')
    assert len(messages) == 1
    assert 'Illegal value' in messages[0]


async def test_custom_field_invalid(async_rt_connection: AsyncRt):
    with pytest.raises(rt.exceptions.BadRequestError, match='Type'):
        await async_rt_connection.create_custom_field(f'cf-{random_string()}', 'Invalid', 'RT::Queue-RT::Ticket')

    with pytest.raises(rt.exceptions.BadRequestError, match='Queue'):
        await async_rt_connection.create_custom_field(f'cf-{random_string()}', 'Freeform', 'RT::Queue-RT::Ticket', Queue=f'missing-{random_string()}')

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.get_custom_field(999999)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_custom_field(999999, Description='x')


async def test_delete_custom_field(async_rt_connection: AsyncRt):
    name = f'cf-{random_string()}'
    cf_id = await async_rt_connection.create_custom_field(name, 'Freeform', 'RT::Queue-RT::Ticket')
    condition = [{'field': 'Name', 'value': name}]

    await async_rt_connection.delete_custom_field(cf_id)

    assert (await async_rt_connection.get_custom_field(cf_id))['Disabled'] == '1'
    assert await _collect(async_rt_connection.search_custom_fields(search_params=condition)) == []
    assert [int(item['id']) async for item in async_rt_connection.search_custom_fields(search_params=condition, include_disabled=True)] == [cf_id]


@pytest.mark.parametrize(
    ('object_type', 'object_id'),
    [('queue', None), (None, 1), ('ticket', 1)],
)
async def test_search_custom_fields_invalid_object(object_type: typing.Any, object_id: int | None):
    async with _mock_client(_no_request) as tracker:
        with no_type_checks(), pytest.raises(rt.exceptions.InvalidUseError):
            await _collect(tracker.search_custom_fields(object_type=object_type, object_id=object_id))


async def test_custom_field_values(async_rt_connection: AsyncRt):
    cf_id = await async_rt_connection.create_custom_field(f'cf-{random_string()}', 'Select', 'RT::Queue-RT::Ticket', MaxValues=1)

    high_id = await async_rt_connection.add_custom_field_value(cf_id, 'High', SortOrder=1)
    low_id = await async_rt_connection.add_custom_field_value(cf_id, 'Low', Description='lowest', SortOrder=2)

    values = await _collect(async_rt_connection.get_custom_field_values(cf_id))
    assert {(int(value['id']), value['name']) for value in values} == {(high_id, 'High'), (low_id, 'Low')}
    found = await _collect(async_rt_connection.get_custom_field_values(cf_id, search_params=[{'field': 'Name', 'value': 'Low'}]))
    assert [int(value['id']) for value in found] == [low_id]
    assert sorted((await async_rt_connection.get_custom_field(cf_id))['Values']) == ['High', 'Low']

    value = await async_rt_connection.get_custom_field_value(cf_id, low_id)
    assert (value['Name'], value['Description']) == ('Low', 'lowest')

    messages = await async_rt_connection.edit_custom_field_value(cf_id, low_id, Description='changed')
    assert len(messages) == 1
    assert 'Description' in messages[0]
    assert (await async_rt_connection.get_custom_field_value(cf_id, low_id))['Description'] == 'changed'

    await async_rt_connection.delete_custom_field_value(cf_id, low_id)
    assert [int(value['id']) async for value in async_rt_connection.get_custom_field_values(cf_id)] == [high_id]
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.get_custom_field_value(cf_id, low_id)
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.delete_custom_field_value(cf_id, low_id)

    with pytest.raises(rt.exceptions.BadRequestError):
        await async_rt_connection.add_custom_field_value(cf_id, '')


async def test_apply_custom_field(async_rt_connection: AsyncRt):
    queue_name, queue_id = await _create_queue(async_rt_connection)
    other_queue_name, other_queue_id = await _create_queue(async_rt_connection)
    name = f'cf-{random_string()}'
    cf_id = await async_rt_connection.create_custom_field(name, 'Freeform', 'RT::Queue-RT::Ticket', Queue=queue_name)

    async def applied_to() -> list[int]:
        return sorted([item['ObjectId'] async for item in async_rt_connection.get_custom_field_applies_to(cf_id)])

    assert await applied_to() == [queue_id]

    assert await async_rt_connection.apply_custom_field(cf_id, other_queue_id) == [f'Added custom field {name} to {other_queue_name}.']
    assert await applied_to() == sorted([queue_id, other_queue_id])
    assert [int(item['id']) async for item in async_rt_connection.search_custom_fields(object_type='queue', object_id=other_queue_id)] == [cf_id]

    with pytest.raises(rt.exceptions.ConflictError, match='already applied'):
        await async_rt_connection.apply_custom_field(cf_id, other_queue_id)
    with pytest.raises(rt.exceptions.BadRequestError):
        await async_rt_connection.apply_custom_field(cf_id, 999999)

    await async_rt_connection.unapply_custom_field(cf_id, queue_id)
    assert await applied_to() == [other_queue_id]
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.unapply_custom_field(cf_id, queue_id)

    # applied globally, the custom field is removed from all queues
    await async_rt_connection.apply_custom_field(cf_id, 0)
    assert [item['ObjectId'] async for item in async_rt_connection.get_custom_field_applies_to(cf_id)] == [0]
    await async_rt_connection.unapply_custom_field(cf_id, 0)
    assert await applied_to() == []


async def test_custom_field_file(async_rt_connection: AsyncRt):
    queue_name, _ = await _create_queue(async_rt_connection)
    cf_id = await async_rt_connection.create_custom_field(f'cf-{random_string()}', 'Binary', 'RT::Queue-RT::Ticket', MaxValues=1, Queue=queue_name)
    content = b'binary \x00\x01\xff content'
    ticket_id = await async_rt_connection.create_ticket(queue_name, subject='File custom field')

    await async_rt_connection.edit_ticket(ticket_id, CustomFields={str(cf_id): Attachment('file.bin', 'application/octet-stream', content).to_dict()})

    ticket = await async_rt_connection.get_ticket(ticket_id)
    (value,) = [custom_field for custom_field in ticket['CustomFields'] if int(custom_field['id']) == cf_id][0]['values']
    assert value['filename'] == 'file.bin'
    value_id = value['_url'].rsplit('/', 1)[1]
    assert await async_rt_connection.get_custom_field_file(value_id) == content

    with pytest.raises(rt.exceptions.NotAllowedError):
        await async_rt_connection.get_custom_field_file(999999)


# --- rights --------------------------------------------------------------------------------------------------------


async def test_rights_of_group(async_rt_connection: AsyncRt):
    queue_name, queue_id = await _create_queue(async_rt_connection)
    group_id = await _create_group(async_rt_connection)

    granted = await async_rt_connection.grant_right('queue', queue_name, 'CreateTicket', group=group_id)
    assert granted['Right'] == 'CreateTicket'
    assert int(granted['Group']['id']) == group_id

    rights = await _collect(async_rt_connection.get_rights('queue', queue_id, group=group_id))
    assert [(right['Right'], int(right['Group']['id'])) for right in rights] == [('CreateTicket', group_id)]

    with pytest.raises(rt.exceptions.ConflictError, match='already has the right'):
        await async_rt_connection.grant_right('queue', queue_id, 'CreateTicket', group=group_id)

    await async_rt_connection.revoke_right('queue', queue_name, 'CreateTicket', group=group_id)
    assert await _collect(async_rt_connection.get_rights('queue', queue_id, group=group_id)) == []

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.revoke_right('queue', queue_id, 'CreateTicket', group=group_id)


async def test_rights_of_user(async_rt_connection: AsyncRt):
    queue_name, _ = await _create_queue(async_rt_connection)
    user_name, user_id = await _create_user(async_rt_connection, Privileged=1)

    # users can be identified by name and ID
    granted = await async_rt_connection.grant_right('queue', queue_name, 'ShowTicket', user=user_name)
    assert int(granted['User']['id']) == user_id
    await async_rt_connection.grant_right('queue', queue_name, 'SeeQueue', user=user_id)

    by_name = {right['Right'] async for right in async_rt_connection.get_rights('queue', queue_name, user=user_name)}
    by_id = {right['Right'] async for right in async_rt_connection.get_rights('queue', queue_name, user=user_id)}
    assert by_name == by_id == {'ShowTicket', 'SeeQueue'}

    await async_rt_connection.revoke_right('queue', queue_name, 'ShowTicket', user=user_id)
    await async_rt_connection.revoke_right('queue', queue_name, 'SeeQueue', user=user_name)
    assert await _collect(async_rt_connection.get_rights('queue', queue_name, user=user_name)) == []


async def test_global_rights(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)

    await async_rt_connection.grant_right('global', None, 'SeeQueue', group=group_id)
    assert [right['Right'] async for right in async_rt_connection.get_rights('global', group=group_id)] == ['SeeQueue']

    await async_rt_connection.revoke_right('global', None, 'SeeQueue', group=group_id)
    assert await _collect(async_rt_connection.get_rights('global', group=group_id)) == []


async def test_rights_on_other_objects(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)
    other_group_id = await _create_group(async_rt_connection)
    cf_id = await async_rt_connection.create_custom_field(f'cf-{random_string()}', 'Freeform', 'RT::Queue-RT::Ticket')

    objects: list[tuple[RightsObjectType, int, str]] = [
        ('group', other_group_id, 'SeeGroup'),
        ('customfield', cf_id, 'SeeCustomField'),
        ('catalog', 1, 'ShowAsset'),
        ('class', 1, 'ShowArticle'),
    ]
    for object_type, object_id, right in objects:
        assert any(right in rights for rights in (await async_rt_connection.get_available_rights(object_type, object_id)).values())

        await async_rt_connection.grant_right(object_type, object_id, right, group=group_id)
        assert [item['Right'] async for item in async_rt_connection.get_rights(object_type, object_id, group=group_id)] == [right]
        await async_rt_connection.revoke_right(object_type, object_id, right, group=group_id)


async def test_available_rights(async_rt_connection: AsyncRt):
    queue_rights = await async_rt_connection.get_available_rights('queue', 1)
    global_rights = await async_rt_connection.get_available_rights('global')

    assert 'CreateTicket' in {right for rights in queue_rights.values() for right in rights}
    assert 'SuperUser' in {right for rights in global_rights.values() for right in rights}
    assert all(isinstance(description, str) for rights in queue_rights.values() for description in rights.values())


async def test_rights_errors(async_rt_connection: AsyncRt):
    group_id = await _create_group(async_rt_connection)

    with pytest.raises(rt.exceptions.BadRequestError, match='Invalid right'):
        await async_rt_connection.grant_right('queue', 1, 'NoSuchRight', group=group_id)
    with pytest.raises(rt.exceptions.BadRequestError):
        await async_rt_connection.grant_right('queue', 1, 'CreateTicket', group=999999)
    with pytest.raises(rt.exceptions.NotFoundError):
        await _collect(async_rt_connection.get_rights('queue', 999999))


async def test_rights_not_allowed(async_rt_connection: AsyncRt):
    user_name, _ = await _create_user(async_rt_connection, Privileged=1, Password='password-of-test-user')

    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(user_name, 'password-of-test-user'), http_timeout=None) as tracker:
        with pytest.raises(rt.exceptions.NotAllowedError):
            await _collect(tracker.get_rights('queue', 1))


@pytest.mark.parametrize(
    ('object_type', 'object_id', 'principal'),
    [
        ('ticket', 1, {'user': 'root'}),
        ('queue', None, {'user': 'root'}),
        ('queue', '', {'user': 'root'}),
        ('global', 1, {'user': 'root'}),
        ('queue', 1, {}),
        ('queue', 1, {'user': 'root', 'group': 1}),
    ],
)
async def test_rights_invalid_use(object_type: typing.Any, object_id: int | str | None, principal: dict[str, typing.Any]):
    async with _mock_client(_no_request) as tracker:
        with no_type_checks():
            with pytest.raises(rt.exceptions.InvalidUseError):
                await tracker.grant_right(object_type, object_id, 'CreateTicket', **principal)
            with pytest.raises(rt.exceptions.InvalidUseError):
                await tracker.revoke_right(object_type, object_id, 'CreateTicket', **principal)
            if principal:
                with pytest.raises(rt.exceptions.InvalidUseError):
                    await _collect(tracker.get_rights(object_type, object_id, **principal))


async def test_create_custom_field_queue_for_other_lookup_type():
    # RT would silently create a ticket custom field instead
    async with _mock_client(_no_request) as tracker:
        with pytest.raises(rt.exceptions.InvalidUseError, match='Queue'):
            await tracker.create_custom_field('Notes', 'Freeform', 'RT::Queue-RT::Ticket-RT::Transaction', Queue='General')


# --- catalogs and assets -------------------------------------------------------------------------------------------


async def _create_catalog(connection: AsyncRt) -> tuple[str, int]:
    """Create a catalog with a random name and return its name and ID."""
    name = f'catalog-{random_string()}'
    return name, await connection.create_catalog(name, Description='python-rt test')


async def test_catalog(async_rt_connection: AsyncRt):
    name, catalog_id = await _create_catalog(async_rt_connection)

    catalog = await async_rt_connection.get_catalog(name)
    assert (int(catalog['id']), catalog['Description'], catalog['Lifecycle']) == (catalog_id, 'python-rt test', 'assets')

    found = await _collect(async_rt_connection.search_catalogs(search_params=[{'field': 'Name', 'value': name}]))
    assert [(int(item['id']), item['Name'], item['Description']) for item in found] == [(catalog_id, name, 'python-rt test')]
    assert catalog_id in [int(item['id']) async for item in async_rt_connection.search_catalogs()]
    all_catalogs = {int(item['id']): item async for item in async_rt_connection.get_all_catalogs()}
    assert all_catalogs[catalog_id]['Name'] == name

    messages = await async_rt_connection.edit_catalog(name, Description='edited')
    assert len(messages) == 1
    assert 'Description' in messages[0]
    assert (await async_rt_connection.get_catalog(catalog_id))['Description'] == 'edited'


async def test_catalog_errors(async_rt_connection: AsyncRt):
    name, _ = await _create_catalog(async_rt_connection)

    with pytest.raises(rt.exceptions.BadRequestError, match='unique'):
        await async_rt_connection.create_catalog(name)
    with pytest.raises(rt.exceptions.BadRequestError, match='lifecycle'):
        await async_rt_connection.create_catalog(f'catalog-{random_string()}', Lifecycle='invalid')
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_catalog(999999, Description='x')


async def test_delete_catalog(async_rt_connection: AsyncRt):
    name, catalog_id = await _create_catalog(async_rt_connection)
    condition = [{'field': 'Name', 'value': name}]

    await async_rt_connection.delete_catalog(catalog_id)

    assert (await async_rt_connection.get_catalog(catalog_id))['Disabled'] == '1'
    assert catalog_id not in [int(item['id']) async for item in async_rt_connection.get_all_catalogs()]
    assert catalog_id in [int(item['id']) async for item in async_rt_connection.get_all_catalogs(include_disabled=True)]
    assert await _collect(async_rt_connection.search_catalogs(search_params=condition)) == []
    assert [int(item['id']) async for item in async_rt_connection.search_catalogs(search_params=condition, include_disabled=True)] == [catalog_id]


async def test_search_assets_raw_query(async_rt_connection: AsyncRt):
    catalog_name, catalog_id = await _create_catalog(async_rt_connection)
    asset_name = f'Grüße {random_string()}'
    asset_id = await async_rt_connection.create_asset(asset_name, catalog_id)
    await async_rt_connection.create_asset(f'other {random_string()}', catalog_id)

    query = f"Catalog = '{catalog_name}' AND Name = '{asset_name}'"
    found = [(int(asset['id']), asset['Name']) async for asset in async_rt_connection.search_assets(raw_query=query, fields='Name')]

    assert found == [(asset_id, asset_name)]


async def test_search_assets_raw_query_request():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={'page': 1, 'per_page': 100, 'pages': 0, 'total': 0, 'count': 0, 'items': []})

    async with _mock_client(handler) as tracker:
        await _collect(tracker.search_assets(raw_query="Status = 'new'"))

    (request,) = requests
    assert request.method == 'POST'
    assert urllib.parse.parse_qs(request.content.decode()) == {'query': ["Status = 'new'"]}
    assert 'query' not in request.url.params


@pytest.mark.parametrize(
    'arguments',
    [
        {'raw_query': ''},
        {'raw_query': '  '},
        {'raw_query': "Status = 'new'", 'catalog_id': 1},
        {'raw_query': "Status = 'new'", 'search_params': []},
    ],
)
async def test_search_assets_raw_query_invalid_use(arguments: dict[str, typing.Any]):
    async with _mock_client(_no_request) as tracker:
        with pytest.raises(rt.exceptions.InvalidUseError):
            await _collect(tracker.search_assets(**arguments))


async def test_delete_asset(async_rt_connection: AsyncRt):
    _, catalog_id = await _create_catalog(async_rt_connection)
    asset_name = f'asset-{random_string()}'
    asset_id = await async_rt_connection.create_asset(asset_name, catalog_id)

    await async_rt_connection.delete_asset(asset_id)

    assert (await async_rt_connection.get_asset(asset_id))['Status'] == 'deleted'
    assert await _collect(async_rt_connection.search_assets(catalog_id=catalog_id, search_params=[{'field': 'Name', 'value': asset_name}])) == []
    # deleting an asset again is no error
    await async_rt_connection.delete_asset(asset_id)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.delete_asset(999999)


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ("Status 'deleted' isn't a valid status for this asset.", rt.exceptions.InvalidUseError),
        ('Asset 1: Permission Denied', rt.exceptions.NotAllowedError),
    ],
)
async def test_delete_asset_refused(message: str, expected: type[rt.exceptions.RtError]):
    async with _mock_client(lambda request: httpx2.Response(200, json=[message])) as tracker:
        with pytest.raises(expected, match=message):
            await tracker.delete_asset(1)
