Usage
=====

REST API version 2
-------------------

Creating a Connection
`````````````````````
All arguments of the constructor must be passed by keyword::

    import rt.rest2
    import httpx2

    api_url = 'http://localhost:8080/REST/2.0/'
    c = rt.rest2.Rt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password'))

Instead of ``http_auth``, an authentication token created in RT can be used with ``token='...'``.
Further optional arguments are ``proxy``, ``verify_cert`` (``False`` or the path to a CA bundle file),
``http_timeout`` (in seconds, default 20, ``None`` for no timeout) and ``per_page`` (number of items
requested per page for results which are split into pages by RT, at most 100, which is the default).

The client keeps its HTTP connections open for further requests. Close it when it is not needed anymore,
or use it as context manager, which closes it automatically::

    with rt.rest2.Rt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password')) as c:
        ticket = c.get_ticket(1)

    # or
    c.close()

To configure the HTTP connection in other ways (e.g. retries, HTTP/2, event hooks or a custom transport),
pass your own ``httpx2.Client``. It is then used as it is, so ``proxy``, ``verify_cert``, ``http_auth``,
``token`` and ``http_timeout`` can not be passed as well, and it is not closed by ``close()``::

    http_client = httpx2.Client(
        auth=httpx2.BasicAuth('root', 'password'),
        transport=httpx2.HTTPTransport(retries=3),
    )
    c = rt.rest2.Rt(url=api_url, client=http_client)


Ticket Operations
`````````````````

Fetching a ticket::

    c.get_ticket(1)

which gives:

.. code-block:: json

    {
        "Due": "1970-01-01T00:00:00Z",
        "Status": "new",
        "Created": "2022-05-02T18:54:36Z",
        "CustomFields": [],
        "TimeEstimated": "0",
        "LastUpdatedBy": {
            "id": "root",
            "type": "user",
            "_url": "http://localhost:8080/REST/2.0/user/root"
        },
        "Type": "ticket",
        "Owner": {
            "id": "Nobody",
            "_url": "http://localhost:8080/REST/2.0/user/Nobody",
            "type": "user"
        },
        "Cc": [],
        "Started": "1970-01-01T00:00:00Z",
        "AdminCc": [],
        "Priority": "0",
        "LastUpdated": "2022-05-02T19:21:30Z",
        "Subject": "Testing issue wvbocycTSwmNTAX",
        "FinalPriority": "0",
        "Queue": {
            "id": "1",
            "type": "queue",
            "_url": "http://localhost:8080/REST/2.0/queue/1",
            "Name": "General"
        },
        "InitialPriority": "0",
        "Resolved": "1970-01-01T00:00:00Z",
        "Creator": {
            "type": "user",
            "_url": "http://localhost:8080/REST/2.0/user/root",
            "id": "root"
        },
        "EffectiveId": {
            "_url": "http://localhost:8080/REST/2.0/ticket/8",
            "type": "ticket",
            "id": "8"
        },
        "Starts": "1970-01-01T00:00:00Z",
        "TimeWorked": "0",
        "TimeLeft": "0",
        "Requestor": [],
        "_hyperlinks": [
            {
                "id": 8,
                "ref": "self",
                "_url": "http://localhost:8080/REST/2.0/ticket/8",
                "type": "ticket"
            },
            {
                "ref": "history",
                "_url": "http://localhost:8080/REST/2.0/ticket/8/history"
            },
            {
                "_url": "http://localhost:8080/REST/2.0/ticket/8/correspond",
                "ref": "correspond"
            },
            {
                "ref": "comment",
                "_url": "http://localhost:8080/REST/2.0/ticket/8/comment"
            },
            {
                "ref": "lifecycle",
                "update": "Respond",
                "from": "new",
                "label": "Open It",
                "_url": "http://localhost:8080/REST/2.0/ticket/8/correspond",
                "to": "open"
            },
            {
                "label": "Resolve",
                "to": "resolved",
                "_url": "http://localhost:8080/REST/2.0/ticket/8/comment",
                "ref": "lifecycle",
                "update": "Comment",
                "from": "new"
            },
            {
                "to": "rejected",
                "_url": "http://localhost:8080/REST/2.0/ticket/8/correspond",
                "label": "Reject",
                "from": "new",
                "update": "Respond",
                "ref": "lifecycle"
            },
            {
                "ref": "lifecycle",
                "label": "Delete",
                "_url": "http://localhost:8080/REST/2.0/ticket/8",
                "from": "new",
                "to": "deleted"
            }
        ],
        "id": 8
    }


Getting ticket links::

    c.get_links(1)

for a ticket with #1 having ticket #7 as parent, this would have as result:

.. code-block:: json

    [
        {
            "_url": "http://localhost:8080/REST/2.0/ticket/7",
            "type": "ticket",
            "ref": "parent",
            "id": "7"
        }
    ]

Editing ticket links. Adding a dependency on another ticket::

    c.edit_link(1, 'DependsOn', 7)

and removing it again::

    c.edit_link(1, 'DependsOn', 7, delete=True)

Creating a ticket::

    new_ticket = {'Requestor': ['test@example.com'],
                  }
    res = c.create_ticket('General',
                          subject='Test subject',
                          content='Ticket body...',
                          **new_ticket
                          )

This returns the ID of the created ticket.

Editing a ticket::

    c.edit_ticket(8,
                  Subject='Re: Test subject',
                  CustomFields={'CF1': 'value1',
                                ...
                                }
                  )

Methods changing something return the status messages of RT, e.g.
``["Ticket 8: Subject changed from 'Test subject' to 'Re: Test subject'"]``. If RT refuses the change,
an exception is raised instead, e.g. :py:exc:`~rt.exceptions.InvalidUseError` when taking a ticket which is
already owned by the user. ``edit_ticket()`` and similar methods are an exception: RT reports invalid values
of single fields only in the returned messages (e.g. ``"Ticket 8: Status 'x' isn't a valid status for this ticket."``),
while the other fields are changed anyway.

All optional arguments of the methods must be passed by keyword.

The docstrings of the methods state the minimum RT version they require.


Searching for tickets with status *new* in the *General* queue::

    list(c.search(queue='General', Status='new'))

gives:

.. code-block:: python

    [
        {
            "type": "ticket",
            "InitialPriority": "0",
            "CustomFields": "",
            "TimeEstimated": "0",
            "Due": "1970-01-01T00:00:00Z",
            "Priority": "0",
            "Status": "new",
            "Created": "2022-05-02T18:54:35Z",
            "Queue": {
                "Name": "General",
                "type": "queue",
                "_url": "http://localhost:8080/REST/2.0/queue/1",
                "id": "1"
            },
            "Subject": "Testing issue SsOwRvDXMGnurhU",
            "LastUpdated": "2022-05-02T20:44:02Z",
            "TimeLeft": "0",
            "Owner": {
                "id": "Nobody",
                "_url": "http://localhost:8080/REST/2.0/user/Nobody",
                "type": "user"
            },
            "Started": "1970-01-01T00:00:00Z",
            "Requestor": [],
            "Cc": [],
            "AdminCc": [],
            "id": "7",
            "_url": "http://localhost:8080/REST/2.0/ticket/7",
            "Type": "ticket"
        },
        ...
    ]

Do a reply on a ticket::

    c.reply(1, content='test')

Comment on a ticket::

    c.comment(1, content='test')

Merge ticket #1 into #2::

    c.merge_ticket(1, 2)

Take, untake or steal a ticket (stealing is only possible for tickets owned by another user)::

    c.take(1)
    c.untake(1)
    c.steal(1)

Comment on a ticket and add an attachment::

    with open('README.rst', 'rb') as fhdl:
        attachment = rt.rest2.Attachment('README.rst', 'text/plain', fhdl.read())
    c.comment(1, 'test', attachments=[attachment])

``reply()`` and ``comment()`` accept the content types ``text/plain`` (default) and ``text/html``::

    c.reply(1, content='<p>test</p>', content_type='text/html')


Get attachments for a ticket::

    list(c.get_attachments(1))

returns:

.. code-block:: json

    [
        {
            "type": "attachment",
            "_url": "http://localhost:8080/REST/2.0/attachment/34",
            "Filename": "README.rst",
            "ContentType": "text/plain",
            "id": "34",
            "ContentLength": "3578"
        }
    ]

Fetch an attachment by its ID::

    c.get_attachment(34)


Searching Tickets
`````````````````
``search()`` returns an iterator over the matching tickets; RT returns the results in pages, which are requested
as needed while iterating. Conditions are passed as keyword arguments, which are combined with ``AND``::

    for ticket in c.search(queue='General', Status='open', Owner='Nobody'):
        print(ticket['id'], ticket['Subject'])

Custom fields are searched with the prefix ``CF_``, e.g. ``CF_Severity='High'``.

Conditions can also be passed as a mapping with ``conditions``, e.g. for field names which are not valid Python
identifiers or conditions built at runtime. Unlike unpacking a dictionary with ``**``, this is accepted by type
checkers like mypy. Both forms can be combined, but a condition must not be given in both::

    c.search(queue='General', conditions={'CF_Contact Email': 'a@example.com'}, Status='open')

Other operators than ``=`` are used by appending them to the field name, e.g. ``Subject__like='coffee'``:

======================  ==============================
Suffix                  TicketSQL operator
======================  ==============================
``__exact`` (default)   ``=``
``__notexact``          ``!=``
``__gt``, ``__gte``     ``>``, ``>=``
``__lt``, ``__lte``     ``<``, ``<=``
``__like``              ``LIKE``
``__notlike``           ``NOT LIKE``
``__startswith``        ``STARTSWITH``
``__notstartswith``     ``NOT STARTSWITH``
``__endswith``          ``ENDSWITH``
``__notendswith``       ``NOT ENDSWITH``
``__is``                ``IS`` (only with ``None``)
``__isnot``             ``IS NOT`` (only with ``None``)
======================  ==============================

For example, all open tickets with a priority of at least 50 which are not resolved::

    c.search(queue='General', Status='open', Priority__gte=50, Resolved__is=None)

All values are quoted, so they can not change the meaning of the query. A complete TicketSQL query can be passed
with ``raw_query`` instead; it is passed to RT as is, so it must never contain untrusted input::

    c.search(queue='General', raw_query="Status = 'new' OR Status = 'open'")

The fields returned for each ticket are selected with ``fields``: ``'l'`` (default, many fields),
``'s'`` (ID and subject), ``'i'`` (only the ID), or a list of fields::

    c.search(queue='General', fields=['Subject', 'Status'])

Tickets updated recently::

    import datetime

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    for ticket in c.last_updated(since, queue='General'):
        print(ticket['id'])

A ``datetime`` with timezone is an exact point in time. Dates, naive datetimes and strings like ``'2024-01-31'``
or ``'2024-01-31 12:00:00'`` are interpreted by RT in the timezone of the RT user.


Users and Groups
````````````````
Users and groups are searched with conditions like assets (all if none are given), e.g. the privileged users
of a domain::

    c.search_users(search_params=[{'field': 'EmailAddress', 'operator': 'LIKE', 'value': '@example.com'}],
                   privileged=True)

Groups are identified by their ID, as RT does not support group names in most requests. Members are added
one at a time, by name to a group or by ID (of a user or group) as member of a group::

    group_id = c.create_group('Staff', Description='Support staff')
    c.add_user_to_group('alice', group_id)
    c.add_group_member(group_id, 42)
    for member in c.get_group_members(group_id, recursive=True):
        print(member['type'], member['id'])


Custom Fields
`````````````
Creating a custom field for tickets with selectable values and applying it to queues::

    cf_id = c.create_custom_field('Severity', 'Select', 'RT::Queue-RT::Ticket', MaxValues=1)
    c.add_custom_field_value(cf_id, 'High', SortOrder=1)
    c.add_custom_field_value(cf_id, 'Low', SortOrder=2)
    c.apply_custom_field(cf_id, queue_id)  # 0 applies it globally, requires RT 6.0.3 or newer

The custom fields applied to a queue::

    c.search_custom_fields(object_type='queue', object_id=queue_id)

Files are set as value of an Image or Binary custom field with an :py:class:`~rt.common.Attachment`, and read
with the ID which is the last part of the ``_url`` of the value in the ticket::

    c.edit_ticket(8, CustomFields={'Screenshot': Attachment('screen.png', 'image/png', content).to_dict()})
    content = c.get_custom_field_file(value_id)


Rights
``````
Rights can be managed with RT 6.0.3 or newer. They are granted on a queue, group, class, catalog or custom field,
or globally, to a user (by name or ID) or a group (by ID)::

    c.grant_right('queue', 'General', 'CreateTicket', group=group_id)
    c.grant_right('global', None, 'SuperUser', user='alice')
    for right in c.get_rights('queue', 'General', user='alice'):
        print(right['Right'])
    c.revoke_right('queue', 'General', 'CreateTicket', group=group_id)

``get_available_rights()`` returns the rights which can be granted on an object, grouped by category.
Granting a right which is already granted raises :py:exc:`~rt.exceptions.ConflictError`.

The version of RT and its plugins are returned by ``get_system_info()``.


Error Handling
``````````````
All exceptions raised by the library are subclasses of :py:exc:`rt.exceptions.RtError`, e.g.:

* :py:exc:`~rt.exceptions.NotFoundError`: the ticket, user, queue etc. does not exist.
* :py:exc:`~rt.exceptions.AuthorizationError`: the credentials are invalid.
* :py:exc:`~rt.exceptions.NotAllowedError`: the user does not have the rights for the request.
* :py:exc:`~rt.exceptions.BadRequestError`: RT rejected the request.
* :py:exc:`~rt.exceptions.ConflictError`: the request conflicts with the state in RT, e.g. a right is already
  granted. It is a subclass of :py:exc:`~rt.exceptions.UnexpectedResponseError`.
* :py:exc:`~rt.exceptions.InvalidUseError`: invalid arguments, e.g. an unsupported search operator, or RT
  refused the action, e.g. merging a ticket into itself. It is also a builtin ``ValueError``.
* :py:exc:`~rt.exceptions.UnexpectedResponseError`: the response is not as expected, e.g. an unexpected
  status code or an HTML page returned by a proxy instead of RT.
* :py:exc:`~rt.exceptions.RtConnectionError`: RT can not be reached. It is also a builtin ``ConnectionError``.

Exceptions caused by an HTTP response of RT carry its status code and body in the attributes ``status_code``
and ``response_message``.

::

    import rt.exceptions

    try:
        c.get_ticket(1)
    except rt.exceptions.NotFoundError:
        print('No such ticket')


Async Usage
```````````
``rt.rest2_async.AsyncRt`` provides the same methods as ``rt.rest2.Rt`` as coroutines. Methods returning
multiple results are async iterators::

    import rt.rest2_async
    import httpx2

    async with rt.rest2_async.AsyncRt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password')) as c:
        ticket = await c.get_ticket(1)
        async for ticket in c.search(queue='General', Status='open'):
            print(ticket['id'])

An own ``httpx2.AsyncClient`` can be passed with ``client``, and the client is closed with ``await c.aclose()``.


REST API version 1
------------------
All arguments of the constructor must be passed by keyword::

    import rt.rest1

    c = rt.rest1.Rt(url='https://rt.example.com/REST/1.0/', default_login='root', default_password='password')
    c.login()
    ticket = c.get_ticket(1)
    c.reply(1, text='test', cc='someone@example.com')
    c.logout()
