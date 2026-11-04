# Changelog
All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v3.8.1], 2026-11-04
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
