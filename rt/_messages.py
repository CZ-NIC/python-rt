"""Catalog of the status messages of RT for changes made with REST2.

REST2 reports the result of a change as a list of messages, with HTTP status 200 (201 for messages) for successes as
well as for refusals; there is no flag for success. The messages are localized by RT (language of the API user, or of the
server), so the catalog contains the English messages of RT only.

The messages are the *msgids* of the translation file of RT (``share/po/rt.pot``), where ``%1``, ``%2``... are replaced
by text, e.g. a value of a user. A message is classified when it matches a whole template; values of users can only
appear in the places of the placeholders. If a value makes a message match templates of different kinds, the message
is not classified (never guessed). Messages of RT which are not in the
catalog are *unrecognized*: they are neither a success nor a refusal for the library, see :py:class:`~rt.common.ActionResult`.

Maintenance: add the msgid of a new message with its kind. ``tests/test_message_catalog.py`` checks that every msgid
still exists in the ``rt.pot`` of the RT image used for the tests (RT rewords messages from time to time) and that the
messages received from RT in the tests are in the catalog.
"""

import enum
import re


class Kind(enum.Enum):
    """What a status message of RT tells about a change."""

    SUCCESS = 'success'
    """The change was made (or there was nothing to do, e.g. "Link already exists")."""

    REFUSED = 'refused'
    """RT refused the change, e.g. an invalid value."""

    NOT_FOUND = 'not_found'
    """RT refused the change, as an object (user, queue, ticket, ...) does not exist."""

    DENIED = 'denied'
    """RT refused the change, as the user does not have the permission."""


S, R, N, D = Kind.SUCCESS, Kind.REFUSED, Kind.NOT_FOUND, Kind.DENIED

# msgids of share/po/rt.pot (RT 5.0 and 6.0) of the messages which REST2 returns for changes
MESSAGES: dict[str, Kind] = {
    # --- successes: changes of fields and of the values of custom fields
    '%1 changed from %2 to %3': S,
    "%1 changed from '%2' to '%3'": S,
    '%1 changed from "%2" to "%3"': S,
    'Status changed from %1 to %2': S,
    "Type changed from '%1' to '%2'": S,
    'Subject changed to %1': S,
    '%1 %2 changed to %3': S,
    '%1 %2 added': S,
    '%1 %2 deleted': S,
    '%1 added as a value for %2': S,
    '%1 is no longer a value for custom field %2': S,
    'Custom field value %1 added': S,
    'Custom field value %1 deleted': S,
    '%1 %2 updated.': S,
    '%1 updated': S,
    'Updated %1': S,
    'Updated': S,
    'Enabled': S,
    'Disabled': S,
    'Added custom field %1 to %2.': S,
    'Globally added custom field %1.': S,
    'Removed custom field %1 from %2.': S,
    'Globally removed custom field %1.': S,
    # --- successes: roles, members and links
    'Added %1 as %2 for this ticket': S,
    'Added %1 as %2 for this queue': S,
    '%1 is no longer %2 for this ticket': S,
    '%1 is no longer %2 for this queue': S,
    'Member added: %1': S,
    'Member %1 added': S,
    'Member %1 deleted': S,
    'Membership in %1 added': S,
    'Membership in %1 deleted': S,
    'Dependency on %1 added': S,
    'Dependency on %1 deleted': S,
    'Dependency by %1 added': S,
    'Dependency by %1 deleted': S,
    'Reference to %1 added': S,
    'Reference to %1 deleted': S,
    'Reference by %1 added': S,
    'Reference by %1 deleted': S,
    # adding a link which exists or deleting one which does not exist changes nothing, it is no error
    'Link already exists': S,
    'That is already the current value': S,
    'Link not found': S,
    # --- successes: actions
    'Owner changed from %1 to %2': S,
    'Owner forcibly changed from %1 to %2': S,
    'Merge Successful': S,
    'Correspondence added': S,
    'Correspondence added for %1': S,
    'Comments added': S,
    'Comments added for %1': S,
    'Message recorded': S,
    # --- successes: users and groups
    'User enabled': S,
    'User disabled': S,
    'Group enabled': S,
    'Group disabled': S,
    'That user is now privileged': S,
    'That user is now unprivileged': S,
    'Password changed': S,
    'Password set': S,
    '%1 set to %2': S,
    "Granted right '%1' to %2 '%3'": S,
    "Revoked right '%1' from %2 '%3'": S,
    # --- not found
    '%1 %2 does not exist': N,
    'That user does not exist': N,
    "New ticket doesn't exist": N,
    "Couldn't find that principal": N,
    "Couldn't find that value": N,
    "Couldn't resolve '%1' into a link.": N,
    "Couldn't resolve base '%1' into a URI.": N,
    "Couldn't resolve target '%1' into a URI.": N,
    "Couldn't load Custom Field #%1": N,
    'Custom field %1 not found': N,
    'Custom field value %1 could not be found for custom field %2': N,
    'Principal %1 not found.': N,
    'Group not found': N,
    'Queue not found': N,
    'Not found': N,
    "Role group '%1' not found": N,
    "Could not find group '%1'": N,
    "Could not find or create user '%1'": N,
    # --- permission denied
    'Permission denied': D,
    'Permission Denied': D,
    'Cannot change %1: Permission Denied': D,
    'Password: Permission Denied': D,
    "Owner '%1' does not have rights to own this ticket.": D,
    'No permission to create queues': D,
    'No permission to modify this asset': D,
    'No permission to modify this catalog': D,
    'No permission to set preferences': D,
    # --- refused: tickets, links and owners
    "Status '%1' isn't a valid status for this %2.": R,
    "Status '%1' isn't a valid status for tickets in this queue.": R,
    "Status '%1' isn't a valid status for assets.": R,
    "New assets cannot have status '%1'.": R,
    "Can't merge a ticket into itself": R,
    'Only tickets can be merged': R,
    "Merge failed. Couldn't set EffectiveId": R,
    "Merge failed. Couldn't set IsMerged": R,
    "Can't link a ticket to itself": R,
    "Can't specify both base and target": R,
    'Either base or target must be specified': R,
    'Linking to a deleted %1 is not allowed': R,
    'Refused to add link which would create a circular relationship': R,
    'Unable to parse link base': R,
    'Unable to parse link target': R,
    'Link could not be created: %1': R,
    'Link could not be deleted: %1': R,
    'That ticket has unresolved dependencies': R,
    'That user already owns that ticket': R,
    'That user may not own tickets in that queue': R,
    'You already own this ticket': R,
    'You can only reassign tickets that you own or that are unowned': R,
    'You can only steal a ticket owned by someone else': R,
    'You can only take tickets that are unowned': R,
    'You can only untake tickets you own': R,
    'Could not change owner: %1': R,
    'Delete operation is disabled by lifecycle configuration': R,
    # --- refused: values, custom fields and roles
    'Illegal value for %1': R,
    'Invalid value for %1': R,
    'Invalid value for custom field': R,
    'Invalid value for %1, should be of type %2': R,
    '%1 is not a valid lifecycle': R,
    '%1 is not a %2': R,
    '%1 is already %2': R,
    '%1 cannot be a group': R,
    'That role is invalid for this object': R,
    'Could not make %1 a %2': R,
    'Could not remove %1 as a %2': R,
    "%1 is an address RT receives mail at. Adding it as a '%2' would create a mail loop": R,
    'Custom field %1 does not apply to this object': R,
    "Could not add a new value to custom field '%1': %2": R,
    'Could not add new custom field value: %1': R,
    'Custom field value could not be deleted': R,
    'That is not a value for this custom field': R,
    "'%1' is not a unique value": R,
    'Content is not a valid value': R,
    'Content is not a valid IP address': R,
    'Content is not a valid IP address range': R,
    'This custom field cannot be added to that object': R,
    "Can't add a custom field value without a name": R,
    'Invalid Render Type': R,
    'SortOrder must be an integer value.': R,
    'Lookup type mismatch': R,
    'Object type mismatch': R,
    'Invalid object': R,
    # --- refused: users, groups, queues, assets, catalogs, classes and articles
    'Group already has member: %1': R,
    'Group has no such member': R,
    "Couldn't add member to group": R,
    'Member not deleted': R,
    "Groups can't be members of their members": R,
    "Group name '%1' is already in use": R,
    'Name in use': R,
    'Email address in use': R,
    'Invalid syntax for email address': R,
    'Can not modify system users': R,
    'That user is already privileged': R,
    'That user is already unprivileged': R,
    'You can not set password.': R,
    'Could not create user': R,
    'Could not create group': R,
    'Queue could not be created': R,
    'Invalid Catalog': R,
    'Invalid Class': R,
    'Invalid Name': R,
    'Invalid name': R,
    'Invalid Name (names may not be all digits)': R,
    'Invalid Name (names must be unique and may not be all digits)': R,
    'Assets may not be deleted': R,
    'Catalogs may not be deleted': R,
    'Deleting this object would violate referential integrity': R,
    'Deleting this object would break referential integrity': R,
    'Class is already applied Globally': R,
    'Class is already applied to %1': R,
    'This class does not apply to that object': R,
    'Name in use in destination class': R,
    'Name is required': R,
    # --- refused: rights
    'Invalid right': R,
    "Invalid right. Couldn't canonicalize right '%1'": R,
    'No right specified': R,
    '%1 already has the right %2 on %3 %4': R,
    'Right could not be revoked': R,
    'System error. Right not granted.': R,
}

# Exact messages which are not in rt.pot: joined by RT ("Link could not be created: " and the message of the refusal) or written by
# REST2 and not translated. Like the msgids without placeholders they take precedence over the templates.
EXACT: dict[str, Kind] = {
    'Link could not be created: Permission denied': D,
    'Link could not be deleted: Permission denied': D,
    'Custom fields updated': S,  # REST2, Resource/Message.pm: custom fields of the transaction of a reply or comment
    'Asset deleted': S,  # REST2: deleting an asset sets the status deleted
}

# Regular expressions for messages which are not in rt.pot and contain values (case insensitive, for the whole message)
PATTERNS: dict[str, Kind] = {
    # Links, made of base, link type and target in RT::Record: "Ticket 1 no longer depends on Ticket 2.", "Asset 3 refers to URI https://..."
    r'(?:ticket|asset|article|uri) \S+ (?:no longer )?(?:depends on|depended on by|refers to|referred to by|member of|has member) .+\.': S,
    # REST2: a custom field of the transaction of a reply or comment can not be loaded
    r'unable to load transaction custom field: .+': R,
    # observed with RT 6.0 when a group does not exist: "Group 4 not found"
    r'group \S+ not found': N,
}

# RT adds the type and the ID of the changed record to the messages of a change: "Ticket 703: Subject changed from ..."
_PREFIX = r'(?:[A-Za-z]+ \d+: )?'


def _compile(regex: str) -> re.Pattern[str]:
    return re.compile(f'^{_PREFIX}{regex}$', re.IGNORECASE | re.DOTALL)


# (pattern of the whole message, has placeholders, kind)
_COMPILED: list[tuple[re.Pattern[str], bool, Kind]] = (
    [(_compile('.+'.join(re.escape(part) for part in re.split(r'%\d+', msgid))), '%' in msgid, kind) for msgid, kind in MESSAGES.items()]
    + [(_compile(re.escape(message)), False, kind) for message, kind in EXACT.items()]
    + [(_compile(pattern), True, kind) for pattern, kind in PATTERNS.items()]
)


def classify(message: str) -> Kind | None:
    """Return the kind of a status message of RT.

    A message which equals a message of RT without placeholders (e.g. ``Permission denied``) is classified as this message.
    Otherwise all templates matching the whole message must be of the same kind. If they are not, e.g. a custom field value
    which ends like a refusal in a message about a success (``<custom field> <value> changed to does not exist``), the message
    is not classified instead of guessing.

    :param message: Status message of RT, e.g. ``"Ticket 1: Status 'x' isn't a valid status for this ticket."``
    :returns: The kind of the message, or ``None`` if it is not in the catalog or ambiguous.
    """
    matches = [(has_placeholders, kind) for pattern, has_placeholders, kind in _COMPILED if pattern.match(message)]
    exact = {kind for has_placeholders, kind in matches if not has_placeholders}
    kinds = exact or {kind for _, kind in matches}

    return next(iter(kinds)) if len(kinds) == 1 else None
