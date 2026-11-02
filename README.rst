.. image:: https://github.com/python-rt/python-rt/actions/workflows/test_lint.yml/badge.svg
    :target: https://github.com/python-rt/python-rt/actions/workflows/test_lint.yml
    :alt: tests
.. image:: https://readthedocs.org/projects/python-rt/badge/?version=stable
    :target: https://python-rt.readthedocs.io/en/stable/?badge=stable
    :alt: Documentation Status
.. image:: https://badge.fury.io/py/rt.svg
    :target: https://badge.fury.io/py/rt

==============================================
 Rt - Python interface to Request Tracker API
==============================================

Python implementation of REST API described here:
 - https://rt-wiki.bestpractical.com/wiki/REST
 - https://docs.bestpractical.com/rt/6.0.4/RT/REST2.html

.. csv-table:: Python version compatibility:
   :header: "Python", "rt"
   :widths: 15, 15

   "2.7", "< 2.0.0"
   ">= 3.5, <3.7", ">= 2.0.0, < 3.0.0"
   ">= 3.7", ">= 3.0.0, < 3.1.0"
   ">= 3.8", ">= 3.0.0, < 3.3.0"
   ">= 3.9", ">= 3.3.0, < 3.7.0"
   ">= 3.10", ">= 3.7.0, <= 3.8.1"
   ">= 3.11", "> 3.8.1"

ℹ️ **Note**:
    Please note that starting with the next release after v3.8.1, this library requires Python version >= 3.11.
    See the *Python version compatibility* table above for more detailed information.

⚡ **Note**:
    As of version 3.1.0, this library is async compatible.
    Usage::

      import rt.rest2_async
      import httpx2

      async with rt.rest2_async.AsyncRt(url='http://localhost/rt/REST/2.0/', http_auth=httpx2.BasicAuth('root', 'password')) as tracker:
          ticket = await tracker.get_ticket(1)

⚠️ **Warning**:
    The next release contains breaking changes for both the REST API version 1 and version 2 parts. Please see the
    migration guide in the changelog (CHANGELOG.md) for details.

Documentation
=============
https://python-rt.readthedocs.io/en/latest/

Installation
============

Install the python-rt package using::

  pip install rt


Licence
=======

This module is distributed under the terms of GNU General Public Licence v3
and was developed by CZ.NIC Labs - research and development department of
CZ.NIC association - top level domain registry for .CZ.  Copy of the GNU
General Public License is distributed along with this module.

Usage
=====

An example is worth a thousand words::

    >>> import rt.rest2
    >>> import httpx2
    >>> tracker = rt.rest2.Rt(url='http://localhost/rt/REST/2.0/', http_auth=httpx2.BasicAuth('root', 'password'))
    >>> [ticket['id'] for ticket in tracker.search(queue='helpdesk', Status='open')]
    ['1', '2', '10', '15']
    >>> tracker.create_ticket(queue='helpdesk', \
    ... subject='Coffee (important)', content='Help I Ran Out of Coffee!')
    19
    >>> tracker.edit_ticket(19, Requestor='addicted@example.com')
    ['Added addicted@example.com as Requestor for this ticket']
    >>> tracker.reply(19, content='Do you know Starbucks?')
    ['Correspondence added']

Get the last important updates from a specific queue that have been updated recently::

    >>> import datetime
    >>> import base64
    >>> import rt.rest2
    >>> import httpx2
    >>> tracker = rt.rest2.Rt(url='http://localhost/rt/REST/2.0/', http_auth=httpx2.BasicAuth('root', 'password'))
    >>> fifteen_minutes_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    >>> tickets = tracker.last_updated(since=fifteen_minutes_ago, queue='helpdesk')
    >>> for ticket in tickets:
    >>>     id = ticket['id']
    >>>     history = list(tracker.get_ticket_history(id))
    >>>     last_update = list(reversed([h for h in history if h['Type'] in ('Correspond', 'Comment')]))
    >>>     hid = tracker.get_transaction(last_update[0]['id'] if last_update else history[0]['id'])
    >>>
    >>>     attachment_id = None
    >>>     for k in hid['_hyperlinks']:
    >>>         if k['ref'] == 'attachment':
    >>>             attachment_id = k['_url'].rsplit('/', 1)[1]
    >>>             break
    >>>
    >>>     if attachment_id is not None:
    >>>         attachment = tracker.get_attachment(attachment_id)
    >>>         if attachment['Content'] is not None:
    >>>             content = base64.b64decode(attachment['Content']).decode()
    >>>             print(content)



Please use docstrings to see how to use different functions. They are written
in ReStructuredText. You can also generate HTML documentation by running
``make html`` in doc directory (Sphinx required).

Official Site
=============

Project site, issue tracking and git repository:
    https://github.com/python-rt/python-rt
