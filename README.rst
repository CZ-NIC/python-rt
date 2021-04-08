           
.. image:: https://travis-ci.org/CZ-NIC/python-rt.svg?branch=master
    :target: https://travis-ci.org/CZ-NIC/python-rt
.. image:: https://readthedocs.org/projects/python-rt/badge/?version=latest
    :target: https://python-rt.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

==============================================
 Rt - Python interface to Request Tracker API 
==============================================

Python interface to Request Tracker's REST API. With this library, you can
automate most actions with Request Tracker that you would be able to make
with the web interface.

 * Version 2.0 of the API uses JSON for input and output which makes it easier
   to parse. You can find information about it here:
   https://docs.bestpractical.com/rt/5.0.0/RT/REST2.html

   * This version of the API is builtin to RT since 5.0. To make it
     available on 4.x you need to install it as a plugin:
     https://metacpan.org/release/RT-Extension-REST2

 * Version 1.0 of the API comes built-in to RT and is described here:
   https://rt-wiki.bestpractical.com/wiki/REST

**Note:** Please note that starting with the major release of v2.0.0, this library requires a Python version >= 3.5.
In case you still require a Python 2 version or one compatible with Python < 3.5, please use a version < 2.0.0 of this library.


REQUIREMENTS
============

This module uses following Python modules:

- requests (http://docs.python-requests.org/)

Unit-tests are implemented using:
- nose (http://nose.readthedocs.org)


INSTALLATION
============

Install the python-rt package using::

  pip install rt


LICENCE
=======

This module is distributed under the terms of GNU General Public Licence v3
and was developed by CZ.NIC Labs - research and development department of
CZ.NIC association - top level domain registy for .CZ.  Copy of the GNU
General Public License is distributed along with this module.

USAGE
=====

An example is worth a thousand words::

    >>> import rt
    >>> tracker = rt.Rt('http://localhost/rt/REST/1.0/', 'user_login', 'user_pass')
    >>> tracker.login()
    True
    >>> map(lambda x: x['id'], tracker.search(Queue='helpdesk', Status='open'))
    ['ticket/1', 'ticket/2', 'ticket/10', 'ticket/15']
    >>> tracker.create_ticket(Queue='helpdesk', \
    ... Subject='Coffee (important)', Text='Help I Ran Out of Coffee!')
    19
    >>> tracker.edit_ticket(19, Requestors='addicted@example.com')
    True
    >>> tracker.reply(19, text='Do you know Starbucks?')
    True
    >>> tracker.logout()
    True

Get the last important updates from a specific queue that have been updated recently::

    >>> import rt
    >>> tracker = rt.Rt('http://localhost/rt/REST/1.0/', http_auth=HTTPBasicAuth(os.environ['rtuser'], os.environ['rtpasswd']))
    >>> tracker.default_queue = "my-queue"
    >>> fifteen_minutes_ago = str(datetime.datetime.now() - datetime.timedelta(minutes=15))
    >>> tickets = tracker.last_updated(since=fifteen_minutes_ago)
    >>> for ticket in tickets:
    >>>     id = ticket['id'][7:]
    >>>     history = tracker.get_short_history(id)
    >>>     last_update = list(reversed([h for h in history if h[1].startswith('Correspondence added') or h[1].startswith('Comments added')]))
    >>>     hid = tracker.get_history(id, last_update[0][0] if last_update else history[0][0])[0]
    >>>     print("http://localhost/rt/Ticket/Display.html?id=%s" % id)
    >>>     print(hid['Content'])
    >>>     print("\n")
		
		
Please use docstrings to see how to use different functions. They are written
in ReStructuredText. You can also generate HTML documentation by running
``make html`` in doc directory (Sphinx required).

OFFICIAL SITE
=============

Project site and issue tracking:
    https://github.com/CZ-NIC/python-rt

Git repository:
    git://github.com/CZ-NIC/python-rt.git    
    
