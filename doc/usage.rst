Usage
=====

REST API version 2
-------------------
The examples use the synchronous client ``rt.rest2.Rt``. The asynchronous client ``rt.rest2_async.AsyncRt`` has the
same methods, see `Async Usage`_. The docstrings of the methods (see the API documentation) describe all parameters
and state the minimum RT version each method requires.

Creating a Connection
`````````````````````
All arguments of the constructor must be passed by keyword::

    import httpx2
    import rt.rest2

    api_url = 'https://rt.example.com/REST/2.0/'
    c = rt.rest2.Rt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password'))

Instead of ``http_auth``, an authentication token created in RT (user preferences, *Auth Tokens*) can be used::

    c = rt.rest2.Rt(url=api_url, token='1-14-ec2bd73b6f1b9a5d8f1ac4b8f0d5e7a1')

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

The requests and responses are logged with the logger ``rt.rest2`` (``rt.rest2_async`` for the async client) at
level ``DEBUG``. Credentials in the request headers are redacted and request bodies are not logged::

    import logging

    logging.basicConfig()
    logging.getLogger('rt.rest2').setLevel(logging.DEBUG)


Results, Messages and Errors
````````````````````````````
Methods returning a single object return it as dictionary, as returned by RT. Methods returning several objects,
e.g. searches, return iterators: RT returns the results in pages, which are requested as needed while iterating.
Use ``list()`` to get all results at once::

    tickets = list(c.search(queue='General', Status='new'))

Searches and lists return a few fields of each object by default; other fields are selected with ``fields``, e.g.
``fields=['Name', 'Description']``, or with a dictionary of query parameters as defined by RT, which also allows to
return fields of linked objects, e.g. ``fields={'fields': 'Owner', 'fields[Owner]': 'Name,EmailAddress'}``.

Methods changing something return the status messages of RT, e.g.
``["Ticket 8: Subject changed from 'Test subject' to 'Re: Test subject'"]``. If RT refuses the change,
an exception is raised instead, e.g. :py:exc:`~rt.exceptions.InvalidUseError` when taking a ticket which is
already owned by the user. ``edit_ticket()`` and the other ``edit_*()`` methods are an exception: RT reports invalid
values of single fields only in the returned messages (e.g.
``"Ticket 8: Status 'x' isn't a valid status for this ticket."``), while the other fields are changed anyway.

All exceptions raised by the library are subclasses of :py:exc:`rt.exceptions.RtError`:

* :py:exc:`~rt.exceptions.NotFoundError`: the ticket, user, queue etc. does not exist.
* :py:exc:`~rt.exceptions.AuthorizationError`: the credentials are invalid.
* :py:exc:`~rt.exceptions.NotAllowedError`: the user does not have the rights for the request.
* :py:exc:`~rt.exceptions.BadRequestError`: RT rejected the request, e.g. an invalid TicketSQL query.
* :py:exc:`~rt.exceptions.ConflictError`: the request conflicts with the state in RT, e.g. a right is already
  granted. It is a subclass of :py:exc:`~rt.exceptions.UnexpectedResponseError`.
* :py:exc:`~rt.exceptions.InvalidUseError`: invalid arguments, e.g. an unsupported search operator, or RT
  refused the action, e.g. merging a ticket into itself. It is also a builtin ``ValueError``.
* :py:exc:`~rt.exceptions.UnexpectedResponseError`: the response is not as expected, e.g. an unexpected
  status code or an HTML page returned by a proxy instead of RT.
* :py:exc:`~rt.exceptions.RtConnectionError`: RT can not be reached. It is also a builtin ``ConnectionError``.

Exceptions caused by an HTTP response of RT carry its status code and body in the attributes ``status_code``
and ``response_message``::

    import rt.exceptions

    try:
        c.take(1)
    except rt.exceptions.NotFoundError:
        print('No such ticket')
    except rt.exceptions.InvalidUseError as exc:
        print(f'RT refused: {exc}')  # e.g. "You already own this ticket"


Tickets
```````
Creating a ticket returns its ID. Requestors, watchers, custom fields and custom roles are set with the field
names of RT::

    ticket_id = c.create_ticket(
        'General',
        subject='Printer out of order',
        content='The printer in room 2 does not print.',
        Requestor=['alice@example.com'],
        CustomFields={'Severity': 'High'},
    )

Creating a ticket with an attachment::

    from rt.common import Attachment

    with open('error.log', 'rb') as file:
        attachment = Attachment('error.log', 'text/plain', file.read())
    ticket_id = c.create_ticket('General', subject='Crash', content='See the log.', attachments=[attachment])

Fetching a ticket; fields of linked objects (e.g. the name and email address of the owner) are returned with
``fields``::

    ticket = c.get_ticket(ticket_id, fields={'fields[Owner]': 'Name,EmailAddress'})
    print(ticket['Subject'], ticket['Status'], ticket['Queue']['Name'], ticket['Owner']['EmailAddress'])

Changing fields, e.g. resolving the ticket, assigning it, or changing custom fields::

    c.edit_ticket(ticket_id, Status='resolved')
    c.edit_ticket(ticket_id, Owner='alice', Priority=50, CustomFields={'Severity': 'Low'})

Taking, untaking or stealing a ticket (stealing is only possible for tickets owned by another user)::

    c.take(ticket_id)
    c.untake(ticket_id)
    c.steal(ticket_id)

Replying to a ticket (sent to the requestors) and commenting on it (not sent to the requestors), in ``text/plain``
(default) or ``text/html``, optionally with attachments::

    c.reply(ticket_id, 'We will replace the toner today.')
    c.comment(ticket_id, '<p>Toner ordered.</p>', content_type='text/html', attachments=[attachment])

Replies and comments can also set the subject of the message, record the time worked, and change the status,
custom fields and custom roles of the ticket and the custom fields of the transaction in the same request. RT sets
these after adding the message and reports refused values only in the returned messages::

    c.reply(ticket_id, 'Fixed, please check.', time_taken=15, status='resolved', custom_fields={'Severity': 'Low'})

Links between tickets, and to URLs::

    c.edit_link(ticket_id, 'DependsOn', 7)
    c.edit_link(ticket_id, 'RefersTo', 'https://wiki.example.com/printers')
    c.edit_link(ticket_id, 'DependsOn', 7, delete=True)
    for link in c.get_links(ticket_id):
        print(link['ref'], link['type'], link['_url'])  # e.g. "refers-to external https://wiki.example.com/printers"

Merging a ticket into another one, and deleting a ticket (RT sets its status to *deleted*)::

    c.merge_ticket(ticket_id, 7)
    c.delete_ticket(8)


Messages, History and Attachments
`````````````````````````````````
The messages of a ticket (its creation, replies and comments) with their text and author, oldest first, in one
request per 100 messages::

    for message in c.get_ticket_messages(ticket_id):
        print(message['Created'], message['Creator']['Name'], message['Type'], message['Content'])

All transactions of a ticket, also e.g. status changes, are returned by ``get_ticket_history()``, a single
transaction by ``get_transaction()``. Transactions are searched, also across tickets, with conditions or a
TransactionSQL query (RT 5.0.2 or newer)::

    c.search_transactions(raw_query="Type = 'Comment' AND Created > '2024-01-01'", fields=['Type', 'Content'])

The files attached to a ticket, and the content of a file (RT returns it base64 encoded)::

    import base64

    for attachment in c.get_attachments(ticket_id):
        print(attachment['id'], attachment['Filename'], attachment['ContentType'], attachment['ContentLength'])
        content = base64.b64decode(c.get_attachment(attachment['id'])['Content'])

The files of a single reply or comment, e.g. of a message returned by ``get_ticket_messages()``::

    c.get_attachments(ticket_id, search_params=[{'field': 'TransactionId', 'value': message['id']}])

Files are searched across all tickets, e.g. by name, content type or creation time (RT only returns those the user
is allowed to see)::

    c.search_attachments(search_params=[{'field': 'ContentType', 'value': 'application/pdf'},
                                        {'field': 'Created', 'operator': '>', 'value': '2024-01-01'}])


Searching Tickets
`````````````````
``search()`` returns an iterator over the matching tickets. Conditions are passed as keyword arguments, which are
combined with ``AND``::

    for ticket in c.search(queue='General', Status='open', Owner='Nobody'):
        print(ticket['id'], ticket['Subject'])

Custom fields are searched with the prefix ``CF_``, e.g. ``CF_Severity='High'``.

Conditions can also be passed as a mapping with ``conditions``, e.g. for field names which are not valid Python
identifiers or conditions built at runtime. Unlike unpacking a dictionary with ``**``, this is accepted by type
checkers like mypy. Both forms can be combined, but a condition must not be given in both::

    c.search(queue='General', conditions={'CF_Contact Email': 'a@example.com', 'Requestor.EmailAddress': 'b@example.com'}, Status='open')

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

All values are quoted, so they can not change the meaning of the query; field names other than plain names like
``Subject`` or ``Requestor.EmailAddress`` are quoted as well, e.g. ``conditions={'CustomRole.{Manager}': 'alice'}``.

A complete TicketSQL query can be passed with ``raw_query`` instead of conditions (``queue`` and ``order`` can still
be used); it is passed to RT as is, so it must never contain untrusted input::

    c.search(queue='General', raw_query="Status = 'new' OR Status = 'open'", order='-Created')

The query is sent in the body of a POST request, so it is not limited by the maximum length of URLs.

The fields returned for each ticket are selected with ``fields``: ``'l'`` (default, many fields),
``'s'`` (ID and subject), ``'i'`` (only the ID), a list of fields, or a dictionary of query parameters::

    c.search(queue='General', fields=['Subject', 'Status'])

Tickets updated recently, and tickets updated by other users than the one of the connection::

    import datetime

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    for ticket in c.last_updated(since, queue='General'):
        print(ticket['id'])
    for ticket in c.new_correspondence(queue='General'):
        print(ticket['id'])

A ``datetime`` with timezone is an exact point in time. Dates, naive datetimes and strings like ``'2024-01-31'``
or ``'2024-01-31 12:00:00'`` are interpreted by RT in the timezone of the RT user.


Queues
``````
Queues are identified by name or ID::

    queue = c.get_queue('General')
    for queue in c.get_all_queues():
        print(queue['id'], queue['Name'])
    c.search_queues(search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Support'}])

    queue_id = c.create_queue('Support', Description='First level support', SubjectTag='support')
    c.edit_queue('Support', CorrespondAddress='support@example.com', AdminCc='alice')
    c.delete_queue('Support')  # disables the queue


Users and Groups
````````````````
Users are identified by name or ID::

    user = c.get_user('alice')
    c.create_user('bob', 'bob@example.com', RealName='Bob Example', Password='secret', Privileged=1)
    c.edit_user('bob', Organization='Example Inc.', Disabled=0)
    c.user_exists('bob', privileged=False)
    c.delete_user('bob')  # disables the user

Users and groups are searched with conditions like the ones of assets (all if none are given), e.g. the privileged
users of a domain::

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

    c.edit_ticket(ticket_id, CustomFields={'Screenshot': Attachment('screen.png', 'image/png', content).to_dict()})
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


Assets and Catalogs
```````````````````
Catalogs are created, edited and disabled like queues::

    catalog_id = c.create_catalog('Laptops', Description='Company laptops')
    c.edit_catalog('Laptops', Description='All laptops')
    for catalog in c.get_all_catalogs():
        print(catalog['Name'])

Assets are created in a catalog, edited, and marked as deleted::

    asset_id = c.create_asset('Laptop 42', 'Laptops', Description='ThinkPad', HeldBy='alice')
    c.edit_asset(asset_id, Status='in-use')
    c.delete_asset(asset_id)

Assets are searched with conditions, or with an AssetSQL query (RT 5.0.2 or newer), which is passed to RT as is::

    c.search_assets(catalog_id=catalog_id, search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Laptop'}])
    c.search_assets(raw_query="Catalog = 'Laptops' AND Status = 'in-use'")

RT ignores an invalid AssetSQL query and then returns all assets.


Articles and Classes
````````````````````
Articles (RT 5.0.1 or newer) belong to a class, their text is stored in the custom field ``Content``::

    class_id = c.create_class('FAQ', Description='Frequently asked questions')
    article_id = c.create_article('VPN setup', 'FAQ', Summary='How to set up the VPN',
                                  CustomFields={'Content': 'Install the client ...'})
    for article in c.search_articles(search_params=[{'field': 'Class', 'value': class_id}]):
        print(article['Name'], article['Summary'])

Custom roles are read with ``search_custom_roles()`` and ``get_custom_role()`` (REST2 can not create or change them).


Async Usage
```````````
``rt.rest2_async.AsyncRt`` provides the same methods as ``rt.rest2.Rt`` as coroutines. Methods returning
multiple results are async iterators, which are iterated without ``await``::

    import httpx2
    import rt.rest2_async

    async with rt.rest2_async.AsyncRt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password')) as c:
        ticket = await c.get_ticket(1)
        async for ticket in c.search(queue='General', Status='open'):
            print(ticket['id'])
        tickets = [ticket async for ticket in c.search(queue='General')]

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
