"""Check that the library recognizes the messages RT returns for refused changes.

RT reports refusals only as messages (see :py:func:`rt.common._message_error_type`), so a reworded message in a new
release of RT silently turns a refusal into a success. The tests provoke the refusals in RT and check that the
messages are classified, in contrast to the unit tests in test_common.py, which use messages copied from RT.
They need the English RT of the README (the language of the user must be English).

The sync tests (test_rest2_messages.py) are generated from the async tests (test_rest2_messages_async.py) using unasyncd.
"""

# ruff: noqa: S101, SLF001

import collections.abc
import typing

import httpx2
import pytest

import rt.common
import rt.exceptions
from rt.rest2_async import AsyncRt

from . import random_string
from .conftest import RT_QUEUE, RT_URL, RT_USER

# Exceptions for refused actions; `Case` is (description, function sending the request, expected exception)
Case = tuple[str, collections.abc.Callable[[], collections.abc.Awaitable[typing.Any]], type[rt.exceptions.RtError]]
# `Request` is (description, function sending the request)
Request = tuple[str, collections.abc.Callable[[], collections.abc.Awaitable[typing.Any]]]


def _assert_recognized(description: str, message: str, expected: type[rt.exceptions.RtError]) -> None:
    """Check that the message of RT for a refusal is recognized and classified as expected."""
    error_type = rt.common._message_error_type(message)

    assert error_type is not None, f'{description}: the message of RT is not recognized as refusal: {message!r}'
    assert error_type is expected, f'{description}: {message!r} is classified as {error_type.__name__}, not as {expected.__name__}'


async def test_refusals_of_actions(async_rt_connection: AsyncRt):
    """Actions which change one thing raise an exception for the message of RT, which has to be recognized."""
    tracker = async_rt_connection
    subject = f'Refusals {random_string()}'
    ticket_id = await tracker.tickets.create(RT_QUEUE, subject=subject, content='Test')
    other_id = await tracker.tickets.create(RT_QUEUE, subject=subject, content='Test')
    deleted_id = await tracker.tickets.create(RT_QUEUE, subject=subject, content='Test')
    await tracker.tickets.delete(deleted_id)
    group_id = await tracker.groups.create(f'group-{random_string()}')
    await tracker.groups.add_member(group_id, 1)  # the principal with the ID 1 exists in every RT
    await tracker.tickets.take(ticket_id)
    await tracker.tickets.edit_link(ticket_id, 'DependsOn', other_id)

    cases: list[Case] = [
        ('take a ticket which is owned', lambda: tracker.tickets.take(ticket_id), rt.exceptions.InvalidUseError),
        ('untake a ticket which is not owned', lambda: tracker.tickets.untake(other_id), rt.exceptions.InvalidUseError),
        ('steal a ticket which is owned by the user', lambda: tracker.tickets.steal(ticket_id), rt.exceptions.InvalidUseError),
        ('steal a ticket which is not owned', lambda: tracker.tickets.steal(other_id), rt.exceptions.InvalidUseError),
        ('merge a ticket into itself', lambda: tracker.tickets.merge(ticket_id, ticket_id), rt.exceptions.InvalidUseError),
        ('merge into a missing ticket', lambda: tracker.tickets.merge(ticket_id, 999999999), rt.exceptions.NotFoundError),
        ('link a ticket to itself', lambda: tracker.tickets.edit_link(ticket_id, 'RefersTo', ticket_id), rt.exceptions.InvalidUseError),
        ('link to a missing ticket', lambda: tracker.tickets.edit_link(ticket_id, 'RefersTo', 999999999), rt.exceptions.NotFoundError),
        ('link to a deleted ticket', lambda: tracker.tickets.edit_link(ticket_id, 'RefersTo', deleted_id), rt.exceptions.InvalidUseError),
        ('circular link', lambda: tracker.tickets.edit_link(other_id, 'DependsOn', ticket_id), rt.exceptions.InvalidUseError),
        ('add a member twice', lambda: tracker.groups.add_member(group_id, 1), rt.exceptions.InvalidUseError),
        ('add a missing member', lambda: tracker.groups.add_member(group_id, 999999999), rt.exceptions.NotFoundError),
        ('add a missing user to a group', lambda: tracker.users.add_to_group(f'missing-{random_string()}', group_id), rt.exceptions.NotFoundError),
        ('add a user to a missing group', lambda: tracker.users.add_to_group(RT_USER, 999999999), rt.exceptions.NotFoundError),
    ]

    for description, send, expected in cases:
        with pytest.raises(expected) as exc_info:
            await send()

        # the exception type of a refusal which is not recognized is InvalidUseError, which hides a missing pattern
        _assert_recognized(description, str(exc_info.value), expected)


async def test_refusals_of_partial_changes(async_rt_connection: AsyncRt):
    """Changes which RT can apply partly report the refused parts in the result, which have to be recognized."""
    tracker = async_rt_connection
    ticket_id = await tracker.tickets.create(RT_QUEUE, subject=f'Partial {random_string()}', content='Test')
    queue_id = await tracker.queues.create(f'queue-{random_string()}')
    custom_field_id = await tracker.custom_fields.create(f'cf-{random_string()}', 'Freeform', 'RT::Queue-RT::Ticket')
    select_field_id = await tracker.custom_fields.create(f'cf-{random_string()}', 'Select', 'RT::Queue-RT::Ticket')
    user_name = f'user-{random_string()}'
    await tracker.users.create(user_name, f'{user_name}@example.com')
    class_id = await tracker.classes.create(f'class-{random_string()}')
    article_id = await tracker.articles.create(f'article-{random_string()}', class_id)

    cases: list[Case] = [
        ('invalid status', lambda: tracker.tickets.edit(ticket_id, Status='invalid'), rt.exceptions.InvalidUseError),
        ('missing owner', lambda: tracker.tickets.edit(ticket_id, Owner=f'missing-{random_string()}'), rt.exceptions.NotFoundError),
        ('missing queue', lambda: tracker.tickets.edit(ticket_id, Queue=f'Support Desk {random_string()}'), rt.exceptions.NotFoundError),
        ('invalid lifecycle', lambda: tracker.queues.edit(queue_id, Lifecycle='invalid'), rt.exceptions.InvalidUseError),
        ('invalid type of a custom field', lambda: tracker.custom_fields.edit(custom_field_id, Type='Invalid'), rt.exceptions.InvalidUseError),
        ('invalid pattern of a custom field', lambda: tracker.custom_fields.edit(custom_field_id, Pattern='(['), rt.exceptions.InvalidUseError),
        ('render type of a freeform field', lambda: tracker.custom_fields.edit(custom_field_id, RenderType='Dropdown'), rt.exceptions.InvalidUseError),
        ('invalid render type', lambda: tracker.custom_fields.edit(select_field_id, RenderType='Invalid'), rt.exceptions.InvalidUseError),
        ('values of a freeform field', lambda: tracker.custom_fields.edit(custom_field_id, ValuesClass='Invalid::Class'), rt.exceptions.InvalidUseError),
        ('invalid values source', lambda: tracker.custom_fields.edit(select_field_id, ValuesClass='Invalid::Class'), rt.exceptions.InvalidUseError),
        ('canonicalizer of a select field', lambda: tracker.custom_fields.edit(select_field_id, CanonicalizeClass='Invalid'), rt.exceptions.InvalidUseError),
        ('empty name of a user', lambda: tracker.users.edit(user_name, Name=''), rt.exceptions.InvalidUseError),
        ('link of an article to a number', lambda: tracker.articles.edit(article_id, RefersTo=999999999), rt.exceptions.InvalidUseError),
        ('invalid status of a reply', lambda: tracker.tickets.reply(ticket_id, 'Reply', status='invalid'), rt.exceptions.InvalidUseError),
        ('invalid status of a comment', lambda: tracker.tickets.comment(ticket_id, 'Comment', status='invalid'), rt.exceptions.InvalidUseError),
    ]

    for description, send, expected in cases:
        result = await send()

        # RT executed the request
        assert result, description
        assert not result.complete, f'{description}: the refusal is not recognized in {result.messages!r}'
        assert len(result.refused) == 1, f'{description}: {result.messages!r}'
        _assert_recognized(description, result.refused[0], expected)
        with pytest.raises(expected):
            result.raise_for_refused()

    # the refused owner and queue were not set
    ticket = await tracker.tickets.get(ticket_id)
    assert ticket['Queue']['Name'] == RT_QUEUE
    assert ticket['Owner']['id'] == 'Nobody'


async def test_accepted_changes_are_complete(async_rt_connection: AsyncRt):
    """The messages RT returns for successful changes must not be recognized as refusals."""
    tracker = async_rt_connection
    ticket_id = await tracker.tickets.create(RT_QUEUE, subject=f'Complete {random_string()}', content='Test')
    other_id = await tracker.tickets.create(RT_QUEUE, subject=f'Complete {random_string()}', content='Test')
    catalog_id = await tracker.catalogs.create(f'catalog-{random_string()}')
    asset_id = await tracker.assets.create(f'asset-{random_string()}', catalog_id)
    # values which look like a refusal
    subject = "Can't set 'Permission Denied' - invalid status"

    for result in (
        await tracker.tickets.edit(ticket_id, Subject=subject),
        await tracker.tickets.edit(ticket_id, Subject=subject),  # nothing changed
        await tracker.tickets.edit(ticket_id, Priority=5, Subject=f'{subject} {random_string()}'),
        await tracker.tickets.reply(ticket_id, 'Reply', subject=subject),
        await tracker.tickets.comment(ticket_id, "Comment: doesn't exist, failed, invalid"),
        # descriptions of the transactions of the changes
        await tracker.tickets.edit(ticket_id, Description='first'),
        await tracker.tickets.edit(ticket_id, Description='second'),
        await tracker.tickets.edit(ticket_id, Description=''),
        await tracker.tickets.edit(ticket_id, TimeWorked=30),
        await tracker.tickets.edit(ticket_id, TimeWorked=15),
        await tracker.catalogs.edit(catalog_id, Disabled=1),
        await tracker.catalogs.edit(catalog_id, Disabled=0),
        await tracker.assets.edit(asset_id, HeldBy='root'),
        await tracker.assets.edit(asset_id, HeldBy='Nobody'),
    ):
        assert result
        assert result.complete, result.messages
        result.raise_for_refused()

    # the messages of successful actions, which are checked by the actions themselves
    assert await tracker.tickets.take(ticket_id)
    assert await tracker.tickets.untake(ticket_id)
    assert await tracker.tickets.take(ticket_id)
    assert await tracker.tickets.edit_link(ticket_id, 'RefersTo', other_id)
    assert await tracker.tickets.edit_link(ticket_id, 'RefersTo', other_id, delete=True)
    assert await tracker.tickets.merge(other_id, ticket_id)


# --- permissions ---------------------------------------------------------------------------------------------------


class _Users(typing.NamedTuple):
    """Queue and users with different rights, created by :py:func:`_create_users`."""

    queue: str
    owner: AsyncRt  # privileged, may see, take and own the tickets of the queue
    viewer: AsyncRt  # privileged, may only see the tickets of the queue
    unprivileged: AsyncRt  # unprivileged user without any rights
    owner_name: str


async def _create_users(root: AsyncRt) -> _Users:
    """Create a queue and the users with different rights; the clients of the users must be closed."""
    queue = f'queue-{random_string()}'
    queue_id = await root.queues.create(queue)
    names: dict[str, str] = {}
    clients: dict[str, AsyncRt] = {}

    for role, privileged in (('owner', 1), ('viewer', 1), ('unprivileged', 0)):
        name = f'{role}-{random_string()}'
        await root.users.create(name, f'{name}@example.com', Password=f'password-{name}', Privileged=privileged)
        names[role] = name
        clients[role] = AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(name, f'password-{name}'), http_timeout=None)

    for right in ('SeeQueue', 'ShowTicket', 'OwnTicket', 'TakeTicket'):
        await root.rights.grant('queue', queue_id, right, user=names['owner'])
    for right in ('SeeQueue', 'ShowTicket'):
        await root.rights.grant('queue', queue_id, right, user=names['viewer'])

    return _Users(queue, clients['owner'], clients['viewer'], clients['unprivileged'], names['owner'])


async def _close_users(users: _Users) -> None:
    """Close the clients of the users."""
    await users.owner.aclose()
    await users.viewer.aclose()
    await users.unprivileged.aclose()


async def test_permission_denied(async_rt_connection: AsyncRt):
    """RT denies a permission with HTTP status 403, with HTTP status 400 or with a message; all are NotAllowedError."""
    users = await _create_users(async_rt_connection)
    try:
        ticket_id = await async_rt_connection.tickets.create(users.queue, subject='Permissions', content='Test')
        other_id = await async_rt_connection.tickets.create(users.queue, subject='Permissions', content='Test')

        # a message with HTTP status 200: the user sees the ticket, but may not change it
        edits: list[Request] = [
            ('edit a ticket without the right', lambda: users.viewer.tickets.edit(ticket_id, Subject='Changed')),
            ('edit a user without the right', lambda: users.viewer.users.edit(RT_USER, RealName='Changed')),
        ]
        for description, send_edit in edits:
            result = await send_edit()
            assert result, description
            assert not result.complete, f'{description}: {result.messages!r}'
            _assert_recognized(description, result.refused[0], rt.exceptions.NotAllowedError)
            with pytest.raises(rt.exceptions.NotAllowedError):
                result.raise_for_refused()

        # an exception for the message of RT, which has to be recognized
        cases: list[Case] = [
            ('reply without the right', lambda: users.viewer.tickets.reply(ticket_id, 'Reply'), rt.exceptions.NotAllowedError),
            ('comment without the right', lambda: users.viewer.tickets.comment(ticket_id, 'Comment'), rt.exceptions.NotAllowedError),
            ('reply of an unprivileged user', lambda: users.unprivileged.tickets.reply(ticket_id, 'Reply'), rt.exceptions.NotAllowedError),
            ('merge without the right', lambda: users.viewer.tickets.merge(ticket_id, other_id), rt.exceptions.NotAllowedError),
            ('link without the right', lambda: users.viewer.tickets.edit_link(ticket_id, 'RefersTo', other_id), rt.exceptions.NotAllowedError),
            ('take without the right', lambda: users.viewer.tickets.take(ticket_id), rt.exceptions.InvalidUseError),
        ]
        for description, send_case, expected in cases:
            with pytest.raises(expected) as exc_info:
                await send_case()

            _assert_recognized(description, str(exc_info.value), expected)

        # HTTP status 403 for the unprivileged user
        forbidden: list[Request] = [
            ('get a ticket', lambda: users.unprivileged.tickets.get(ticket_id)),
            ('edit a ticket', lambda: users.unprivileged.tickets.edit(ticket_id, Subject='Changed')),
            ('take a ticket', lambda: users.unprivileged.tickets.take(ticket_id)),
            ('merge tickets', lambda: users.unprivileged.tickets.merge(ticket_id, other_id)),
            ('add a group member', lambda: users.unprivileged.groups.add_member(1, 1)),
        ]
        for description, send_forbidden in forbidden:
            with pytest.raises(rt.exceptions.NotAllowedError) as exc_info:
                await send_forbidden()
            assert exc_info.value.status_code == 403, description

        # nothing was changed by the refused requests
        ticket = await async_rt_connection.tickets.get(ticket_id)
        assert ticket['Subject'] == 'Permissions'
        assert ticket['Owner']['id'] == 'Nobody'
    finally:
        await _close_users(users)


async def test_take_steal_and_untake_of_other_users(async_rt_connection: AsyncRt):
    """The successful actions need a second user: the owner of the ticket."""
    users = await _create_users(async_rt_connection)
    try:
        ticket_id = await async_rt_connection.tickets.create(users.queue, subject='Owners', content='Test')

        assert await users.owner.tickets.take(ticket_id)
        assert (await async_rt_connection.tickets.get(ticket_id))['Owner']['id'] == users.owner_name

        # the user can not untake a ticket owned by somebody else
        with pytest.raises(rt.exceptions.InvalidUseError) as exc_info:
            await async_rt_connection.tickets.untake(ticket_id)
        _assert_recognized('untake a ticket of another user', str(exc_info.value), rt.exceptions.InvalidUseError)
        with pytest.raises(rt.exceptions.InvalidUseError) as exc_info:
            await async_rt_connection.tickets.take(ticket_id)
        _assert_recognized('take a ticket of another user', str(exc_info.value), rt.exceptions.InvalidUseError)

        assert await async_rt_connection.tickets.steal(ticket_id)
        assert (await async_rt_connection.tickets.get(ticket_id))['Owner']['id'] == RT_USER

        assert await async_rt_connection.tickets.untake(ticket_id)
        assert (await async_rt_connection.tickets.get(ticket_id))['Owner']['id'] == 'Nobody'
    finally:
        await _close_users(users)


async def test_values_in_successful_changes_are_no_refusals(async_rt_connection: AsyncRt):
    """The messages for successful changes contain values of users, which must not be recognized as refusals."""
    tracker = async_rt_connection
    hostile = "can't failed invalid does not exist permission denied"
    queue = f'queue-{random_string()}'
    queue_id = await tracker.queues.create(queue)
    multi_id = await tracker.custom_fields.create(f'multi {hostile} {random_string()}', 'Freeform', 'RT::Queue-RT::Ticket', MaxValues=0)
    single_id = await tracker.custom_fields.create(f'single {hostile} {random_string()}', 'Freeform', 'RT::Queue-RT::Ticket', MaxValues=1)
    assert await tracker.custom_fields.apply(multi_id, queue_id)
    assert await tracker.custom_fields.apply(single_id, queue_id)
    ticket_id = await tracker.tickets.create(queue, subject=hostile, content=hostile)
    user_name = f'{hostile} {random_string()}'
    await tracker.users.create(user_name, f'{random_string()}@example.com')
    user_id = int((await tracker.users.get(user_name))['id'])
    group_id = await tracker.groups.create(f'{hostile} {random_string()}')
    url = 'https://example.com/' + hostile.replace(' ', '-')

    for description, send in (
        ('multi value custom field added', lambda: tracker.tickets.edit(ticket_id, CustomFields={str(multi_id): [f'{hostile} a', f'{hostile} b']})),
        ('multi value custom field replaced', lambda: tracker.tickets.edit(ticket_id, CustomFields={str(multi_id): [f'{hostile} b', f'{hostile} c']})),
        ('single value custom field added', lambda: tracker.tickets.edit(ticket_id, CustomFields={str(single_id): hostile})),
        ('single value custom field changed', lambda: tracker.tickets.edit(ticket_id, CustomFields={str(single_id): f'{hostile} 2'})),
        ('single value custom field deleted', lambda: tracker.tickets.edit(ticket_id, CustomFields={str(single_id): None})),
        ('watcher added', lambda: tracker.tickets.edit(ticket_id, Cc=[user_name])),
        ('watcher replaced', lambda: tracker.tickets.edit(ticket_id, Cc=['root'])),
        ('requestor added', lambda: tracker.tickets.edit(ticket_id, Requestor=[f'{random_string()}-failed@example.com'])),
        ('subject changed', lambda: tracker.tickets.edit(ticket_id, Subject=f'{hostile} 2')),
        ('user changed', lambda: tracker.users.edit(user_name, RealName=hostile)),
        ('queue changed', lambda: tracker.queues.edit(queue_id, Description=hostile)),
        ('reply', lambda: tracker.tickets.reply(ticket_id, hostile, subject=hostile, custom_fields={str(multi_id): [hostile]})),
        ('comment', lambda: tracker.tickets.comment(ticket_id, hostile, subject=hostile, custom_fields={str(single_id): hostile})),
    ):
        result = await send()

        assert result, description
        assert result.complete, f'{description}: {result.messages!r}'
        result.raise_for_refused()

    # actions raise an exception for a message of a refusal only
    assert await tracker.groups.add_member(group_id, user_id)
    assert await tracker.tickets.edit_link(ticket_id, 'RefersTo', url)
    assert await tracker.tickets.edit_link(ticket_id, 'RefersTo', url, delete=True)
    assert await tracker.tickets.take(ticket_id)
