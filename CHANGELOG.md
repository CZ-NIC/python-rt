# Changelog
All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Migration guide
This release contains breaking changes. Most code only needs the adaptations below; the entries in the following
sections describe all changes in detail.

Python 3.11 or newer is required.

#### Exceptions
- `rt.exceptions.ConnectionError` was renamed to `rt.exceptions.RtConnectionError`. Code catching the builtin
  `ConnectionError` keeps working, as `RtConnectionError` is a subclass of it:
  ```python
  # before
  except rt.exceptions.ConnectionError: ...
  # after
  except rt.exceptions.RtConnectionError: ...
  ```
- REST2 raises `rt.exceptions.UnexpectedResponseError` instead of `json.JSONDecodeError` for responses which are not
  valid JSON.
- REST2 raises `rt.exceptions.NotAllowedError` instead of `UnexpectedResponseError` if RT answers with HTTP status 403,
  i.e. if the user does not have the rights for a request.
- REST2 raises `rt.exceptions.InvalidUseError` instead of `ValueError` for invalid arguments. `InvalidUseError` is a
  subclass of `ValueError`, so `except ValueError` keeps working.

#### REST1
- Pass all constructor arguments by keyword, as well as `cc`, `bcc`, `content_type` and `files` of `reply()`/`comment()`:
  ```python
  # before
  tracker = rt.rest1.Rt('https://rt.example.com/REST/1.0/', 'user', 'password')
  tracker.reply(1, 'Hello', 'cc@example.com')
  # after
  tracker = rt.rest1.Rt(url='https://rt.example.com/REST/1.0/', default_login='user', default_password='password')
  tracker.reply(1, 'Hello', cc='cc@example.com')
  ```
- *httpx2* replaces *requests*: use the httpx2 authentication classes, and `Rt.session` is an `httpx2.Client`:
  ```python
  # before
  rt.rest1.Rt(url=url, http_auth=requests.auth.HTTPBasicAuth('user', 'password'))
  # after
  rt.rest1.Rt(url=url, http_auth=httpx2.BasicAuth('user', 'password'))
  ```
- Credentials in `.netrc` files are no longer used automatically, redirects are not followed, requests time out
  after 20 seconds (`http_timeout=None` disables the timeout) and files to attach must be bytes or binary file objects.

#### REST2
- Import `AsyncRt` from `rt.rest2_async` and pass all constructor arguments by keyword (also for `Rt`):
  ```python
  # before
  tracker = rt.rest2.AsyncRt('https://rt.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('user', 'password'))
  # after
  import rt.rest2_async
  tracker = rt.rest2_async.AsyncRt(url='https://rt.example.com/REST/2.0/', http_auth=httpx2.BasicAuth('user', 'password'))
  ```
- The sync `get_ticket_history()`, `get_attachments()`, `get_attachments_ids()` and `get_all_queues()` return iterators
  instead of lists; wrap them in `list()` if a list is needed:
  ```python
  history = list(tracker.get_ticket_history(ticket_id))
  ```
- The async `new_correspondence()` and `last_updated()` are iterated without `await`:
  ```python
  # before
  async for ticket in await tracker.last_updated('2024-01-01'): ...
  # after
  async for ticket in tracker.last_updated('2024-01-01'): ...
  ```
- `search()` quotes and escapes all values, so remove any manual escaping of quotes in values (`raw_query` is still
  passed to RT as is). Unknown operator suffixes (e.g. `Subject__likee`) raise `InvalidUseError`, and a field name
  containing `__` needs an explicit operator, e.g. `CF_my__field__exact='value'`.
- `reply()` and `comment()` raise `InvalidUseError` for a `content_type` other than `text/plain` or `text/html`.
- `http_auth` and `token` can not be combined anymore.
- Pass all optional arguments by keyword, e.g. `queue` of `search()`/`last_updated()`, `delete` of `edit_link()`,
  `privileged` of `user_exists()` and all arguments of `search_assets()`. Only `content` of `reply()`/`comment()` can
  still be passed by position:
  ```python
  # before
  tracker.search_assets(1, [{'field': 'Name', 'value': 'Laptop'}])
  tracker.create_ticket('General', 'text/plain', 'Subject')
  # after
  tracker.search_assets(catalog_id=1, search_params=[{'field': 'Name', 'value': 'Laptop'}])
  tracker.create_ticket('General', subject='Subject')
  ```
- The parameter `query_format` of `search()`, `get_ticket()`, `get_asset()`, `get_attachments()` and `search_assets()`
  was renamed to `fields`. A remaining `query_format=` in `search()` is sent to RT as search condition, which RT rejects
  with `BadRequestError: Unknown field: query_format`.
- Methods changing something return the status messages of RT (`list[str]`) instead of `True`/`False`, and raise an
  exception if RT refuses the change:

  | Method | Before | After |
  |---|---|---|
  | `edit_ticket()`, `edit_asset()`, `edit_link()` | `True` | status messages (empty list if nothing changed) |
  | `reply()`, `comment()` | `True` | status messages, e.g. `['Correspondence added']` |
  | `take()`, `untake()`, `steal()` | `False` if RT refused | status messages; `InvalidUseError` (or `NotAllowedError` for "Permission Denied") if RT refused |
  | `merge_ticket()` | `False` if RT refused | status messages; `NotFoundError` if the destination ticket does not exist, else `InvalidUseError`/`NotAllowedError` |
  | `edit_link()` | `True` if RT could not create or delete the link | `InvalidUseError`, e.g. for a link from a ticket to itself |

  ```python
  # before
  if not tracker.take(ticket_id): ...
  # after
  try:
      tracker.take(ticket_id)
  except rt.exceptions.InvalidUseError: ...
  ```
  Code testing the result with `if tracker.edit_ticket(...)` must be changed, as an empty list (nothing changed) is false.
- `new_correspondence()` only returns tickets last updated by other users than the one of the connection, as documented
  (before, it returned all tickets).
- The type aliases `TYPE_VALID_TICKET_LINK_NAMES` and `TYPE_CONTENT_TYPE` were renamed to `TicketLinkName` and `ContentType`.
- `Attachment` is immutable; create a modified copy with `dataclasses.replace(attachment, file_name='new.txt')`.
- The `base_url` attribute was removed; use `tracker.url.removesuffix('REST/2.0/')` if needed.

### Changes
- **Breaking:** Remove support for Python 3.10, which reached its end of life; Python >= 3.11 is required.
- **Breaking:** Replace *requests* with *httpx2* for the REST1 part; *requests* is no longer a dependency.
  - `Rt.session` is now an `httpx2.Client` instead of a `requests.Session`.
  - `http_auth` expects an `httpx2.Auth` instance (e.g. `httpx2.BasicAuth`, `httpx2.DigestAuth`).
  - `verify_cert` accepts `True`/`False` or the path to a CA bundle file.
  - Credentials from `.netrc` files are no longer used automatically.
  - Redirects are no longer followed.
  - Responses are decoded using the charset sent by RT (UTF-8 if none); undecodable bytes are replaced instead of raising.
  - Files to attach must be passed as bytes or binary file objects.
  - Requests time out after 20 seconds by default.
- **Breaking:** Split the REST2 sync and async implementations: `AsyncRt` moved to `rt.rest2_async`
  (use `rt.rest2_async.AsyncRt` instead of `rt.rest2.AsyncRt`).
  `rt.rest2` is now generated from `rt.rest2_async` using *unasyncd*.
- **Breaking:** The sync REST2 methods `get_ticket_history`, `get_attachments`, `get_attachments_ids` and `get_all_queues`
  now return iterators, like their async counterparts, instead of lists. Wrap them in `list()` if a list is needed.
  Errors (e.g. for a non-existent ticket) are raised when iterating instead of when calling the method.
- Move the REST2 `Attachment` class to `rt.common`; it is still available as `rt.rest2.Attachment` and `rt.rest2_async.Attachment`.
- **Breaking:** `AsyncRt.new_correspondence()` and `AsyncRt.last_updated()` return async iterators directly, like all other
  methods returning multiple results: use `async for ticket in tracker.last_updated(...)` without `await`.
- **Breaking:** Values passed to the REST2 `search()` (including the queue name and the date of `last_updated()`) are now
  quoted and escaped, so they can not change the meaning of the query (TicketSQL injection). Values which were escaped
  manually before must not be escaped anymore. `raw_query` is still passed to RT as is.
- **Breaking:** REST2 clients raise `InvalidUseError` (a `ValueError`) if both `http_auth` and `token` are specified.
- **Breaking:** REST2 `search()` raises `InvalidUseError` for an unsupported operator suffix (e.g. `Subject__likee`),
  which was silently treated as `=` before. A field name containing `__` must be followed by an operator,
  e.g. `CF_my__field__exact='value'`.
- **Breaking:** REST2 `reply()` and `comment()` raise `InvalidUseError` (a `ValueError`) for a `content_type` other
  than `text/plain` or `text/html` before sending the request, like `create_ticket()` already did.
- **Breaking:** All parameters of the REST1 `Rt` constructor are keyword-only,
  e.g. `Rt(url='https://rt.example.com/REST/1.0/', default_login=..., default_password=...)`.
- **Breaking:** Rename the type aliases `TYPE_VALID_TICKET_LINK_NAMES` to `TicketLinkName` and `TYPE_CONTENT_TYPE`
  to `ContentType`.
- **Breaking:** `Attachment` is immutable (frozen dataclass with slots).
- **Breaking:** All parameters of the REST2 `Rt`/`AsyncRt` constructors are keyword-only,
  e.g. `Rt(url='https://rt.example.com/REST/2.0/', http_auth=...)`.
- **Breaking:** Remove the unused `base_url` attribute of the REST2 `Rt`/`AsyncRt` classes.
- **Breaking:** Rename `rt.exceptions.ConnectionError` to `rt.exceptions.RtConnectionError`, so it no longer shadows the
  builtin `ConnectionError`. It is now raised for connection and transport errors in REST1 and REST2 (before, the builtin
  `ConnectionError` was raised). As it is a subclass of both `RtError` and the builtin `ConnectionError`, existing
  `except ConnectionError` code keeps working.
- **Breaking:** The parameters `cc`, `bcc`, `content_type` and `files` of the REST1 `reply()` and `comment()` are keyword-only.
- REST2 raises `UnexpectedResponseError` instead of `json.JSONDecodeError` if RT (or a proxy in between) returns an invalid
  JSON response, e.g. an HTML login page.
- REST2 debug logging no longer contains credentials (the `Authorization` header is redacted, request bodies are not logged)
  and is only prepared if debug logging is enabled.
- REST2 requests 100 items per page (the maximum supported by RT) instead of 20 for paginated results by default,
  which reduces the number of requests. The page size can be set with the new `per_page` constructor parameter.
- The package is now type checked with `mypy --strict`. Type hints are more precise, which may require adaptations
  in code that is type checked as well (runtime behaviour is unchanged):
  - REST2: values passed as `**kwargs` to create/edit methods are typed as JSON data (`rt.common.JSONInput`), query
    parameters as `rt.common.QueryParams`. Returned RT objects stay `dict[str, Any]`.
  - REST1: return types are concrete instead of `dict`, e.g. `search()` returns `list[dict[str, str | Sequence[str]]]`.
    Ticket fields passed to `create_ticket()`/`edit_ticket()` are typed `str | list[str] | tuple[str, ...]`, which are
    the only types these methods ever supported. Files to attach are typed `rt.rest1.FileTuple`.
- REST2 validates the content of responses (e.g. status messages must be strings, created objects must have an ID)
  and raises `UnexpectedResponseError` instead of failing later with an unrelated error.
- **Breaking:** REST2 methods changing something return the status messages of RT as `list[str]`: `edit_ticket()`,
  `edit_asset()`, `edit_link()`, `reply()`, `comment()`, `take()`, `untake()`, `steal()` and `merge_ticket()`
  (before `bool`; `edit_user()` and `edit_queue()` already returned the messages).
- **Breaking:** REST2 `take()`, `untake()`, `steal()` and `merge_ticket()` raise an exception if RT refuses the action
  instead of returning `False`: `InvalidUseError` (e.g. "That user already owns that ticket"), `NotAllowedError` for
  "Permission Denied", and `NotFoundError` if the destination ticket of a merge does not exist.
- **Breaking:** All optional parameters of the REST2 methods are keyword-only (except `content` of `reply()` and
  `comment()`). The parameters of `create_ticket()` are ordered `queue, *, subject, content, content_type, attachments`.
- **Breaking:** Rename the REST2 parameter `query_format` to `fields` in `search()`, `get_ticket()`, `get_asset()`,
  `get_attachments()` and `search_assets()`.
- **Breaking:** REST2 raises `NotAllowedError` for HTTP status 403 (before `UnexpectedResponseError`), with the message
  sent by RT, e.g. "No permission to create tickets in the queue 'General'". This also applies to `create_asset()`
  with a catalog that does not exist, for which RT answers with 403.
- **Breaking:** `InvalidUseError` is a subclass of both `RtError` and the builtin `ValueError`. REST2 raises it instead
  of `ValueError` for invalid arguments, so all errors are `RtError`s, while `except ValueError` keeps working.
- All exceptions have the attributes `status_code` and `response_message` (before only `UnexpectedResponseError`).
  REST2 sets them for all errors caused by an HTTP response of RT; otherwise they are `None`.
### Fixed
- REST2: IDs and names used in URLs (e.g. user or queue names) are percent-encoded, so they can no longer change
  the requested endpoint. Previously e.g. `get_user('../ticket/1')` returned ticket 1, and names containing `?` or `#`
  were truncated.
- REST2 `search()` with custom fields (`CF_<name>=...`) created a malformed query and always failed.
- REST2 `search()` failed for values containing a single quote.
- REST2 `edit_ticket()` did not detect non-existent users or queues for many names (e.g. queue "Support").
- REST2 paginated results: no `NotFoundError` anymore for empty results of users who are not allowed to see all results
  (RT >= 5.0.5), no more missing results after a page whose items are all hidden from the user, and no more duplicate
  results if items are deleted while iterating.
- REST2 `search_assets()` modified the `search_params` list passed by the caller.
- REST2 `last_updated()` accepted invalid dates like 2024-02-30.
- REST2 delete operations treated a non-JSON response other than "204 No Content" (e.g. an HTML page returned by a proxy)
  as success.
- REST2 `edit_link()` returned `True` if RT could not create or delete the link, e.g. a link from a ticket to itself.
- REST2 `new_correspondence()` returned all tickets instead of only those last updated by other users than the one of
  the connection, as documented (and as implemented in REST1).
### Added
- Add an `http_timeout` parameter to the REST1 `Rt` class.
- REST2 clients accept an own HTTP client via the new `client` constructor parameter (an `httpx2.Client` for `Rt`,
  an `httpx2.AsyncClient` for `AsyncRt`), e.g. configured with a custom transport, retries, event hooks or HTTP/2.
  It can not be combined with `proxy`, `verify_cert`, `http_auth`, `token` and `http_timeout`, and it is not closed
  by `close()`/`aclose()`, as it is owned by the caller.
- REST2 `last_updated()` accepts `datetime.date` and `datetime.datetime` objects. A `datetime` with timezone is
  converted to UTC and therefore an exact point in time; dates and naive datetimes (like strings) are interpreted by
  RT in the timezone of the RT user.
- Add `rt.common.SearchFormat` for the `fields` values `'i'`, `'s'` and `'l'` of the REST2 `search()`.
- Add `rt.common.VALID_CONTENT_TYPES`. It and `VALID_TICKET_LINK_NAMES` are derived from the corresponding `Literal` types,
  so the type hints and the checks at runtime can not differ.
- REST2 `search()` supports the TicketSQL operators `__gte` (>=), `__lte` (<=), `__startswith`, `__notstartswith`,
  `__endswith`, `__notendswith`, `__is` and `__isnot` (the latter two with the value `None`, e.g. `Resolved__isnot=None`).
- REST2 `search()` accepts the conditions as a mapping with the new `conditions` parameter, e.g.
  `search(conditions={'CF_Contact Email': 'a@example.com'})`. Unlike unpacking a dictionary into the keyword arguments
  (`search(**conditions)`), which mypy rejects as the values may be passed to the other parameters, this is type-safe.
  Conditions as keyword arguments continue to work and can be combined with it.
- REST2 clients can be closed with `close()` (sync) / `aclose()` (async) or used as (async) context manager to close
  the underlying HTTP connections.

## [v3.8.2], 2026-11-04
### Fixes
- Fix the REST2 search() with custom fields (CF_<name>=...), which created a malformed query with an unmatched single quote (#128 thanks @Goggin).

## [v3.8.0], 2026-07-20
### Changes
- Switch from the seemingly unmaintained httpx library to the actively maintained fork, httpx2.

## [v3.7.1], 2026-07-02
### Added
- Add a query_format parameter to sync/async get_attachments methods (#120 thanks @nazywam).

## [v3.7.0], 2026-06-29
### Removed
- Remove support for now EoL Python 3.9.
- Modernise typing due to raised minimum Python version.

## [v3.6.1], 2026-06-29
### Fixes
- Fix API doc on search() to correctly document the queue parameter in case you want to query all queues (thanks @p-fruck #121)

## [v3.6.0], 2026-02-06
### Added
- Parameters search_params and catalog_id used in asset search are now optional
- If catalog_id is set to None, search all catalogs

## [v3.5.0], 2026-02-04
### Added
- Added option to define all query parameters for get/search asset and ticket endpoints
- Fixed typing of methods that returned a partially unknown dictionary

## [v3.4.0], 2025-11-21
### Added
- Added functionality for some of the asset endpoints (get, create, edit, search, get history)
- Added functionality for the get catalog endpoint

## [v3.3.9], 2025-10-01
### Fixes
- In debug mode, where content may be dumped, said content may not decode correctly if it is not utf-8. Ignore errors as we don't care about that in debug mode anyways (fixes #113)

## [v3.3.8], 2025-09-25
### Added
- Allow for specifying a custom RT JSON filter when querying for attachments for a ticket (#110). This solved the issue with not returning attachment IDs in
    case an attachment file name is empty as the default query explicitely excludes those.
### Changes
- Remove unused noqa directives
- Do not use len() in asset when no comparison is being done
- Add quotes to type expression in `typing.cast()`

## [v3.3.7], 2025-09-24
### Changes
- Use RT v6 based docker image for tests
### Fixes
- Fix optional return types (#111)

## [v3.3.6], 2025-04-24
### Fixes
- Catch *TransportError* from httpx and re-raise as *ConnectionError* so that httpx transport error exceptions do not leak (fixes #109).

## [v3.3.5], 2025-04-18
### Fixes
- There was still a comparison issue, fix bad date comparison (fixes #107)

## [v3.3.4], 2025-03-03
### Fixes
- Fix bad date comparison (fixes #107)

## [v3.3.3], 2024-12-02
### Changes
- Starting with version 0.28.0 of httpx, *verify* should be either a bool or an *SSL Context*.

## [v3.3.2], 2024-12-02
### Fixes
- Replace the removed httpx parameter of *proxies* by *proxy* (fixes #102)
- Pin dependencies to supported relative upstream versions.
- Remove the now obsolete *setup.py*.

## [v3.3.1], 2024-11-14
### Fixes
- Fix str(bytes) warning (*BytesWarning: str() on a bytes instance*) (#1074)

### Changes
- Set included files for ruff
- Switch to hatchling
- Set ignores for tests files
- Ignore uv.lock

## [v3.3.0], 2024-10-04
### Removed
- Remove support for now EoL Python 3.8.

## [v3.2.0], 2024-09-06
### Added
- Added option for custom list of fields to be populated for search "query_format" param to avoid unnecessary round trips to get fields like Told, Starts, Resolved, etc by returning the required fields during search. (see #97 @nerdfirefighter)

## [v3.1.4], 2024-02-16
### Fixes
- Add a workaround for a breaking change introduced in RT5.0.5 which returns undefined pages variable for non-superusers (see #93 #94).

## [v3.1.3], 2023-10-10
### Fixes
- Fix an issue where no e-mail was sent on ticket creation due to suggesting to use **Requestors** instead of **Requestor** (https://github.com/python-rt/python-rt/pull/92).

## [v3.1.2], 2023-09-25
### Fixes
- Revert breaking change for python3.8 (collections.abc.AsyncIterator is not subscriptable).

## [v3.1.1], 2023-09-25
### Fixes
- In AsyncRt, instead of returning sequences, return AsyncIterators.

## [v3.1.0], 2023-09-25
### Changes
- Replace *requests* with *httpx* for the REST2 part.

### Added
- Add a new *AsyncRt* class which implements the RT REST2 API in asnyc.
- Adapt tests to include thew new async parts of this library.

## [v3.0.7], 2023-07-27
### Fixes
- Fix sorting when using search() method (#90)

## [v3.0.6], 2023-06-21
### Fixes
- Fixed bug in rest1 (#86)

## [v3.0.5], 2023-02-02
### Added
- Added support for specifying custom fields on user creation/edit (#82).

## [v3.0.4], 2022-11-08
### Fixes
- Workaround for parsing issues with tickets with only 1 attachment (#80), due to probably an upstream bug.

## [v3.0.3], 2022-06-16
### Changes
- Move package metadata and configuration from setup.cfg to pyproject.toml.

## [v3.0.2], 2022-06-12
### Fixes
- Fix edit_user() response handling in case a user_id name (str) was passed instead of a number.

## [v3.0.1], 2022-05-26
### Fixes
- Make sure to include _hyperlinks in history items
- On edit ticket, raise exception if user/queue does not exist

### Added
- Add helper method for deleting tickets
- Add tests

## [v3.0.0], 2022-05-17
The following is a major release of the `rt` library.
There is support for the REST API version 1 as well as version 2.
Please note that this release contains breaking changes and requires adaptations to existing code, even if you are
sticking to version 1 of the API.
These changes were necessary in order to properly support both API versions.

### Added
- RT REST2 support was added and is mostly on par with the REST1 support (differences are a result of the REST2 API implementation differences in RT).
REST2 is a modern API based on JSON exchanges and thus the complex parsing of responses and request construction are no longer needed.

### Changes
- Existing exception classes were renamed to adhere to the naming convention (https://peps.python.org/pep-0008/#exception-names).
  - In case you do catch specific `rt` exceptions, a simple search/replace will do, see the changelog page in the documentation for details.
- Importing the `rt` class changed in order to better accommodate the new `rest2` implementation.
  - Where one use to be able to import `rt` using:
    `from rt import Rt`

    you now have to use the following syntax:

    `from rt.rest1 import Rt`
- Importing the `rt` module does no longer import all exceptions but only the core `RtError` exception.
If you require other exceptions, please import them from `rt.exceptions`.
- Use pytest instead of nose.

## [v2.2.2], 2022-04-08
- Fix bug in the get_ticket would omit certain fields in case they were empty instead of returning an empty list as was the previous behavior (#70).
- Add tests for verifying correct return result for AdminCc, Cc and Requestor fields.

## [v2.2.1], 2021-11-26
- Fix bug in get_attachment_content which was a workaround for a bug in RT <=4.2 (trailing new-lines) but which was fixed in RT >=4.2. This made tests fail and return falsely stripped attachment content.

## [v2.2.0], 2021-11-15
- Search has a parameter fields that can be used to return only particular fields for tickets. In some cases I noticed it will improve the speed of the query completion if you only need specific fields (#65 by @kimmoal).

## [v2.1.1], 2021-03-23
- Fix support for custom field values containing newlines in API responses (#10, #11)
  (the previous change in v1.0.11 fixed API requests) (#64)

## [v2.1.0], 2021-02-25
- Add the possibility to provide cookies as dict to authenticate (#60)
- Add 'Referer' header for CSRF check when cookies are used for authentication (#60)
- Add IS and IS NOT operators to search (#57)

## [v2.0.1], 2020-08-07
- Fix UnicodeDecodeError in logging code for non-text attachments (#50, #51)
- Documentation: Add a search example (#49)
- edit_ticket: Handle possible empty responses: When a ticket is not modified, at least with RT 4.x, an empty
  response could be returned. Gracefully handle that as success. (#47, #48)

## [v2.0.0], 2020-02-11
- Drop Python2 support
- Adjust Travis tests for Python3-only, and add v3.8
- Add inline typing
- Remove "debug_mode" parameter
- Add "logging" support (basically replacing "debug_mode" and the various "print"s)
- Fix "no-else-after-return" and "no-else-after-raise"
- Fix "startswitch" typos / bugs
- Removed deprecated "basic_auth" and "digest_auth" parameters. The same functionality is given by specifying the
  "http_auth" with an instance of either object. This allows for more flexibility with various other alternative
  authentication methods.

## [v1.0.13], 2020-02-06
- Add deprecation warning for in the next major release unsupported parameters (basic_auth, digest_auth).
  They are now replaced with http_auth.
- Fix problematic default method parameters ("{}" and "[]").

## [v1.0.12], 2019-10-25
- Travis CI Docker tests
- RT 4.4 fixes
- Support multiline CF values in create_ticket and edit_ticket.
- Fix support for custom field names containing colons
- In search(), replace splitlines() with lines array split on \n.
- Add debug_mode flag for response logging
- Add platform independent url joining / Allow testing on Windows
- Add numerical_id to get_ticket result

## [v1.0.11], 2018-07-16
- Added parameter to set the content type in reply() and comment() (#12).
- Added parameter Format to search() (#17).
- Tests: Update to new demo instance, fixing tests.
- Tests: Disable tests in Travis, the existing test instance closed the REST interface (#28).
- Fix support for custom field names containing colons (#37).
- Fix support for custom field values containing newlines (#11).

## [v1.0.10], 2017-02-22
- PEP8 fixes
- update .travis.yml to update python interpreter list and some other small changes
- prefer format over % (PEP 3101)
- Add patch from https://gitlab.labs.nic.cz/labs/python-rt/issues/9
  "Support CF search where special chars or spaces in CF names"
- Implement a fix for the issue suggested in
  https://gitlab.labs.nic.cz/labs/python-rt/issues/10 (can't create ticket
  with multi-line message)
- Implement fix for https://gitlab.labs.nic.cz/labs/python-rt/issues/7
  "returned types inconsistent in get_ticket"
  Add splitting for Cc and AdminCc

## [v1.0.9], 2016-06-22
- added ability to steal, untake, and explicitly take tickets
- fixed create_ticket return value when provided an invalid custom field

## [v1.0.8], 2014-05-29
- added ability to search all queues
- added RtError super class
- fixed compatibility issues with Python 2.6

## [v1.0.7], 2013-10-01
- unit tests
- own exceptions
- added create_user, create_queue, edit_user, edit_queue methods
- added edit_link (replaces buggy edit_ticket_links)
- added get_attachments, get_short_history methods
- support merge_ticket in RT4
- custom query to search method
- strict binary handling with attachments

## [v1.0.6], 2013-09-05
- added support for HTTP basic and digest authentication
- specification of errors to different exceptions

## [v1.0.5], 2013-04-26
- fixed decoding of utf-8 only when needed
- updated search function to support various
  lookup operators and sorting

## [v1.0.4], 2013-03-21
- default queue added to init parameters

## [v1.0.3], 2013-03-06
- python-requests 1.x compatible

## [v1.0.2], 2013-02-18
- HTTP proxy support
- Support for multilinks in get_links

## [v1.0.1], 2013-01-10
- Updated docstrings
- Added Sphinx documentation

## [v1.0.0], 2012-08-03
- Initial release
