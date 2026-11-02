"""Tests for python-rt / REST2 - Python interface to Request Tracker :term:`API`.

The sync tests (test_basic.py) are generated from the async tests (test_basic_async.py) using unasyncd.
"""

# ruff: noqa: S101, S105, S311

__license__ = """ Copyright (C) 2013 CZ.NIC, z.s.p.o.
    Copyright (c) 2021 CERT Gouvernemental (GOVCERT.LU)

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
    '"Georges Toth" <georges.toth@govcert.etat.lu>',
]

import base64
import random
import string

import httpx2
import pytest

import rt.exceptions
from rt.common import Attachment
from rt.rest2_async import AsyncRt

from . import random_string

RT_URL = 'http://localhost:8080/REST/2.0/'
RT_USER = 'root'
RT_PASSWORD = 'password'
RT_QUEUE = 'General'


async def test_get_user(async_rt_connection: AsyncRt):
    user = await async_rt_connection.get_user(RT_USER)
    assert user['Name'] == RT_USER
    assert '@' in user['EmailAddress']
    assert user['Privileged'] == 1


async def test_invalid_api_url():
    with pytest.raises(ValueError):
        AsyncRt(url='https://example.com', http_auth=httpx2.BasicAuth('dummy', 'dummy'))


async def test_ticket_operations(async_rt_connection: AsyncRt):
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    # empty search result
    search_result = [item async for item in async_rt_connection.search(Subject=ticket_subject)]
    assert not search_result

    # create
    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id > -1

    # search
    search_result = [item async for item in async_rt_connection.search(Subject=ticket_subject)]
    assert len(search_result) == 1
    assert search_result[0]['id'] == str(ticket_id)
    assert search_result[0]['Status'] == 'new'

    # search with a list of fields
    search_result = [item async for item in async_rt_connection.search(Subject=ticket_subject, fields=['Status', 'Subject'])]
    assert len(search_result) == 1
    assert search_result[0]['Subject'] == str(ticket_subject)
    assert search_result[0]['Status'] == 'new'
    assert 'Requestor' not in search_result[0].keys()

    # search with a dictionary of field parameters
    search_result = [item async for item in async_rt_connection.search(Subject=ticket_subject, fields={'fields': 'Owner', 'fields[Owner]': 'Name'})]
    assert len(search_result) == 1
    assert 'Subject' not in search_result[0]
    assert 'Status' not in search_result[0]
    assert search_result[0]['Owner']['Name'] == 'Nobody'

    # raw search
    search_result = [item async for item in async_rt_connection.search(raw_query=f'Subject="{ticket_subject}"')]
    assert len(search_result) == 1
    assert search_result[0]['id'] == str(ticket_id)
    assert search_result[0]['Status'] == 'new'

    # get ticket
    ticket = await async_rt_connection.get_ticket(ticket_id)
    search_result[0]['id'] = int(search_result[0]['id'])

    for k in search_result[0]:
        if k.startswith('_') or k in ('type', 'CustomFields'):
            continue

        assert k in ticket
        assert ticket[k] == search_result[0][k]

    # edit ticket
    requestors = ['tester1@example.com', 'tester2@example.com']
    await async_rt_connection.edit_ticket(ticket_id, Status='open', Requestor=requestors)

    # get ticket (edited)
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert ticket['Status'] == 'open'
    for requestor in ticket['Requestor']:
        assert requestor['id'] in requestors
    for requestor in requestors:
        found = False
        for _requestor in ticket['Requestor']:
            if _requestor['id'] == requestor:
                found = True
                break

        assert found

    # get history
    hist = [item async for item in async_rt_connection.get_ticket_history(ticket_id)]
    assert len(hist) > 0
    transaction = await async_rt_connection.get_transaction(hist[0]['id'])
    found = False
    for hyperlink in transaction['_hyperlinks']:
        if hyperlink['ref'] == 'attachment':
            attachment_id = hyperlink['_url'].rsplit('/', 1)[1]
            attachment_text = base64.b64decode((await async_rt_connection.get_attachment(attachment_id))['Content']).decode('utf-8')
            found = True
            assert attachment_text == ticket_text
            break

    assert found

    # get_short_history
    short_hist = [item async for item in async_rt_connection.get_ticket_history(ticket_id)]
    assert len(short_hist) > 0
    assert short_hist[0]['Type'] == 'Create'
    assert short_hist[0]['Creator']['Name'] == RT_USER

    # create 2nd ticket
    ticket2_subject = 'Testing issue ' + ''.join([random.choice(string.ascii_letters) for i in range(15)])
    ticket2_id = await async_rt_connection.create_ticket(queue=RT_QUEUE, subject=ticket2_subject)
    assert ticket2_id > -1

    # edit link
    assert await async_rt_connection.edit_link(ticket_id, 'DependsOn', ticket2_id) == [f'Ticket {ticket_id} depends on Ticket {ticket2_id}.']

    # get links
    links1 = await async_rt_connection.get_links(ticket_id)
    found = False
    for link in links1:
        if link['ref'] == 'depends-on' and link['id'] == str(ticket2_id):
            found = True
    assert found

    links2 = await async_rt_connection.get_links(ticket2_id)
    found = False
    for link in links2:
        if link['ref'] == 'depended-on-by' and link['id'] == str(ticket_id):
            found = True
    assert found

    # delete link
    assert await async_rt_connection.edit_link(ticket_id, 'DependsOn', ticket2_id, delete=True) == [
        f'Ticket {ticket_id} no longer depends on Ticket {ticket2_id}.'
    ]
    assert not [link for link in await async_rt_connection.get_links(ticket_id) if link['ref'] == 'depends-on']

    # link to a ticket which does not exist
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_link(ticket_id, 'DependsOn', 999999999)

    # link which RT does not create
    with pytest.raises(rt.exceptions.InvalidUseError, match='itself'):
        await async_rt_connection.edit_link(ticket_id, 'DependsOn', ticket_id)

    # reply with attachment
    attachment_content = b'Content of attachment.'
    attachment_name = 'attachment-name.txt'
    reply_text = 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.'
    attachment = Attachment(attachment_name, 'text/plain', attachment_content)
    assert await async_rt_connection.reply(ticket_id, content=reply_text, attachments=[attachment]) == ['Correspondence added']

    # reply with a comment
    reply_text = 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.'
    assert await async_rt_connection.comment(ticket_id, content=reply_text) == ['Comments added']

    # reply with a html content
    reply_text = '<em>Ut enim ad minim veniam</em>, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.'
    assert await async_rt_connection.reply(ticket_id, content=reply_text, content_type='text/html') == ['Correspondence added']

    # attachments list
    at_list = [item async for item in async_rt_connection.get_attachments(ticket_id)]
    assert at_list
    at_names = [at['Filename'] for at in at_list]
    assert attachment_name in at_names
    # get the attachment and compare it's content
    at_id = at_list[at_names.index(attachment_name)]['id']
    at_content = base64.b64decode((await async_rt_connection.get_attachment(at_id))['Content'])
    assert at_content == attachment_content

    # set invalid user
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_ticket(ticket_id, Owner='invalid_user')

    # set invalid queue
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_ticket(ticket_id, Queue='invalid_queue')

    # edit invalid ticket
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.edit_ticket(999999999, Owner='Nobody')

    # merge tickets
    with pytest.raises(rt.exceptions.InvalidUseError, match='itself'):
        await async_rt_connection.merge_ticket(ticket_id, ticket_id)
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.merge_ticket(ticket2_id, 999999999)
    assert await async_rt_connection.merge_ticket(ticket2_id, ticket_id) == ['Merge Successful']

    # delete ticket
    await async_rt_connection.delete_ticket(ticket_id)

    # delete invalid ticket
    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.delete_ticket(999999999)


async def test_attachments_create(async_rt_connection: AsyncRt):
    """Create a ticket with a random (>= 2) number of attachments and verify that they have been successfully added to the ticket."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    attachment_count = random.randint(2, 10)
    attachments = []
    for _i in range(attachment_count):
        attachment_content = random_string(length=100).encode()
        attachment_name = f'attachment-{random_string(length=10)}.txt'
        attachments.append(Attachment(attachment_name, 'text/plain', attachment_content))

    # create
    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE, attachments=attachments)
    assert ticket_id > -1

    # get ticket
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert int(ticket['id']) == ticket_id

    # attachments list
    at_list = [item async for item in async_rt_connection.get_attachments(ticket_id)]
    assert at_list
    assert len(at_list) == len(attachments)
    at_names = [at['Filename'] for at in at_list]
    for k in attachments:
        assert k.file_name in at_names

        # get the attachment and compare it's content
        at_id = at_list[at_names.index(k.file_name)]['id']
        at_content = base64.b64decode((await async_rt_connection.get_attachment(at_id))['Content'])
        assert at_content == k.file_content


async def test_attachments_search(async_rt_connection: AsyncRt):
    """Create a ticket with an attachments and verify that attachment search and filtering works correctly."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    attachment_content = random_string(length=100).encode()
    attachment_name = f'attachment-{random_string(length=10)}.txt'
    attachment = Attachment(attachment_name, 'text/plain', attachment_content)

    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE, attachments=[attachment])

    at_list = [item async for item in async_rt_connection.get_attachments(ticket_id, fields=['TransactionId', 'Headers'])]
    assert at_list
    assert len(at_list) == 1

    assert at_list[0]['TransactionId']
    assert at_list[0]['Headers']


async def test_attachments_comment(async_rt_connection: AsyncRt):
    """Create a ticket and comment to it with a random (>= 2) number of attachments and verify that they have been successfully added to the ticket."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    # create
    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id > -1

    attachment_count = random.randint(2, 10)
    attachments = []
    for _i in range(attachment_count):
        attachment_content = random_string(length=100).encode()
        attachment_name = f'attachment-{random_string(length=10)}.txt'
        attachments.append(Attachment(attachment_name, 'text/plain', attachment_content))

    # comment with attachments
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    comment_success = await async_rt_connection.comment(ticket_id=ticket_id, content=ticket_text, attachments=attachments)
    assert comment_success

    # attachments list
    at_list = [item async for item in async_rt_connection.get_attachments(ticket_id)]
    assert at_list
    assert len(at_list) == len(attachments)
    at_names = [at['Filename'] for at in at_list]
    for k in attachments:
        assert k.file_name in at_names

        # get the attachment and compare it's content
        at_id = at_list[at_names.index(k.file_name)]['id']
        at_content = base64.b64decode((await async_rt_connection.get_attachment(at_id))['Content'])
        assert at_content == k.file_content


async def test_attachments_reply(async_rt_connection: AsyncRt):
    """Create a ticket and reply to it with a random (>= 2) number of attachments and verify that they have been successfully added to the ticket."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    # create
    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id > -1

    attachment_count = random.randint(2, 10)
    attachments = []
    for _i in range(attachment_count):
        attachment_content = random_string(length=100).encode()
        attachment_name = f'attachment-{random_string(length=10)}.txt'
        attachments.append(Attachment(attachment_name, 'text/plain', attachment_content))

    # comment with attachments
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    comment_success = await async_rt_connection.reply(ticket_id=ticket_id, content=ticket_text, attachments=attachments)
    assert comment_success

    # attachments list
    at_list = [item async for item in async_rt_connection.get_attachments(ticket_id)]
    assert at_list
    assert len(at_list) == len(attachments)
    at_names = [at['Filename'] for at in at_list]
    for k in attachments:
        assert k.file_name in at_names

        # get the attachment and compare it's content
        at_id = at_list[at_names.index(k.file_name)]['id']
        at_content = base64.b64decode((await async_rt_connection.get_attachment(at_id))['Content'])
        assert at_content == k.file_content


async def test_ticket_operations_admincc_cc(async_rt_connection: AsyncRt):
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    def compare_list(from_list: list[str], ticket_list: list[dict]) -> bool:
        """Lists (Requestor, AdminCc, Cc) returned from REST2 contain a list of dicts with additional user information.

        Thus a simple compare of both lists is not enough.
        """
        if len(from_list) != len(ticket_list):
            return False

        to_list = [entry['id'] for entry in ticket_list]
        diff = set(from_list) ^ set(to_list)

        return not diff

    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id > -1

    # make sure Requestor, AdminCc and Cc are present and an empty list, as would be expected
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert len(ticket['Requestor']) >= 0
    assert len(ticket['AdminCc']) >= 0
    assert len(ticket['Cc']) >= 0

    # set requestors
    requestors = ['tester1@example.com', 'tester2@example.com']
    await async_rt_connection.edit_ticket(ticket_id, Status='open', Requestor=requestors)
    # verify
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert compare_list(requestors, ticket['Requestor'])

    # set admincc
    admincc = ['tester2@example.com', 'tester3@example.com']
    await async_rt_connection.edit_ticket(ticket_id, Status='open', AdminCc=admincc)
    # verify
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert compare_list(requestors, ticket['Requestor'])
    assert compare_list(admincc, ticket['AdminCc'])

    # update admincc
    admincc = ['tester2@example.com', 'tester3@example.com', 'tester4@example.com']
    await async_rt_connection.edit_ticket(ticket_id, Status='open', AdminCc=admincc)
    # verify
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert compare_list(requestors, ticket['Requestor'])
    assert compare_list(admincc, ticket['AdminCc'])

    # unset requestors and admincc
    requestors = []
    admincc = []
    await async_rt_connection.edit_ticket(ticket_id, Status='open', Requestor=requestors, AdminCc=admincc)
    # verify
    ticket = await async_rt_connection.get_ticket(ticket_id)
    assert compare_list(requestors, ticket['Requestor'])
    assert compare_list(admincc, ticket['AdminCc'])


async def test_users(async_rt_connection: AsyncRt):
    assert await async_rt_connection.get_user('tester1@example.com') is not None
    assert await async_rt_connection.user_exists('root', privileged=True) is True
    assert await async_rt_connection.user_exists('tester1@example.com', privileged=False) is True
    assert await async_rt_connection.user_exists('tester1@example.com', privileged=True) is False
    assert await async_rt_connection.user_exists('does-not-exist@example.com', privileged=False) is False

    random_user_name = f'username_{random_string()}'
    random_user_email = f'user-{random_string()}@example.com'
    random_user_password = f'user_password-{random_string()}'

    assert await async_rt_connection.create_user(random_user_name, random_user_email, Password=random_user_password) == random_user_name
    await async_rt_connection.delete_user(random_user_name)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.delete_user(f'username_{random_string()}')

    assert await async_rt_connection.edit_user(user_id=random_user_name, RealName=random_user_name)


async def test_queues(async_rt_connection: AsyncRt):
    queue = await async_rt_connection.get_queue(RT_QUEUE)
    assert queue['Name'] == RT_QUEUE

    queues = [item async for item in async_rt_connection.get_all_queues()]
    assert len(queues) >= 1

    found = False
    for q in queues:
        if q['Name'] == RT_QUEUE:
            found = True
    assert found

    random_queue_name = f'Queue {random_string()}'
    random_queue_email = f'q-{random_string()}@example.com'

    await async_rt_connection.create_queue(random_queue_name, CorrespondAddress=random_queue_email, Description='test queue')
    queues = [item async for item in async_rt_connection.get_all_queues()]
    found = False
    for q in queues:
        if q['Name'] == random_queue_name:
            found = True
    assert found

    await async_rt_connection.edit_queue(random_queue_name, Disabled='1')
    assert (await async_rt_connection.get_queue(random_queue_name))['Disabled'] == '1'

    await async_rt_connection.edit_queue(random_queue_name, Disabled='0')
    assert (await async_rt_connection.get_queue(random_queue_name))['Disabled'] == '0'

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.get_queue('InvalidName')

    await async_rt_connection.delete_queue(random_queue_name)

    with pytest.raises(rt.exceptions.NotFoundError):
        await async_rt_connection.delete_queue(f'Queue {random_string()}')


async def test_catalog(async_rt_connection: AsyncRt):
    catalog = await async_rt_connection.get_catalog(1)
    assert catalog['id'] == 1


async def test_assets(async_rt_connection: AsyncRt):
    asset_name = random_string()
    asset_name_new = random_string()

    asset_id = await async_rt_connection.create_asset(asset_name, 1, Creator='root')
    assert asset_id

    asset = await async_rt_connection.get_asset(asset_id)
    assert asset['id'] == asset_id

    asset_history = [item async for item in async_rt_connection.get_asset_history(asset_id)]
    assert len(asset_history) == 1

    asset_edited = await async_rt_connection.edit_asset(asset_id, Name=asset_name_new)
    assert asset_edited == [f"Asset {asset_id}: Name changed from '{asset_name}' to '{asset_name_new}'"]

    search = async_rt_connection.search_assets(catalog_id=1, search_params=[{'field': 'Name', 'value': asset_name_new}])
    items = [item async for item in search]
    assert len(items) == 1
    assert items[0]['Status'] == 'new'

    search = async_rt_connection.search_assets(catalog_id=1, search_params=[{'field': 'Name', 'value': asset_name_new}], fields='Owner')
    items = [item async for item in search]
    assert len(items) == 1
    assert items[0]['Owner']['id'] == 'Nobody'
    assert 'Status' not in items[0]

    search = async_rt_connection.search_assets(catalog_id=1, search_params=[{'field': 'Name', 'value': asset_name_new}], fields=['Owner'])
    items = [item async for item in search]
    assert len(items) == 1
    assert items[0]['Owner']['id'] == 'Nobody'
    assert 'Status' not in items[0]

    search = async_rt_connection.search_assets()
    items = [item async for item in search]
    assert items

    search = async_rt_connection.search_assets(
        catalog_id=1, search_params=[{'field': 'Name', 'value': asset_name_new}], fields={'fields': 'Owner', 'fields[Owner]': 'Name'}
    )
    items = [item async for item in search]
    assert len(items) == 1
    assert items[0]['Owner']['Name'] == 'Nobody'
    assert 'Status' not in items[0]
