"""Python interface to Request Tracker :term:`API`.

Description of Request Tracker :term:`REST` :term:`API`:
https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html
"""

from rt._rest2_async.articles import AsyncArticles, AsyncClasses
from rt._rest2_async.assets import AsyncAssets, AsyncCatalogs
from rt._rest2_async.client import AsyncRt
from rt._rest2_async.custom_fields import AsyncCustomFields, AsyncCustomRoles
from rt._rest2_async.groups import AsyncGroups
from rt._rest2_async.queues import AsyncQueues
from rt._rest2_async.rights import AsyncRights
from rt._rest2_async.tickets import AsyncTickets
from rt._rest2_async.users import AsyncUsers

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

__all__ = [
    'AsyncRt',
    'AsyncTickets',
    'AsyncUsers',
    'AsyncGroups',
    'AsyncQueues',
    'AsyncAssets',
    'AsyncCatalogs',
    'AsyncArticles',
    'AsyncClasses',
    'AsyncCustomFields',
    'AsyncCustomRoles',
    'AsyncRights',
]
