"""Tests for code shared by the REST2 clients (rt.common) and for rt.exceptions, which need no RT server."""

# ruff: noqa: S101, SLF001

import builtins
import dataclasses

import pytest

import rt.common
import rt.exceptions
import rt.rest1

from .conftest import RT_PASSWORD, RT_USER

# --- search query building -----------------------------------------------------------------------------------------


def test_build_ticket_query():
    assert rt.common._build_ticket_query(None, None, {}) == ''
    assert rt.common._build_ticket_query('General', None, {}) == "(Queue='General')"
    assert rt.common._build_ticket_query("Gen'eral", None, {'Subject': 'a\\b'}) == "(Queue='Gen\\'eral') AND (Subject='a\\\\b')"
    assert rt.common._build_ticket_query(None, None, {'Subject__like': 'x', 'Priority__gte': 5}) == "(Subject LIKE 'x') AND (Priority>='5')"
    assert rt.common._build_ticket_query(None, None, {'CF_My Field': "it's"}) == "('CF.{My Field}'='it\\'s')"
    assert rt.common._build_ticket_query(None, None, {'CF_my__field__exact': 'x'}) == "('CF.{my__field}'='x')"
    assert rt.common._build_ticket_query(None, None, {'Resolved__is': None, 'Told__isnot': 'null'}) == '(Resolved IS NULL) AND (Told IS NOT NULL)'

    # the raw query is used as is and the conditions are ignored
    assert rt.common._build_ticket_query('General', "Status = 'open'", {'Subject': 'x'}) == "(Queue='General') AND (Status = 'open')"


@pytest.mark.parametrize(
    ('operator', 'expected'),
    [
        ('exact', "(Subject='x')"),
        ('notexact', "(Subject!='x')"),
        ('gt', "(Subject>'x')"),
        ('gte', "(Subject>='x')"),
        ('lt', "(Subject<'x')"),
        ('lte', "(Subject<='x')"),
        ('like', "(Subject LIKE 'x')"),
        ('notlike', "(Subject NOT LIKE 'x')"),
        ('startswith', "(Subject STARTSWITH 'x')"),
        ('notstartswith', "(Subject NOT STARTSWITH 'x')"),
        ('endswith', "(Subject ENDSWITH 'x')"),
        ('notendswith', "(Subject NOT ENDSWITH 'x')"),
    ],
)
def test_build_ticket_query_operators(operator: str, expected: str):
    assert rt.common._build_ticket_query(None, None, {f'Subject__{operator}': 'x'}) == expected


def test_build_ticket_query_invalid():
    with pytest.raises(rt.exceptions.InvalidUseError, match='likee'):
        rt.common._build_ticket_query(None, None, {'Subject__likee': 'x'})
    with pytest.raises(rt.exceptions.InvalidUseError, match='None'):
        rt.common._build_ticket_query(None, None, {'Resolved__is': '2024-01-01'})


def test_search_fields_params():
    assert rt.common._search_fields_params('i') == {}
    assert rt.common._search_fields_params('s') == {'fields': 'Subject'}
    assert rt.common._search_fields_params('l') == {'fields': rt.common._SEARCH_LONG_FORMAT_FIELDS, 'fields[Queue]': 'Name'}
    assert rt.common._search_fields_params(['Subject', 'Status']) == {'fields': 'Subject,Status'}
    assert rt.common._search_fields_params({'fields': 'Owner', 'fields[Owner]': 'Name'}) == {'fields': 'Owner', 'fields[Owner]': 'Name'}


def test_fields_params():
    assert rt.common._fields_params(None, 'A,B') == {'fields': 'A,B'}
    assert rt.common._fields_params('C', 'A,B') == {'fields': 'C'}
    assert rt.common._fields_params(['C', 'D'], 'A,B') == {'fields': 'C,D'}
    assert rt.common._fields_params({'fields[Owner]': 'Name'}, 'A,B') == {'fields': 'A,B', 'fields[Owner]': 'Name'}
    assert rt.common._fields_params({'fields': 'C'}, 'A,B') == {'fields': 'C'}


def test_quote_value():
    assert rt.common._quote_value('x') == "'x'"
    assert rt.common._quote_value(5) == "'5'"
    assert rt.common._quote_value("O'Brien \\ x") == "'O\\'Brien \\\\ x'"


# --- URL paths -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('segments', 'expected'),
    [
        (('user', 'root'), 'user/root'),
        (('ticket', 5, 'history'), 'ticket/5/history'),
        (('user', '../ticket/1'), 'user/..%2Fticket%2F1'),
        (('user', '..'), 'user/%2E%2E'),
        (('user', '.'), 'user/%2E'),
        (('queue', 'General Desk'), 'queue/General%20Desk'),
        (('user', 'a?b#c'), 'user/a%3Fb%23c'),
        (('user', '100%'), 'user/100%25'),
    ],
)
def test_path_encoding(segments: tuple, expected: str):
    assert rt.common._path(*segments) == expected


# --- error messages of edit operations -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        # refusals returned by RT 5.0 (verified), by the status of RT, owner, queue, links, merge and groups
        ("Ticket 1: Status 'bogus' isn't a valid status for this ticket.", rt.exceptions.InvalidUseError),
        ('Ticket 1: That user does not exist', rt.exceptions.NotFoundError),
        ('Ticket 1: Queue NoQueue does not exist', rt.exceptions.NotFoundError),
        # names which contain the letters d, o, e and s, or the words of a message
        ('Ticket 1: Queue Support Desk does not exist', rt.exceptions.NotFoundError),
        ('Queue Does Not Exist Desk does not exist', rt.exceptions.NotFoundError),
        ('Queue q: nonexistent is not a valid lifecycle', rt.exceptions.InvalidUseError),
        ("New ticket doesn't exist", rt.exceptions.NotFoundError),
        ("Can't merge a ticket into itself", rt.exceptions.InvalidUseError),
        ("Can't link a ticket to itself", rt.exceptions.InvalidUseError),
        ('Linking to a deleted ticket is not allowed', rt.exceptions.InvalidUseError),
        ('Refused to add link which would create a circular relationship', rt.exceptions.InvalidUseError),
        ("Couldn't resolve 'x' into a link.", rt.exceptions.NotFoundError),
        ('Link could not be created: Permission denied', rt.exceptions.NotAllowedError),
        ('Permission Denied', rt.exceptions.NotAllowedError),
        ('Cannot change Password: Permission Denied', rt.exceptions.NotAllowedError),
        ('That user already owns that ticket', rt.exceptions.InvalidUseError),
        ('You can only steal a ticket owned by someone else', rt.exceptions.InvalidUseError),
        ('You can only untake tickets you own', rt.exceptions.InvalidUseError),
        ('You can only take tickets that are unowned', rt.exceptions.InvalidUseError),
        ('You already own this ticket', rt.exceptions.InvalidUseError),
        ('That user may not own tickets in that queue', rt.exceptions.InvalidUseError),
        ("Couldn't find that principal", rt.exceptions.NotFoundError),
        ('Group already has member: alice', rt.exceptions.InvalidUseError),
        ('CustomField 1: Illegal value for Type', rt.exceptions.InvalidUseError),
        ('Ticket 5: Permission Denied', rt.exceptions.NotAllowedError),
        ("Owner 'x' does not have rights to own this ticket.", rt.exceptions.NotAllowedError),
        ('Custom field 5 not found', rt.exceptions.NotFoundError),
        # not a refusal, also if a value set by a user looks like a refusal
        ("Ticket 1: Subject changed from 'a' to 'Permission Denied'", None),
        ("Ticket 1: Subject changed from 'Invalid x' to 'could not'", None),
        ('Owner changed from Nobody to root', None),
        ('Ticket 1: That is already the current value', None),
        ('Merge Successful', None),
        ('Member added: alice', None),
        ('Custom fields updated', None),
        ('Added custom field Severity to General.', None),
        ('Correspondence added', None),
        ('Link already exists', None),
        ('Link not found', None),
        # successful changes whose messages contain values of users which look like refusals
        ("python-rt Field can't be empty failed added", None),
        ("Field can't be empty failed changed to does not exist", None),
        ("can't be empty is no longer a value for custom field Permission Denied", None),
        ('invalid value added as a value for Field does not exist', None),
        ("Added can't failed as Cc for this ticket", None),
        ('Added failed@example.com as Requestor for this ticket', None),
        ("can't failed is no longer Cc for this ticket", None),
        ('invalid is no longer AdminCc for this queue', None),
        ("Member added: can't failed invalid", None),
        ("Member can't failed deleted", None),
        ("Membership in can't failed added", None),
        ("Ticket 1 refers to URI https://example.com/can't-failed-invalid.", None),
        ('Ticket 1 no longer depends on Ticket 2.', None),
        ('URI https://example.com/failed referred to by Asset 3.', None),
        ("Owner changed from can't to failed", None),
        ("Reference to https://example.com/can't added", None),
        ("Ticket 1: Subject changed from 'a' to 'Permission Denied'", None),
        ('', None),
    ],
)
def test_message_error_type(message: str, expected: type[Exception] | None):
    assert rt.common._message_error_type(message) is expected


def test_raise_for_messages():
    rt.common._raise_for_messages([])
    rt.common._raise_for_messages(["Ticket 1: Subject changed from 'a' to 'b'"])

    # the most specific error is raised, with all refusals in the message
    with pytest.raises(rt.exceptions.NotFoundError, match=r'(?s)(?=.*valid status)(?=.*does not exist)'):
        rt.common._raise_for_messages(["Status 'x' isn't a valid status for this ticket.", "Subject changed from 'a' to 'b'", 'That user does not exist'])

    with pytest.raises(rt.exceptions.NotAllowedError):
        rt.common._raise_for_messages(['Permission Denied', "Status 'x' isn't a valid status for this ticket."])


def test_action_result():
    complete = rt.common.ActionResult(("Ticket 1: Subject changed from 'a' to 'b'",))
    assert complete
    assert complete.complete
    assert complete.refused == ()
    complete.raise_for_refused()

    empty = rt.common.ActionResult(())
    assert empty
    assert empty.complete
    empty.raise_for_refused()


def test_action_result_partial():
    refused = "Ticket 1: Status 'x' isn't a valid status for this ticket."
    result = rt.common.ActionResult(("Ticket 1: Subject changed from 'a' to 'b'", refused))

    # a partial result is true, like a complete one
    assert result
    assert not result.complete
    assert result.refused == (refused,)
    with pytest.raises(rt.exceptions.InvalidUseError, match="isn't a valid status"):
        result.raise_for_refused()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.messages = ()  # type: ignore[misc]


# --- attachments ------------------------------------------------------------------------------------------------------


def test_attachment():
    attachment = rt.common.Attachment('test.txt', 'text/plain', b'content')

    assert attachment.to_dict() == {'FileName': 'test.txt', 'FileType': 'text/plain', 'FileContent': 'Y29udGVudA=='}
    assert attachment.multipart_form_element() == ('test.txt', b'content', 'text/plain')


# --- constants derived from types ------------------------------------------------------------------------------------


def test_valid_values():
    assert rt.common.VALID_TICKET_LINK_NAMES == ('Parent', 'Child', 'RefersTo', 'ReferredToBy', 'DependsOn', 'DependedOnBy')
    assert rt.common.VALID_CONTENT_TYPES == ('text/plain', 'text/html')


# --- exceptions ------------------------------------------------------------------------------------------------------


def test_exceptions():
    # invalid arguments can be caught as builtin ValueError as well as RtError
    assert issubclass(rt.exceptions.InvalidUseError, ValueError)
    assert issubclass(rt.exceptions.InvalidUseError, rt.exceptions.RtError)

    not_found = rt.exceptions.NotFoundError('No such resource found.', status_code=404, response_message='{}')
    assert (str(not_found), not_found.status_code, not_found.response_message) == ('No such resource found.', 404, '{}')

    invalid_use = rt.exceptions.InvalidUseError('Invalid')
    assert (invalid_use.status_code, invalid_use.response_message) == (None, None)


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('Permission Denied', rt.exceptions.NotAllowedError),
        ('That user already owns that ticket', rt.exceptions.InvalidUseError),
        ('You can only steal a ticket owned by someone else', rt.exceptions.InvalidUseError),
        ('You can only untake tickets you own', rt.exceptions.InvalidUseError),
        ('You can only take tickets that are unowned', rt.exceptions.InvalidUseError),
        ('You already own this ticket', rt.exceptions.InvalidUseError),
        ('That user may not own tickets in that queue', rt.exceptions.InvalidUseError),
    ],
)
def test_refusal_error(message: str, expected: type[Exception]):
    error = rt.common._refusal_error(message)
    assert type(error) is expected
    assert str(error) == message


# --- REST1 ---------------------------------------------------------------------------------------------------------------


def test_rest1_connection_error():
    tracker = rt.rest1.Rt(url='http://127.0.0.1:1/REST/1.0/', default_login=RT_USER, default_password=RT_PASSWORD)

    with pytest.raises(rt.exceptions.RtConnectionError) as exc_info:
        tracker.login()

    # can be caught as builtin ConnectionError (as before) as well as RtError
    assert isinstance(exc_info.value, builtins.ConnectionError)
    assert isinstance(exc_info.value, rt.exceptions.RtError)


def test_rest1_init_parameters_are_keyword_only():
    with pytest.raises(TypeError):
        rt.rest1.Rt('http://localhost:8080/REST/1.0/')  # type: ignore[call-arg]


def test_rest1_close_and_context_manager():
    tracker = rt.rest1.Rt(url='http://127.0.0.1:1/REST/1.0/', skip_login=True)
    assert not tracker.session.is_closed
    tracker.close()
    assert tracker.session.is_closed

    with rt.rest1.Rt(url='http://127.0.0.1:1/REST/1.0/', skip_login=True) as context_tracker:
        assert not context_tracker.session.is_closed
    assert context_tracker.session.is_closed
