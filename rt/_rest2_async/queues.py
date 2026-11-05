"""Queues of the REST2 client."""

import collections.abc
import typing

from rt._rest2_async.transport import _AsyncTransport
from rt.common import (
    _QUEUE_FIELDS,
    ActionResult,
    JSONInput,
    JSONSearchParams,
    SortOrder,
    _check_fields,
    _fields_params,
    _order_params,
    _path,
)


class AsyncQueues:
    """Queues of RT.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.queues``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        """Create the area of the API.

        :py:class:`AsyncRt` creates it, do not create it yourself.

        :param transport: Transport of the client, which sends the requests to RT.
        """
        self._t = transport

    async def get(self, queue_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get queue details.

        Example of a return result:

        .. code-block:: json

            {
                "LastUpdatedBy": {
                    "_url": "http://localhost:8080/REST/2.0/user/RT_System",
                    "type": "user",
                    "id": "RT_System"
                },
                "LastUpdated": "2022-03-06T04:53:38Z",
                "AdminCc": [],
                "SortOrder": "0",
                "CorrespondAddress": "",
                "Creator": {
                    "id": "RT_System",
                    "_url": "http://localhost:8080/REST/2.0/user/RT_System",
                    "type": "user"
                },
                "Lifecycle": "default",
                "Cc": [],
                "Created": "2022-03-06T04:53:38Z",
                "_hyperlinks": [
                    {
                        "_url": "http://localhost:8080/REST/2.0/queue/1",
                        "type": "queue",
                        "id": 1,
                        "ref": "self"
                    },
                    {
                        "ref": "history",
                        "_url": "http://localhost:8080/REST/2.0/queue/1/history"
                    },
                    {
                        "ref": "create",
                        "type": "ticket",
                        "_url": "http://localhost:8080/REST/2.0/ticket?Queue=1"
                    }
                ],
                "SLADisabled": "1",
                "Name": "General",
                "TicketCustomFields": [],
                "Disabled": "0",
                "TicketTransactionCustomFields": [],
                "CustomFields": [],
                "Description": "The default queue",
                "CommentAddress": "",
                "id": 1
            }

        .. note:: Requires RT 5.0.0 or newer.

        :param queue_id: Identification of queue by name (str) or queue ID
                         (int)
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the queue itself.
        :returns: Queue details as a dictionary

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        :raises NotFoundError: In case the queue does not exist
        """
        return self._t.dict_result(await self._t.send('GET', _path('queue', queue_id), params=fields))

    async def all(
        self,
        *,
        include_disabled: bool = False,
        fields: str | list[str] | dict[str, str] | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Return a list of all queues.

        Example of a return result:

        .. code-block:: json

            [
                {
                    "InitialPriority": "",
                    "_url": "http://localhost:8080/REST/2.0/queue/1",
                    "type": "queue",
                    "Name": "General",
                    "DefaultDueIn": "",
                    "Description": "The default queue",
                    "CorrespondAddress": "",
                    "CommentAddress": "",
                    "id": "1",
                    "FinalPriority": ""
                }
            ]

        .. note:: Requires RT 5.0.0 or newer.

        :param include_disabled: Set to True to also return disabled queues.
        :param fields: Fields returned for each queue: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT, e.g. ``{'fields[Creator]': 'Name'}``. Defaults to Name, Description, CorrespondAddress, CommentAddress, InitialPriority,
                       FinalPriority and DefaultDueIn.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.

        :returns: Iterator of dictionaries containing basic information on all queues.

        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int | list[str]] = {
            **_fields_params(fields, default_fields='Name,Description,CorrespondAddress,CommentAddress,InitialPriority,FinalPriority,DefaultDueIn'),
            **_order_params(order),
            'find_disabled_rows': int(include_disabled),
        }
        async for item in self._t.paged_request('queues/all', params=params):
            yield item

    async def edit(self, queue_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit queue.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue_id: Identification of queue by name (str) or ID (int)
        :param kwargs: Other fields to edit from the following list:

                          * Name
                          * Description
                          * CorrespondAddress
                          * CommentAddress
                          * Disabled
                          * SLADisabled
                          * Lifecycle
                          * SortOrder
                          * SubjectTag
                          * CustomFields (custom fields of the queue itself, e.g. ``{'Region': 'EU'}``)
                          * Cc, AdminCc (watchers of all tickets of the queue: user names, email addresses, principal
                            IDs or groups as ``'group:Name'``, replacing the current watchers)

        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: When queue does not exist
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _QUEUE_FIELDS)

        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('queue', queue_id), json_data=kwargs)))

    async def create(self, name: str, **kwargs: JSONInput) -> int:
        """Create queue.

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Queue name (required)
        :param kwargs: Optional fields to set (see :py:meth:`~AsyncQueues.edit`)
        :returns: ID of new queue
        :raises BadRequestError: When queue already exists
        :raises InvalidUseError: When invalid fields are set
        :raises UnexpectedResponseError: If the response from RT is not as expected
        """
        _check_fields(kwargs, _QUEUE_FIELDS)

        response = await self._t.send('POST', 'queue', json_data={'Name': name, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def delete(self, queue_id: str | int) -> None:
        """Disable a queue.

        .. note:: Requires RT 5.0.0 or newer.

        :param queue_id: Identification of queue by name (str) or ID (int)
        :raises NotFoundError: If the queue does not exist.
        :raises BadRequestError: If RT rejects the request.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('queue', queue_id))

    async def search(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search queues.

        Example::

            >>> tracker.queues.search(search_params=[{'field': 'Lifecycle', 'value': 'default'}])

        Unlike for other objects, RT combines several conditions on the same field with AND for queues. Add
        ``'entry_aggregator': 'OR'`` to a condition to combine it with the previous one with OR.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'Support'}]``. All queues if not
                              specified.
        :param fields: Fields returned for each queue: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description, Lifecycle and Disabled.
        :param include_disabled: Set to True to also return disabled queues.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the found queues.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._t.search_objects(
            'queues', search_params, fields, 'Name,Description,Lifecycle,Disabled', include_disabled=include_disabled, order=order, method='queues.search'
        ):
            yield item
