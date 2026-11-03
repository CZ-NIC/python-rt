"""Tests of the catalog of the status messages of RT (rt/_messages.py).

The messages received from RT in the live tests are checked at the end of the test session by the fixture
``record_messages_of_rt`` in conftest.py.
"""

# ruff: noqa: S101, S603, SLF001

import re
import shutil
import subprocess

import pytest

import rt._messages
from rt._messages import Kind, classify

RT_IMAGE = 'ghcr.io/python-rt/request-tracker'
RT_POT = '/opt/rt/share/po/rt.pot'


def _rt_pot() -> set[str]:
    """Return the msgids of the translation file of the RT image used for the tests, or skip the test."""
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

    blocks = re.findall(r'^msgid ((?:"[^\n]*"\n)+)', pot.stdout, flags=re.MULTILINE)

    return {''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', block)).replace('\\"', '"') for block in blocks}


def test_msgids_of_the_catalog_exist_in_rt():
    """RT rewords messages from time to time: a msgid which is not in rt.pot anymore is a message of the catalog which RT does not send."""
    pot = _rt_pot()

    missing = [msgid for msgid in rt._messages.MESSAGES if msgid not in pot]

    assert not missing, f'These messages of the catalog are not in {RT_POT} of the RT image (reworded or removed?): {missing}'


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
