"""Tests for code shared by the REST2 clients (rt.common) and for rt.exceptions, which need no RT server."""

# ruff: noqa: S101, SLF001

import builtins

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
        ('That user does not exist', True),
        ('Ticket 1: That user does not exist', True),
        ('Ticket 1: Queue Support does not exist', True),
        ('Queue Does Not Exist Desk does not exist', True),
        ('Resource does not exist', True),
        ("Ticket 1: Subject changed from 'a' to 'user does not exist'", False),
        ('Ticket 1: Queue changed from General to Support', False),
        ('Owner changed from Nobody to root', False),
    ],
)
def test_does_not_exist_pattern(message: str, expected: bool):
    assert bool(rt.common.REGEX_PATTERNS['does_not_exist'].search(message)) is expected


# --- constants derived from types ------------------------------------------------------------------------------------


def test_valid_values():
    assert rt.common.VALID_TICKET_LINK_NAMES == ('Parent', 'Child', 'RefersTo', 'ReferredToBy', 'DependsOn', 'DependedOnBy')
    assert rt.common.VALID_CONTENT_TYPES == ('text/plain', 'text/html')


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
        rt.rest1.Rt('http://localhost:8080/REST/1.0/')  # type: ignore[misc]
