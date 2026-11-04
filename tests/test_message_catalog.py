"""Tests of the catalog of the status messages of RT (rt/_messages.py).

The messages received from RT in the live tests are checked at the end of the test session by the fixture
``record_messages_of_rt`` in conftest.py.

New messages of a newer RT: ``test_new_messages_of_rt_are_reviewed`` fails for each msgid of the record code of RT
(``lib/RT/``, without the web interface) which is neither in the catalog nor in ``rt_messages_not_in_catalog.json``.
That file maps each reviewed msgid which is not in the catalog to the reason, e.g. a label, a method which changes made
with REST2 do not call (REST2 calls ``RT::Record::Update``, which only calls the ``Set`` methods of writable fields), a
message REST2 answers with an HTTP status instead (creates, deletes, rights), or an internal error of RT. The review of
RT 6.0.4 (2026-11-04) is based on the code at the references of each msgid in ``rt.pot`` and on live tests of all
writable fields; a new msgid has to be reviewed the same way.
"""

# ruff: noqa: S101, S603, SLF001

import json
import pathlib
import re
import shutil
import subprocess

import pytest

import rt._messages
from rt._messages import Kind, classify

RT_IMAGE = 'ghcr.io/python-rt/request-tracker'
RT_POT = '/opt/rt/share/po/rt.pot'
REVIEWED = pathlib.Path(__file__).parent / 'rt_messages_not_in_catalog.json'

# Source files of RT whose messages are no results of changes made with REST2 (web interface, configuration, reports...)
_NOT_STATUS_MESSAGE_SOURCES = (
    'lib/RT/Interface/Web',
    'lib/RT/Config.pm',
    'lib/RT/Dashboard',
    'lib/RT/Graph',
    'lib/RT/Report',
    'lib/RT/Search',
    'lib/RT/Shredder',
    'lib/RT/Test',
)


def _rt_pot() -> dict[str, set[str]]:
    """Return the msgids of the translation file of the RT image used for the tests with their source files, or skip the test."""
    docker = shutil.which('docker')
    if not docker:
        pytest.skip('docker is not available to read share/po/rt.pot of the RT image')

    containers = subprocess.run(
        [docker, 'ps', '--filter', f'ancestor={RT_IMAGE}:6.0', '--format', '{{.ID}}'], capture_output=True, text=True, check=False
    ).stdout.split()
    if not containers:
        pytest.skip(f'no running container of the image {RT_IMAGE}')

    pot = subprocess.run([docker, 'exec', containers[0], 'cat', RT_POT], capture_output=True, text=True, check=False)
    if pot.returncode:
        pytest.skip(f'{RT_POT} can not be read from the container: {pot.stderr}')

    msgids: dict[str, set[str]] = {}
    for entry in pot.stdout.split('\n\n'):
        match = re.search(r'^msgid ((?:"[^\n]*"\n?)+)', entry, flags=re.MULTILINE)
        if not match:
            continue
        msgid = ''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))).replace('\\"', '"')
        sources = {reference.rsplit(':', 1)[0] for line in re.findall(r'^#: (.*)$', entry, flags=re.MULTILINE) for reference in line.split()}
        msgids.setdefault(msgid, set()).update(sources)

    return msgids


def _status_message_candidates(pot: dict[str, set[str]]) -> set[str]:
    """Return the msgids which RT may return as status message of a change made with REST2: those of its record code."""
    return {
        msgid
        for msgid, sources in pot.items()
        if msgid and any(source.startswith('lib/RT/') and not source.startswith(_NOT_STATUS_MESSAGE_SOURCES) for source in sources)
    }


def test_msgids_of_the_catalog_exist_in_rt():
    """RT rewords messages from time to time: a msgid which is not in rt.pot anymore is a message of the catalog which RT does not send."""
    pot = _rt_pot()

    missing = [msgid for msgid in rt._messages.MESSAGES if msgid not in pot]

    assert not missing, f'These messages of the catalog are not in {RT_POT} of the RT image (reworded or removed?): {missing}'


def test_new_messages_of_rt_are_reviewed():
    """A newer RT may return new status messages, which the library would not recognize: list them for review."""
    reviewed = json.loads(REVIEWED.read_text(encoding='utf-8')).keys()

    new = sorted(_status_message_candidates(_rt_pot()) - rt._messages.MESSAGES.keys() - reviewed)

    assert not new, (
        f'{len(new)} message(s) of the record code of RT are neither in the catalog nor reviewed. Add each status message of a change '
        f'to rt/_messages.py with its kind, and all others to {REVIEWED.name} with the reason (lines to complete below):\n'
        + '\n'.join(f'{json.dumps(msgid)}: "<reason>",' for msgid in new)
    )


def test_reviewed_messages_have_reasons():
    reviewed: dict[str, str] = json.loads(REVIEWED.read_text(encoding='utf-8'))

    assert all(isinstance(reason, str) and reason.strip() for reason in reviewed.values())
    # a msgid is either in the catalog or reviewed as no status message, not both
    assert not reviewed.keys() & rt._messages.MESSAGES.keys()


def test_templates_of_the_catalog_do_not_shadow_each_other():
    """A template filled in must be classified as its own kind: a template of another kind matching it would make it ambiguous."""
    shadowed = [msgid for msgid, kind in rt._messages.MESSAGES.items() if classify(rt._messages._PLACEHOLDER.sub('Foo', msgid)) is not kind]

    assert not shadowed, f'These templates of the catalog are not classified as their kind when filled in (another template matches them): {shadowed}'


def test_catalog_is_consistent():
    # the exact messages (without placeholders) are classified as they are in the catalog
    for msgid, kind in rt._messages.MESSAGES.items():
        if '%' not in msgid:
            assert classify(msgid) is kind, msgid
            assert classify(f'Ticket 1: {msgid}') is kind, msgid

    # templates with placeholders match filled in, also by values which look like other messages
    assert classify('Added alice as Cc for this ticket') is Kind.SUCCESS
    assert classify('Added does not exist as Cc for this ticket') is Kind.SUCCESS
    assert classify("Status 'x' isn't a valid status for this ticket.") is Kind.REFUSED


@pytest.mark.parametrize(
    'message',
    [
        '',
        'Ein neuer Text von RT',
        'Besitzer geändert von Nobody zu root',
        # a value which makes the message match templates of different kinds is not guessed
        "Field can't be empty failed changed to does not exist",
    ],
)
def test_unknown_and_ambiguous_messages_are_not_classified(message: str):
    assert classify(message) is None
