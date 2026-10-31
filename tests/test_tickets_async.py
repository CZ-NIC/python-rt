"""Tests for python-rt / REST2 - Python interface to Request Tracker :term:`API`.

The sync tests (test_tickets.py) are generated from the async tests (test_tickets_async.py) using unasyncd.
"""

# ruff: noqa: S101

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

from rt.common import Attachment
from rt.rest2_async import AsyncRt

from . import random_string
from .conftest import RT_QUEUE


async def test_ticket_attachments(async_rt_connection: AsyncRt):
    """Test various ticket attachment operations."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = (
        'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    )
    attachment_content = b'Content of attachment.'
    attachment_name = 'attachment-name.txt'

    attachment = Attachment(attachment_name, 'text/plain', attachment_content)
    ticket_id = await async_rt_connection.create_ticket(
        subject=ticket_subject, content=ticket_text, queue=RT_QUEUE, attachments=[attachment]
    )
    assert ticket_id

    att_ids = [item async for item in async_rt_connection.get_attachments_ids(ticket_id)]
    assert len(att_ids) == 1

    att_list = [item async for item in async_rt_connection.get_attachments(ticket_id)]
    assert len(att_list) == 1

    att_names = [att['Filename'] for att in att_list]
    assert attachment_name in att_names

    # get the attachment and compare it's content
    att_id = att_list[att_names.index(attachment_name)]['id']
    att_content = base64.b64decode((await async_rt_connection.get_attachment(att_id))['Content'])
    assert att_content == attachment_content

    # test filter parameter
    att_ids = [item async for item in async_rt_connection.get_attachments_ids(ticket_id, query_filter=None)]
    assert len(att_ids) == 1

    att_ids = [item async for item in async_rt_connection.get_attachments_ids(ticket_id, query_filter=[])]
    assert len(att_ids) == 3

    att_ids = [
        item
        async for item in async_rt_connection.get_attachments_ids(
            ticket_id, query_filter=[{'field': 'Filename', 'value': 'non-existant.txt'}]
        )
    ]
    assert not att_ids


async def test_ticket_take(async_rt_connection: AsyncRt):
    """Test take/untake."""
    ticket_subject = f'Testing issue {random_string()}'
    ticket_text = (
        'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    )

    ticket_id = await async_rt_connection.create_ticket(subject=ticket_subject, content=ticket_text, queue=RT_QUEUE)
    assert ticket_id

    assert await async_rt_connection.take(ticket_id)
    assert await async_rt_connection.untake(ticket_id)
