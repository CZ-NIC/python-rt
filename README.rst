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
          ticket = await tracker.tickets.get(1)

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
    >>> [ticket['id'] for ticket in tracker.tickets.search(queue='helpdesk', Status='open')]
    ['1', '2', '10', '15']
    >>> tracker.tickets.create(queue='helpdesk', \
    ... subject='Coffee (important)', content='Help I Ran Out of Coffee!')
    19
    >>> result = tracker.tickets.edit(19, Requestor='addicted@example.com')
    >>> result.complete
    True
    >>> bool(tracker.tickets.reply(19, content='Do you know Starbucks?'))
    True

Print the last reply or comment of the tickets of a queue which have been updated recently::

    >>> import datetime
    >>> import rt.rest2
    >>> import httpx2
    >>> tracker = rt.rest2.Rt(url='http://localhost/rt/REST/2.0/', http_auth=httpx2.BasicAuth('root', 'password'))
    >>> fifteen_minutes_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    >>> for ticket in tracker.tickets.last_updated(fifteen_minutes_ago, queue='helpdesk'):
    ...     messages = list(tracker.tickets.messages(ticket['id']))
    ...     print(ticket['id'], messages[-1]['Creator']['Name'], messages[-1]['Content'])

See the documentation for more examples.

Please use docstrings to see how to use different functions. They are written
in ReStructuredText. You can also generate HTML documentation by running
``make html`` in doc directory (Sphinx required).

Testing
=======

The tests run against a live RT on port 8080. Start the container image
`ghcr.io/python-rt/request-tracker <https://github.com/python-rt/docker-rt>`_ from the root of the repository::

    docker run --rm --name rt -p 8080:8080 \
      -v ./tests/rt_initdata.pl:/docker-entrypoint-init.d/python-rt.pl:ro \
      ghcr.io/python-rt/request-tracker:6.0

``tests/rt_initdata.pl`` is inserted on the first start of the container (a custom field needed by the tests). The
tests needing an authentication token are skipped unless ``RT_TOKEN`` is set; when RT is ready, run the tests in
another shell with::

    export RT_TOKEN=$(docker exec rt rt-token)
    uv sync --group test
    uv run pytest tests

This runs the tests of the async client in 4 parallel processes (about a minute; ``-n 0`` runs them one after the other,
e.g. to debug them, ``-n 8`` is a bit faster). The tests of the sync client are generated from them (``uv run unasyncd``)
and only run with ``uv run pytest -m sync tests``; use ``uv run pytest -m '' tests`` to run all tests. Tests which do not
need RT (mocked responses, unit tests) run in a few seconds with ``uv run pytest -m 'not live' tests``.

The tests create objects, so use a new container for each run: once RT holds more than 100 objects of a kind (e.g. catalogs),
it does not return all of them in the listings and the tests of the listings fail.

The user is ``root`` with the password ``password``. Use ``docker pull ghcr.io/python-rt/request-tracker:6.0``
to update the image to the latest RT 6.0 release.

Official Site
=============

Project site, issue tracking and git repository:
    https://github.com/python-rt/python-rt
