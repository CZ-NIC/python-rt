Usage
=====

REST API version 2
-------------------
The examples use the synchronous client ``rt.rest2.Rt``. The asynchronous client ``rt.rest2_async.AsyncRt`` has the
same methods, see `Async Usage`_. The docstrings of the methods (see the API documentation) describe all parameters
and state the minimum RT version each method requires.

The methods are grouped by the kind of object they work on, in the attributes of the client: ``c.tickets``,
``c.users``, ``c.groups``, ``c.queues``, ``c.assets``, ``c.catalogs``, ``c.articles``, ``c.classes``,
``c.custom_fields``, ``c.custom_roles`` and ``c.rights``. Only ``c.get_system_info()`` and ``c.close()`` are methods of the client, so
that ``c.tickets.get(1)`` is the ticket 1 and ``c.users.get('root')`` the user *root*.

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
        ticket = c.tickets.get(1)

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

    tickets = list(c.tickets.search(queue='General', Status='new'))

Searches and lists return a few fields of each object by default; other fields are selected with ``fields``, e.g.
``fields=['Name', 'Description']``, or with a dictionary of query parameters as defined by RT, which also allows to
return fields of linked objects, e.g. ``fields={'fields': 'Owner', 'fields[Owner]': 'Name,EmailAddress'}``.
The lists of the members of a group, the groups of a user and the values of a custom field have no ``fields``, as RT
always returns the same few fields for them.

Searches and lists are sorted with ``order``: a field name, with ``-`` in front for descending order, or a list of
them; without it, RT uses its default order::

    c.queues.all(order='Name')
    c.tickets.search(queue='General', order=['Status', '-Created'])
    c.tickets.history(ticket_id, order='-Created')

Searches take their conditions in ``search_params`` (TicketSQL conditions for ``tickets.search()``, see below), and
so does the history of tickets, assets and articles, e.g. only the changes of the status::

    c.tickets.history(ticket_id, search_params=[{'field': 'Type', 'value': 'Status'}])

Results of changes
------------------

All methods which change something return an :py:class:`~rt.common.ActionResult`, which is **true whenever RT executed
the request**, so ``if tracker.tickets.comment(...)`` keeps working like the ``bool`` returned in earlier versions.

RT answers with HTTP status 200 and a list of status messages also if it refused all or a part of the request, and it
gives no flag for success or failure. The library classifies the messages with a catalog of the messages of RT
(``rt/_messages.py``, derived from the translation file of RT), and an exception is raised only for a refusal it knows:

* Methods which change one thing (``tickets.take()``, ``tickets.untake()``, ``tickets.steal()``, ``tickets.merge()``,
  ``tickets.edit_link()``, ``users.add_to_group()`` etc.) raise an exception if RT refuses, e.g. :py:exc:`~rt.exceptions.InvalidUseError` when
  taking a ticket which is already owned by the user, as nothing was changed.
* The ``edit()`` methods (``tickets.edit()``, ``users.edit()``, ...), ``tickets.reply()`` and ``tickets.comment()`` can be applied partly: they
  change everything RT accepts and report the values it refuses (e.g. an invalid status) only as a message. They do not
  raise, as parts of the request were made. Code which cares can look at the details::

    result = c.tickets.edit(1, Subject='New subject', Status='invalid')
    if result:               # True: RT changed the subject
        ...
    result.complete          # False: RT refused the status
    result.refused           # ("Ticket 1: Status 'invalid' isn't a valid status for this ticket.",)
    result.unrecognized      # messages which are not in the catalog of the library (see below)
    result.messages          # all messages of RT
    result.raise_for_refused()  # raises InvalidUseError; NotFoundError if e.g. a user does not exist

  ``raise_for_refused()`` raises :py:exc:`~rt.exceptions.NotFoundError` (e.g. a user or queue does not exist),
  :py:exc:`~rt.exceptions.NotAllowedError` (permission denied) or :py:exc:`~rt.exceptions.InvalidUseError` (a refused
  value), the most specific one if several parts were refused. ``tickets.reply()`` and ``tickets.comment()`` add the message before RT
  sets their other values (``status``, ``custom_fields`` and ``custom_roles``), so a refused value never prevents the
  message.

A message which is not in the catalog (a new message of a newer RT, a message in another language, or a message which
a value of a user makes ambiguous) is neither a success nor a refusal, and the HTTP status does not tell if the request
succeeded. It is listed in ``result.unrecognized``, which is empty in the normal case. What happens depends on how much
the method knows:

* The ``edit()`` methods, ``tickets.reply()`` and ``tickets.comment()`` never raise for it, as parts of the request were made.
* ``tickets.take()``, ``tickets.untake()``, ``tickets.steal()``, ``tickets.merge()``, ``tickets.edit_link()``, ``assets.edit_link()`` and
  ``groups.add_member()`` raise :py:exc:`~rt.exceptions.UnexpectedResponseError`, as the message is the only information
  about their result and the action may not have been made. This is not a refusal, so it is not an
  :py:exc:`~rt.exceptions.InvalidUseError`.
* ``users.add_to_group()`` and ``custom_fields.apply()`` do not raise, as RT tells their result with a status.

.. warning:: **The language of the user of the API must be set to English (``en``) in RT.**
             RT answers with localized messages (language of the user, or of the server). The catalog contains the
             English messages of RT only. In other languages nothing is recognized: for the ``edit()`` methods,
             ``tickets.reply()`` and ``tickets.comment()`` ``refused`` is always empty, ``complete`` always true and all
             messages are in ``unrecognized``; ``tickets.take()``, ``tickets.merge()`` and the other methods which change one thing always
             raise :py:exc:`~rt.exceptions.UnexpectedResponseError`, also if they succeeded. Set the language of the user in the preferences of RT
             (*Preferences / Language*), or in the configuration of RT with ``Set($DefaultLanguage, 'en')`` if the
             user has no language set.
             RT also ignores some invalid input without any message: unknown fields and custom fields, and values it
             can not interpret, e.g. an invalid date (reported as "Due changed from Not set to Not set") or a
             non-numeric priority.

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
        c.tickets.take(1)
    except rt.exceptions.NotFoundError:
        print('No such ticket')
    except rt.exceptions.InvalidUseError as exc:
        print(f'RT refused: {exc}')  # e.g. "You already own this ticket"


Unknown Field Names
```````````````````
RT ignores fields it does not know without any message: unknown fields in ``create()`` and ``edit()``, conditions on
fields it can not search in ``search_params`` (the search then finds more objects than intended, for users and groups
even all of them), and unknown names in ``fields`` (returned with an empty value).

The library knows the fields of RT 6.0, but newer versions of RT or extensions may support more. So it sends field
names it does not know to RT as they are, and logs a warning on the logger of the client (``rt.rest2`` or
``rt.rest2_async``), e.g. for a typo::

    c.tickets.edit(ticket_id, Statu='resolved')
    # WARNING tickets.edit: field(s) not known to the library, sent to RT as they are (RT ignores fields it does not know): Statu

The fields of users and queues are a closed set, so ``users.create()``, ``users.edit()``, ``queues.create()`` and
``queues.edit()`` raise :py:exc:`~rt.exceptions.InvalidUseError` for unknown fields instead. Custom fields are passed in
``CustomFields``, so their names are not checked in ``create()`` and ``edit()``. In search conditions (``CF.{name}``),
each custom field is looked up once (one request), and a warning is logged if RT does not find it, as RT then ignores the
condition as well. The names in ``fields`` are not checked, as RT also returns computed fields which are no fields of the
objects (e.g. ``ContentLength`` of attachments).


Tickets
```````
Creating a ticket returns its ID. Requestors, watchers, custom fields and custom roles are set with the field
names of RT::

    ticket_id = c.tickets.create(
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
    ticket_id = c.tickets.create('General', subject='Crash', content='See the log.', attachments=[attachment])

Fetching a ticket; fields of linked objects (e.g. the name and email address of the owner) are returned with
``fields``::

    ticket = c.tickets.get(ticket_id, fields={'fields[Owner]': 'Name,EmailAddress'})
    print(ticket['Subject'], ticket['Status'], ticket['Queue']['Name'], ticket['Owner']['EmailAddress'])

Changing fields, e.g. resolving the ticket, assigning it, or changing custom fields::

    c.tickets.edit(ticket_id, Status='resolved')
    c.tickets.edit(ticket_id, Owner='alice', Priority=50, CustomFields={'Severity': 'Low'})

Taking, untaking or stealing a ticket (stealing is only possible for tickets owned by another user)::

    c.tickets.take(ticket_id)
    c.tickets.untake(ticket_id)
    c.tickets.steal(ticket_id)

Replying to a ticket (sent to the requestors) and commenting on it (not sent to the requestors), in ``text/plain``
(default) or ``text/html``, optionally with attachments::

    c.tickets.reply(ticket_id, 'We will replace the toner today.')
    c.tickets.comment(ticket_id, '<p>Toner ordered.</p>', content_type='text/html', attachments=[attachment])

Replies and comments can also set the subject of the message, record the time worked, and change the status,
custom fields and custom roles of the ticket and the custom fields of the transaction in the same request. RT sets
these after adding the message and reports refused values only in the returned messages::

    c.tickets.reply(ticket_id, 'Fixed, please check.', time_taken=15, status='resolved', custom_fields={'Severity': 'Low'})

A message can not be sent to additional recipients only once (Cc or Bcc of a single reply or comment), as REST2 does
not support it: RT treats a ``Cc`` in the request as the new Cc watchers of the ticket, replacing the current ones,
and ignores a ``Bcc``. ``c.tickets.edit(ticket_id, Cc=[...])`` sets the Cc watchers of the ticket (also replacing them);
the REST1 ``reply()`` and ``comment()`` accept ``cc`` and ``bcc`` for a single message.

Links to other tickets, assets and URLs are added and deleted one at a time, keeping the other links of the ticket
(RT 5.0.1 or newer)::

    c.tickets.edit_link(ticket_id, 'DependsOn', 7)
    c.tickets.edit_link(ticket_id, 'RefersTo', 'asset:3')
    c.tickets.edit_link(ticket_id, 'RefersTo', 'https://wiki.example.com/printers')
    c.tickets.edit_link(ticket_id, 'DependsOn', 7, delete=True)
    for link in c.tickets.get_links(ticket_id):
        print(link['ref'], link['type'], link['_url'])  # e.g. "refers-to external https://wiki.example.com/printers"

Merging a ticket into another one, and deleting a ticket (RT sets its status to *deleted*)::

    c.tickets.merge(ticket_id, 7)
    c.tickets.delete(8)


Messages, History and Attachments
`````````````````````````````````
The messages of a ticket (its creation, replies and comments) with their text and author, oldest first, in one
request per 100 messages::

    for message in c.tickets.messages(ticket_id):
        print(message['Created'], message['Creator']['Name'], message['Type'], message['Content'])

All transactions of a ticket, also e.g. status changes, are returned by ``tickets.history()``, a single
transaction by ``get_transaction()``. Transactions are searched, also across tickets, with conditions or a
TransactionSQL query (RT 5.0.2 or newer)::

    c.tickets.search_transactions(raw_query="Type = 'Comment' AND Created > '2024-01-01'", fields=['Type', 'Content'])

The files attached to a ticket, and the content of a file (RT returns it base64 encoded)::

    import base64

    for attachment in c.tickets.get_attachments(ticket_id):
        print(attachment['id'], attachment['Filename'], attachment['ContentType'], attachment['ContentLength'])
        content = base64.b64decode(c.tickets.get_attachment(attachment['id'])['Content'])

The files of a single reply or comment, e.g. of a message returned by ``tickets.messages()``::

    c.tickets.get_attachments(ticket_id, search_params=[{'field': 'TransactionId', 'value': message['id']}])

Files are searched across all tickets, e.g. by name, content type or creation time (RT only returns those the user
is allowed to see)::

    c.tickets.search_attachments(search_params=[{'field': 'ContentType', 'value': 'application/pdf'},
                                                {'field': 'Created', 'operator': '>', 'value': '2024-01-01'}])


Searching Tickets
`````````````````
``tickets.search()`` returns an iterator over the matching tickets. Conditions are passed as keyword arguments, which are
combined with ``AND``::

    for ticket in c.tickets.search(queue='General', Status='open', Owner='Nobody'):
        print(ticket['id'], ticket['Subject'])

Custom fields are searched with the prefix ``CF_``, e.g. ``CF_Severity='High'``.

Conditions can also be passed as a mapping with ``conditions``, e.g. for field names which are not valid Python
identifiers or conditions built at runtime. Unlike unpacking a dictionary with ``**``, this is accepted by type
checkers like mypy. Both forms can be combined, but a condition must not be given in both::

    c.tickets.search(queue='General', conditions={'CF_Contact Email': 'a@example.com', 'Requestor.EmailAddress': 'b@example.com'}, Status='open')

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

    c.tickets.search(queue='General', Status='open', Priority__gte=50, Resolved__is=None)

All values are quoted, so they can not change the meaning of the query; field names other than plain names like
``Subject`` or ``Requestor.EmailAddress`` are quoted as well, e.g. ``conditions={'CustomRole.{Manager}': 'alice'}``.

A complete TicketSQL query can be passed with ``raw_query`` instead of conditions (``queue`` and ``order`` can still
be used); it is passed to RT as is, so it must never contain untrusted input::

    c.tickets.search(queue='General', raw_query="Status = 'new' OR Status = 'open'", order='-Created')

The query is sent in the body of a POST request, so it is not limited by the maximum length of URLs.

The fields returned for each ticket are selected with ``fields``: ``'l'`` (default, many fields),
``'s'`` (ID and subject), ``'i'`` (only the ID), a list of fields, or a dictionary of query parameters::

    c.tickets.search(queue='General', fields=['Subject', 'Status'])

Tickets updated recently, and tickets updated by other users than the one of the connection::

    import datetime

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    for ticket in c.tickets.last_updated(since, queue='General'):
        print(ticket['id'])
    for ticket in c.tickets.new_correspondence(queue='General'):
        print(ticket['id'])

A ``datetime`` with timezone is an exact point in time. Dates, naive datetimes and strings like ``'2024-01-31'``
or ``'2024-01-31 12:00:00'`` are interpreted by RT in the timezone of the RT user.


Queues
``````
Queues are identified by name or ID::

    queue = c.queues.get('General')
    for queue in c.queues.all():
        print(queue['id'], queue['Name'])
    c.queues.search(search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Support'}])

    queue_id = c.queues.create('Support', Description='First level support', SubjectTag='support')
    c.queues.edit('Support', CorrespondAddress='support@example.com', AdminCc='alice')
    c.queues.delete('Support')  # disables the queue


Users and Groups
````````````````
Users are identified by name or ID::

    user = c.users.get('alice')
    c.users.create('bob', 'bob@example.com', RealName='Bob Example', Password='secret', Privileged=1)
    c.users.edit('bob', Organization='Example Inc.', Disabled=0)
    c.users.exists('bob', privileged=False)
    c.users.delete('bob')  # disables the user

Users and groups are searched with conditions like the ones of assets (all if none are given), e.g. the privileged
users of a domain::

    c.users.search(search_params=[{'field': 'EmailAddress', 'operator': 'LIKE', 'value': '@example.com'}],
                   privileged=True)

Groups are identified by their ID, as RT does not support group names in most requests. Members are added
one at a time, by name to a group or by ID (of a user or group) as member of a group::

    group_id = c.groups.create('Staff', Description='Support staff')
    c.users.add_to_group('alice', group_id)
    c.groups.add_member(group_id, 42)
    for member in c.groups.get_members(group_id, recursive=True):
        print(member['type'], member['id'])


Custom Fields
`````````````
Creating a custom field for tickets with selectable values and applying it to queues::

    cf_id = c.custom_fields.create('Severity', 'Select', 'RT::Queue-RT::Ticket', MaxValues=1)
    c.custom_fields.add_value(cf_id, 'High', SortOrder=1)
    c.custom_fields.add_value(cf_id, 'Low', SortOrder=2)
    c.custom_fields.apply(cf_id, queue_id)  # 0 applies it globally, requires RT 6.0.3 or newer

The custom fields applied to a queue::

    c.custom_fields.search(object_type='queue', object_id=queue_id)

Files are set as value of an Image or Binary custom field with an :py:class:`~rt.common.Attachment`, and read
with the ID which is the last part of the ``_url`` of the value in the ticket::

    c.tickets.edit(ticket_id, CustomFields={'Screenshot': Attachment('screen.png', 'image/png', content).to_dict()})
    content = c.custom_fields.get_file(value_id)


Rights
``````
Rights can be managed with RT 6.0.3 or newer. They are granted on a queue, group, class, catalog or custom field,
or globally, to a user (by name or ID) or a group (by ID)::

    c.rights.grant('queue', 'General', 'CreateTicket', group=group_id)
    c.rights.grant('global', None, 'SuperUser', user='alice')
    for right in c.rights.get('queue', 'General', user='alice'):
        print(right['Right'])
    c.rights.revoke('queue', 'General', 'CreateTicket', group=group_id)

``rights.get_available()`` returns the rights which can be granted on an object, grouped by category.
Granting a right which is already granted raises :py:exc:`~rt.exceptions.ConflictError`.

The version of RT and its plugins are returned by ``get_system_info()``.


Assets and Catalogs
```````````````````
Catalogs are created, edited and disabled like queues::

    catalog_id = c.catalogs.create('Laptops', Description='Company laptops')
    c.catalogs.edit('Laptops', Description='All laptops')
    for catalog in c.catalogs.all():
        print(catalog['Name'])

Assets are created in a catalog, edited, and marked as deleted::

    asset_id = c.assets.create('Laptop 42', 'Laptops', Description='ThinkPad', HeldBy='alice')
    c.assets.edit(asset_id, Status='in-use')
    c.assets.delete(asset_id)

Links of assets are added and deleted like the ones of tickets, e.g. to the ticket of a repair::

    c.assets.edit_link(asset_id, 'RefersTo', ticket_id)
    c.assets.edit_link(asset_id, 'Parent', 'asset:5')
    for link in c.assets.get_links(asset_id):
        print(link['ref'], link['type'], link['_url'])

Assets are searched with conditions, or with an AssetSQL query (RT 5.0.2 or newer), which is passed to RT as is::

    c.assets.search(catalog_id=catalog_id, search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Laptop'}])
    c.assets.search(raw_query="Catalog = 'Laptops' AND Status = 'in-use'")

RT ignores an invalid AssetSQL query and then returns all assets.


Articles and Classes
````````````````````
Articles (RT 5.0.1 or newer) belong to a class, their text is stored in the custom field ``Content``::

    class_id = c.classes.create('FAQ', Description='Frequently asked questions')
    article_id = c.articles.create('VPN setup', 'FAQ', Summary='How to set up the VPN',
                                  CustomFields={'Content': 'Install the client ...'})
    for article in c.articles.search(search_params=[{'field': 'Class', 'value': class_id}]):
        print(article['Name'], article['Summary'])

Custom roles are read with ``custom_roles.search()`` and ``custom_roles.get()`` (REST2 can not create or change them).


Async Usage
```````````
``rt.rest2_async.AsyncRt`` provides the same attributes and methods as ``rt.rest2.Rt``, the methods as coroutines. Methods returning
multiple results are async iterators, which are iterated without ``await``::

    import httpx2
    import rt.rest2_async

    async with rt.rest2_async.AsyncRt(url=api_url, http_auth=httpx2.BasicAuth('root', 'password')) as c:
        ticket = await c.tickets.get(1)
        async for ticket in c.tickets.search(queue='General', Status='open'):
            print(ticket['id'])
        tickets = [ticket async for ticket in c.tickets.search(queue='General')]

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
