"""Groups of the REST2 client."""

import collections.abc
import typing

from rt._rest2_async.transport import _AsyncTransport
from rt.common import (
    ActionResult,
    JSONInput,
    JSONSearchParams,
    _fields_params,
    _path,
)
from rt.exceptions import (
    InvalidUseError,
    UnexpectedResponseError,
)


class AsyncGroups:
    """Groups of RT.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.groups``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    async def get(self, group_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the group itself.
        :returns: The group as dictionary, including its direct members in the key Members (users by name,
                  groups by ID).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('group', group_id), params=fields))

    async def create(self, name: str, **kwargs: JSONInput) -> int:
        """Create a user defined group.

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Name of the group, which must be unique.
        :param kwargs: Other fields to set, e.g. Description.
        :returns: ID of the new group.
        :raises BadRequestError: If RT rejects the request, e.g. if a group with the name exists.
        :raises NotAllowedError: If the user is not allowed to create groups.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._t.send('POST', 'group', json_data={'Name': name, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit(self, group_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param kwargs: Fields to set, e.g. Name, Description, Disabled. RT ignores unknown fields.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('group', group_id), json_data=kwargs)))

    async def delete(self, group_id: str | int) -> None:
        """Disable a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('group', group_id))

    async def get_members(
        self,
        group_id: str | int,
        *,
        recursive: bool = False,
        users: bool = True,
        groups: bool = True,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the members of a group.

        RT returns only the ID, type (user or group) and _url of each member, :py:meth:`get`
        returns the direct members with the names of users.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param recursive: Set to True to also return the members of member groups. RT then also returns the group
                          itself, and users which are members of several of the groups more than once.
        :param users: Set to False to not return users.
        :param groups: Set to False to not return groups.
        :returns: Iterator of the members.
        :raises InvalidUseError: If both *users* and *groups* are False.
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        if not users and not groups:
            raise InvalidUseError('At least one of users and groups must be True.')

        params: dict[str, str | int] = {}
        if recursive:
            params['recursively'] = 1
        if not users:
            params['users'] = 0
        if not groups:
            params['groups'] = 0

        async for item in self._t.paged_request(_path('group', group_id, 'members'), params=params):
            yield item

    async def add_member(self, group_id: str | int, principal_id: str | int) -> ActionResult:
        """Add a user or group as member to a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param principal_id: ID of the user or group to add (RT does not support names here).
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises NotFoundError: If the group or the member does not exist.
        :raises InvalidUseError: If RT refused to add the member, e.g. if it is already a member of the group.
        :raises NotAllowedError: If the user is not allowed to change the members of the group.
        :raises UnexpectedResponseError: If the response from RT is not as expected, or RT answers with a message which is not
                                         known to the library (e.g. if the language of the user is not English): the action may not have been made.
        """
        msg = self._t.list_result(await self._t.send('PUT', _path('group', group_id, 'members'), json_data=[principal_id]))

        if len(msg) != 1:
            raise UnexpectedResponseError(str(msg))

        # RT reports a group which is not user defined (e.g. a system group) as not found
        return self._t.done(msg)

    async def remove_member(self, group_id: str | int, principal_id: str | int) -> None:
        """Remove a user or group from the members of a group.

        RT also confirms the removal if the principal is not a member of the group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :param principal_id: ID of the user or group to remove (RT does not support names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('group', group_id, 'member', principal_id))

    async def remove_all_members(self, group_id: str | int) -> None:
        """Remove all direct members of a group.

        .. note:: Requires RT 5.0.0 or newer.

        :param group_id: ID of the group (RT does not support group names here).
        :raises NotFoundError: If the group does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('group', group_id, 'members'))

    async def search(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search groups.

        RT 6.0 returns only user defined groups, RT 5.0 also internal groups (e.g. system and role groups).

        Example::

            >>> tracker.groups.search(search_params=[{'field': 'Name', 'operator': 'LIKE', 'value': 'Staff'}])

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'value': 'Staff'}]``. All groups if not specified.
        :param fields: Fields returned for each group: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description and Disabled.
        :param include_disabled: Set to True to also return disabled groups.
        :returns: Iterator of the found groups.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int] = {
            **_fields_params(fields, default_fields='Name,Description,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._t.paged_request('groups', json_data=list(search_params or []), params=params):
            yield item
