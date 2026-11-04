"""Tests for python-rt / REST2 - Python interface to Request Tracker :term:`API`.

The sync tests (test_tickets.py) are generated from the async tests (test_tickets_async.py) using unasyncd.
"""

# ruff: noqa: S101, S106

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
import json
import typing
import urllib.parse

import httpx2
import pytest

import rt.exceptions
from rt.common import Attachment
from rt.rest2_async import AsyncRt

from . import random_string
from .conftest import RT_CUSTOM_FIELD, RT_CUSTOM_ROLE, RT_PASSWORD, RT_QUEUE, RT_URL, RT_USER, requires_rt_setup


async def test_ticket_attachments(async_rt_connection: AsyncRt):
    """Test various ticket attachment operations."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    attachment_content = b'Content of attachment.'
    attachment_name = 'attachment-name.txt'

    attachment = Attachment(attachment_name, 'text/plain', attachment_content)
    ticket_id = await async_rt_connection.tickets.create(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE, attachments=[attachment])
    assert ticket_id

    att_ids = [item async for item in async_rt_connection.tickets.get_attachments_ids(ticket_id)]
    assert len(att_ids) == 1

    att_list = [item async for item in async_rt_connection.tickets.get_attachments(ticket_id)]
    assert len(att_list) == 1

    att_names = [att['Filename'] for att in att_list]
    assert attachment_name in att_names

    # get the attachment and compare it's content
    att_id = att_list[att_names.index(attachment_name)]['id']
    att_content = base64.b64decode((await async_rt_connection.tickets.get_attachment(att_id))['Content'])
    assert att_content == attachment_content

    # test filter parameters
    att_ids = [item async for item in async_rt_connection.tickets.get_attachments_ids(ticket_id)]
    assert len(att_ids) == 1

    # all parts of the message, not only the file
    att_ids = [item async for item in async_rt_connection.tickets.get_attachments_ids(ticket_id, files_only=False)]
    assert len(att_ids) == 3

    att_ids = [
        item async for item in async_rt_connection.tickets.get_attachments_ids(ticket_id, search_params=[{'field': 'Filename', 'value': 'non-existant.txt'}])
    ]
    assert not att_ids
    att_ids = [
        item async for item in async_rt_connection.tickets.get_attachments_ids(ticket_id, search_params=[{'field': 'Filename', 'value': attachment_name}])
    ]
    assert len(att_ids) == 1


async def test_ticket_take(async_rt_connection: AsyncRt):
    """Test take/untake."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'

    ticket_id = await async_rt_connection.tickets.create(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id

    assert (await async_rt_connection.tickets.take(ticket_id)).complete
    with pytest.raises(rt.exceptions.InvalidUseError, match='already owns'):
        await async_rt_connection.tickets.take(ticket_id)

    assert (await async_rt_connection.tickets.untake(ticket_id)).complete

    # RT only steals tickets owned by another user, the ticket is owned by Nobody now
    with pytest.raises(rt.exceptions.InvalidUseError, match='someone else'):
        await async_rt_connection.tickets.steal(ticket_id)


# --- fields of replies and comments ----------------------------------------------------------------------------------


async def test_reply_and_comment_fields(async_rt_connection: AsyncRt):
    queue_name = f'queue-{random_string()}'
    queue_id = await async_rt_connection.queues.create(queue_name)
    txn_field = f'cf-{random_string()}'
    txn_field_id = await async_rt_connection.custom_fields.create(txn_field, 'Freeform', 'RT::Queue-RT::Ticket-RT::Transaction', MaxValues=1)
    await async_rt_connection.custom_fields.apply(txn_field_id, queue_id)
    ticket_id = await async_rt_connection.tickets.create(queue_name, subject='Fields of replies', content='Test')

    assert (await async_rt_connection.tickets.reply(ticket_id, 'Reply', subject='Other subject', time_taken=5, status='stalled')).complete
    assert (await async_rt_connection.tickets.comment(ticket_id, 'Comment', time_taken=3, txn_custom_fields={txn_field: 'value'})).complete

    ticket = await async_rt_connection.tickets.get(ticket_id)
    assert ticket['Status'] == 'stalled'
    assert ticket['TimeWorked'] == '8'
    history = [item async for item in async_rt_connection.tickets.history(ticket_id)]
    assert [item['Type'] for item in history].count('Correspond') == 1


async def test_reply_invalid_status(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Invalid status', content='Test')

    # RT adds the reply and reports the refused status only in a message; the result is true as the reply was added
    result = await async_rt_connection.tickets.reply(ticket_id, 'Reply', status='invalid')
    assert result
    assert not result.complete
    assert "Status 'invalid' isn't a valid status for this ticket." in result.refused
    assert result.messages[0] == 'Correspondence added'

    assert (await async_rt_connection.tickets.get(ticket_id))['Status'] != 'invalid'
    assert [item['Type'] for item in [i async for i in async_rt_connection.tickets.history(ticket_id)]].count('Correspond') == 1


@requires_rt_setup
async def test_comment_custom_fields_and_roles(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Custom fields of comments', content='Test')
    value = f"it's {random_string()}"

    assert (
        await async_rt_connection.tickets.comment(ticket_id, 'Comment', custom_fields={RT_CUSTOM_FIELD: value}, custom_roles={RT_CUSTOM_ROLE: RT_USER})
    ).complete
    ticket = await async_rt_connection.tickets.get(ticket_id)
    assert [field['values'] for field in ticket['CustomFields'] if field['name'] == RT_CUSTOM_FIELD] == [[value]]
    assert ticket['CustomRoles'][RT_CUSTOM_ROLE]['id'] == RT_USER


async def test_reply_fields_are_only_sent_if_specified():
    bodies: list[dict[str, typing.Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.headers['Content-Type'].startswith('multipart/form-data'):
            # the JSON is sent in the form field JSON together with the attachments
            content = request.content.decode(errors='replace')
            bodies.append(json.loads(content.split('name="JSON"', 1)[1].split('\r\n\r\n', 1)[1].split('\r\n--', 1)[0]))
        else:
            bodies.append(json.loads(request.content))
        return httpx2.Response(201, json=['Correspondence added'])

    async with AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as tracker:
        await tracker.tickets.reply(1, 'Text')
        await tracker.tickets.comment(1, 'Text', status='resolved', custom_fields={'Severity': 'High'}, txn_custom_fields={'Notes': 'x'})
        await tracker.tickets.reply(
            1, 'Text', attachments=[Attachment('a.txt', 'text/plain', b'a')], subject='Subject', time_taken=0, custom_roles={'Manager': ['alice', 'bob']}
        )

    assert bodies == [
        {'Content': 'Text', 'ContentType': 'text/plain'},
        {'Status': 'resolved', 'CustomFields': {'Severity': 'High'}, 'TxnCustomFields': {'Notes': 'x'}, 'Content': 'Text', 'ContentType': 'text/plain'},
        {'Subject': 'Subject', 'TimeTaken': 0, 'CustomRoles': {'Manager': ['alice', 'bob']}, 'Content': 'Text', 'ContentType': 'text/plain'},
    ]


# --- messages and transactions -------------------------------------------------------------------------------------


async def test_get_ticket_messages(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Messages', content='Initial text')
    await async_rt_connection.tickets.reply(ticket_id, '<p>HTML <b>reply</b></p>', content_type='text/html')
    await async_rt_connection.tickets.comment(ticket_id, 'Comment with file', attachments=[Attachment('a.txt', 'text/plain', b'file content')], time_taken=7)
    await async_rt_connection.tickets.comment(ticket_id, attachments=[Attachment('only.bin', 'application/octet-stream', b'\x00\x01')])
    # no message
    await async_rt_connection.tickets.edit(ticket_id, Subject='Messages changed')

    messages = [message async for message in async_rt_connection.tickets.messages(ticket_id)]

    assert [message['Type'] for message in messages] == ['Create', 'Correspond', 'Comment', 'Comment']
    assert messages[0]['Content'] == 'Initial text'
    # RT converts HTML to plain text
    assert messages[1]['Content'].strip() == 'HTML reply'
    # attachments are not part of the content
    assert messages[2]['Content'] == 'Comment with file'
    assert messages[2]['TimeTaken'] == '7'
    assert messages[3]['Content'] == ''
    assert all(message['Creator']['Name'] == RT_USER for message in messages)
    assert all('EmailAddress' in message['Creator'] for message in messages)
    assert [int(message['id']) for message in messages] == sorted(int(message['id']) for message in messages)

    # the history (all transactions) and single transactions are still available
    history = [item async for item in async_rt_connection.tickets.history(ticket_id)]
    assert {item['id'] for item in history} > {message['id'] for message in messages}
    transaction = await async_rt_connection.tickets.get_transaction(messages[2]['id'])
    assert transaction['Type'] == 'Comment'


async def test_get_ticket_messages_all_pages(async_rt_connection: AsyncRt):
    # not '0', which RT (Perl) takes as no content
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Many messages', content='message 0')
    for number in range(1, 5):
        await async_rt_connection.tickets.comment(ticket_id, f'message {number}')

    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(RT_USER, RT_PASSWORD), http_timeout=None, per_page=2) as tracker:
        contents = [message['Content'] async for message in tracker.tickets.messages(ticket_id)]

    assert contents == [f'message {number}' for number in range(5)]


async def test_get_ticket_messages_unknown_ticket(async_rt_connection: AsyncRt):
    assert [message async for message in async_rt_connection.tickets.messages(999999)] == []


async def test_search_transactions(async_rt_connection: AsyncRt):
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Search transactions', content='Initial text')
    await async_rt_connection.tickets.comment(ticket_id, 'first')
    await async_rt_connection.tickets.comment(ticket_id, 'second')
    await async_rt_connection.tickets.reply(ticket_id, 'reply')

    by_conditions = [
        (item['Type'], item['Content'])
        async for item in async_rt_connection.tickets.search_transactions(
            search_params=[{'field': 'ObjectId', 'value': ticket_id}, {'field': 'ObjectType', 'value': 'RT::Ticket'}, {'field': 'Type', 'value': 'Comment'}],
            fields=['Type', 'Content'],
            order='id',
        )
    ]
    assert by_conditions == [('Comment', 'first'), ('Comment', 'second')]

    by_query = [
        item['Content']
        async for item in async_rt_connection.tickets.search_transactions(
            raw_query=f"ObjectType = 'RT::Ticket' AND ObjectId = {ticket_id} AND (Type = 'Comment' OR Type = 'Correspond')",
            fields='Content',
            order='-id',
        )
    ]
    assert by_query == ['reply', 'second', 'first']

    default_fields = [item async for item in async_rt_connection.tickets.search_transactions(search_params=[{'field': 'ObjectId', 'value': ticket_id}])]
    assert {'Type', 'Created', 'Creator', 'ObjectType', 'ObjectId'} <= set(default_fields[0])

    with pytest.raises(rt.exceptions.BadRequestError):
        [item async for item in async_rt_connection.tickets.search_transactions(raw_query='Invalid ==== 1')]


async def test_search_transactions_request():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={'page': 1, 'per_page': 100, 'pages': 0, 'total': 0, 'count': 0, 'items': []})

    async with AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as tracker:
        [item async for item in tracker.tickets.search_transactions(raw_query="Type = 'Comment'", order='-Created')]
        [item async for item in tracker.tickets.search_transactions(search_params=[{'field': 'Type', 'value': 'Comment'}])]

    sql_request, json_request = requests
    assert sql_request.method == 'POST'
    assert urllib.parse.parse_qs(sql_request.content.decode()) == {'query': ["Type = 'Comment'"]}
    assert sql_request.url.params['orderby'] == 'Created'
    assert sql_request.url.params['order'] == 'DESC'
    assert json.loads(json_request.content) == [{'field': 'Type', 'value': 'Comment'}]


@pytest.mark.parametrize(
    'arguments',
    [
        {},
        {'search_params': [], 'raw_query': "Type = 'Comment'"},
        {'raw_query': ''},
        {'raw_query': '  '},
    ],
)
async def test_search_transactions_invalid_use(arguments: dict[str, typing.Any]):
    def no_request(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError('no request must be sent')

    async with AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(no_request))) as tracker:
        with pytest.raises(rt.exceptions.InvalidUseError):
            [item async for item in tracker.tickets.search_transactions(**arguments)]


# --- attachment search ---------------------------------------------------------------------------------------------


async def test_search_attachments(async_rt_connection: AsyncRt):
    prefix = f'search-{random_string()}'
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Attachment search', content='Test')
    await async_rt_connection.tickets.comment(
        ticket_id,
        'Files',
        attachments=[Attachment(f'{prefix}-a.pdf', 'application/pdf', b'%PDF-1.4'), Attachment(f'{prefix}-b.txt', 'text/plain', b'text')],
    )
    await async_rt_connection.tickets.comment(ticket_id, 'Another file', attachments=[Attachment(f'{prefix}-c.txt', 'text/plain', b'more')])
    by_prefix = [{'field': 'Filename', 'operator': 'LIKE', 'value': prefix}]

    found = [item async for item in async_rt_connection.tickets.search_attachments(search_params=by_prefix)]
    assert sorted(item['Filename'] for item in found) == [f'{prefix}-a.pdf', f'{prefix}-b.txt', f'{prefix}-c.txt']
    assert {'Filename', 'ContentType', 'ContentLength', 'TransactionId', 'Created'} <= set(found[0])

    pdfs = [
        item['Filename']
        async for item in async_rt_connection.tickets.search_attachments(search_params=[*by_prefix, {'field': 'ContentType', 'value': 'application/pdf'}])
    ]
    assert pdfs == [f'{prefix}-a.pdf']

    # conditions on the file name stay combined with OR, although only files are returned
    either = [{'field': 'Filename', 'value': f'{prefix}-a.pdf'}, {'field': 'Filename', 'value': f'{prefix}-c.txt'}]
    assert sorted([item['Filename'] async for item in async_rt_connection.tickets.search_attachments(search_params=either)]) == [
        f'{prefix}-a.pdf',
        f'{prefix}-c.txt',
    ]

    # the files of a single comment, with search_attachments and with get_attachments
    transaction_id = next(item['TransactionId'] for item in found if item['Filename'] == f'{prefix}-c.txt')
    of_transaction = [{'field': 'TransactionId', 'value': transaction_id}]
    assert [item['Filename'] async for item in async_rt_connection.tickets.search_attachments(search_params=of_transaction)] == [f'{prefix}-c.txt']
    assert [item['Filename'] async for item in async_rt_connection.tickets.get_attachments(ticket_id, search_params=of_transaction)] == [f'{prefix}-c.txt']

    # all parts of the message: the container, the text of the message and the file
    parts = [item async for item in async_rt_connection.tickets.search_attachments(search_params=of_transaction, files_only=False)]
    assert len(parts) == 3
    assert sorted(item['Filename'] for item in parts) == ['', '', f'{prefix}-c.txt']


async def test_search_attachments_rights(async_rt_connection: AsyncRt):
    prefix = f'rights-{random_string()}'
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Attachment rights', content='Test')
    await async_rt_connection.tickets.comment(ticket_id, 'File', attachments=[Attachment(f'{prefix}.txt', 'text/plain', b'secret')])
    user_name = f'user-{random_string()}'
    await async_rt_connection.users.create(user_name, f'{user_name}@example.com', Password='password-of-test-user', Privileged=1)
    condition = [{'field': 'Filename', 'value': f'{prefix}.txt'}]

    assert len([item async for item in async_rt_connection.tickets.search_attachments(search_params=condition)]) == 1
    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(user_name, 'password-of-test-user'), http_timeout=None) as tracker:
        assert [item async for item in tracker.tickets.search_attachments(search_params=condition)] == []


async def test_get_attachments_of_ticket_not_found_or_hidden(async_rt_connection: AsyncRt):
    # RT searches the attachments of all tickets if the ticket does not exist or the user may not see it
    prefix = f'hidden-{random_string()}'
    ticket_id = await async_rt_connection.tickets.create(RT_QUEUE, subject='Hidden attachments', content='Test')
    await async_rt_connection.tickets.comment(ticket_id, 'File', attachments=[Attachment(f'{prefix}.txt', 'text/plain', b'secret')])
    condition = [{'field': 'Filename', 'value': f'{prefix}.txt'}]

    with pytest.raises(rt.exceptions.NotFoundError):
        _ = [item async for item in async_rt_connection.tickets.get_attachments(999999999, search_params=condition)]
    with pytest.raises(rt.exceptions.NotFoundError):
        _ = [item async for item in async_rt_connection.tickets.get_attachments_ids(999999999, search_params=condition)]

    user_name = f'user-{random_string()}'
    await async_rt_connection.users.create(user_name, f'{user_name}@example.com', Password='password-of-test-user', Privileged=1)
    async with AsyncRt(url=RT_URL, http_auth=httpx2.BasicAuth(user_name, 'password-of-test-user'), http_timeout=None) as tracker:
        with pytest.raises(rt.exceptions.NotAllowedError):
            _ = [item async for item in tracker.tickets.get_attachments(ticket_id, search_params=condition)]


async def test_search_attachments_conditions():
    conditions: list[typing.Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        conditions.append(json.loads(request.content))
        return httpx2.Response(200, json={'page': 1, 'per_page': 100, 'pages': 0, 'total': 0, 'count': 0, 'items': []})

    files_only = {'field': 'Filename', 'operator': 'IS NOT', 'value': '', 'entry_aggregator': 'AND'}
    search_params = [{'field': 'Filename', 'value': 'a.pdf'}]
    async with AsyncRt(url=RT_URL, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as tracker:
        [item async for item in tracker.tickets.search_attachments()]
        [item async for item in tracker.tickets.search_attachments(search_params=search_params)]
        [item async for item in tracker.tickets.search_attachments(files_only=False)]
        [item async for item in tracker.tickets.search_attachments(search_params=search_params, files_only=False)]

    assert conditions == [
        [files_only],
        [{'field': 'Filename', 'value': 'a.pdf'}, files_only],
        [{'field': 'id', 'operator': '>', 'value': 0}],
        [{'field': 'Filename', 'value': 'a.pdf'}],
    ]
    # the list passed by the caller is not modified
    assert search_params == [{'field': 'Filename', 'value': 'a.pdf'}]
