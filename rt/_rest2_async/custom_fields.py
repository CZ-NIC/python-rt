"""Custom fields, their values and custom roles of the REST2 client."""

import collections.abc
import typing

from rt._rest2_async.transport import _AsyncTransport
from rt.common import (
    _CUSTOM_FIELD_FIELDS,
    _CUSTOM_FIELD_VALUE_FIELDS,
    VALID_CUSTOM_FIELD_OBJECT_TYPES,
    ActionResult,
    CustomFieldObjectType,
    JSONInput,
    JSONSearchParams,
    SortOrder,
    _fields_params,
    _order_params,
    _path,
)
from rt.exceptions import (
    InvalidUseError,
    UnexpectedResponseError,
)


class AsyncCustomFields:
    """Custom fields of RT and their values.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.custom_fields``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    async def get(self, custom_field_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the custom field itself.
        :returns: The custom field as dictionary, including the names of its values in the key Values for the
                  type Select.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('customfield', custom_field_id), params=fields))

    async def create(self, name: str, field_type: str, lookup_type: str, **kwargs: JSONInput) -> int:
        """Create a custom field.

        Example::

            >>> tracker.custom_fields.create('Severity', 'Select', 'RT::Queue-RT::Ticket', MaxValues=1, Queue='General')

        .. note:: Requires RT 5.0.0 or newer.

        :param name: Name of the custom field. RT does not require it to be unique.
        :param field_type: Type of the custom field, e.g. Freeform, Select, Text, Wikitext, Image, Binary, Combobox,
                           Autocomplete, Date, DateTime, IPAddress or IPAddressRange.
        :param lookup_type: Type of the objects the custom field is for, e.g. ``'RT::Queue-RT::Ticket'`` (tickets),
                            ``'RT::Queue-RT::Ticket-RT::Transaction'`` (ticket transactions), ``'RT::Queue'``,
                            ``'RT::User'``, ``'RT::Group'``, ``'RT::Catalog-RT::Asset'`` (assets) or
                            ``'RT::Class-RT::Article'`` (articles).
        :param kwargs: Other fields to set, e.g. Description, MaxValues (0 for unlimited, 1 for a single value),
                       Pattern, EntryHint, SortOrder, or Queue (name or ID of a single queue to apply a ticket custom
                       field to, see :py:meth:`apply` for more and for other lookup types).
        :returns: ID of the new custom field.
        :raises InvalidUseError: If Queue is specified for another lookup type than ``'RT::Queue-RT::Ticket'``,
                                 as RT would then silently create a ticket custom field.
        :raises BadRequestError: If RT rejects the request, e.g. for an invalid type or an unknown queue.
        :raises NotAllowedError: If the user is not allowed to create custom fields.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CUSTOM_FIELD_FIELDS, 'custom_fields.create')
        if 'Queue' in kwargs and lookup_type != 'RT::Queue-RT::Ticket':
            raise InvalidUseError('Queue can only be specified for ticket custom fields, use custom_fields.apply() for other lookup types.')

        response = await self._t.send('POST', 'customfield', json_data={'Name': name, 'Type': field_type, 'LookupType': lookup_type, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit(self, custom_field_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param kwargs: Fields to set, e.g. Name, Description, MaxValues, Pattern, EntryHint, SortOrder, Disabled.
                       RT ignores unknown fields.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CUSTOM_FIELD_FIELDS, 'custom_fields.edit')
        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('customfield', custom_field_id), json_data=kwargs)))

    async def delete(self, custom_field_id: str | int) -> None:
        """Disable a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('customfield', custom_field_id))

    async def get_applies_to(self, custom_field_id: str | int) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the objects which a custom field is applied to.

        This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :returns: Iterator of the objects, each a dictionary with the keys ObjectId, ObjectType, ObjectName and _url,
                  e.g. ``{'ObjectId': 1, 'ObjectType': 'RT::Queue', 'ObjectName': 'General', ...}``, or
                  ``{'ObjectId': 0, 'Global': True}`` if the custom field is applied globally.
        :raises NotFoundError: If the custom field does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._t.paged_request(_path('customfield', custom_field_id, 'appliesto')):
            yield item

    async def apply(self, custom_field_id: str | int, object_id: int) -> ActionResult:
        """Apply a custom field to an object, e.g. a ticket custom field to a queue.

        The type of the object is determined by the lookup type of the custom field, e.g. a queue for a ticket
        custom field. This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param object_id: ID of the object (RT does not support names here), or 0 to apply the custom field
                          globally, which removes it from all objects it was applied to.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request. RT refused nothing,
                  as an exception is raised for a refusal (nothing was changed).
        :raises BadRequestError: If RT rejects the request, e.g. if the object or the custom field does not exist.
        :raises ConflictError: If the custom field is already applied to the object.
        :raises NotAllowedError: If the user is not allowed to apply the custom field.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        response = await self._t.send('POST', _path('customfield', custom_field_id, 'appliesto'), json_data={'ObjectId': object_id})
        result = self._t.dict_result(response)

        message = result.get('message')
        if not isinstance(message, str):
            raise UnexpectedResponseError(str(result), status_code=response.status_code, response_message=response.text)

        return self._t.confirmed([message])

    async def unapply(self, custom_field_id: str | int, object_id: int) -> None:
        """Remove a custom field from an object it is applied to.

        This endpoint is not part of the REST2 documentation of RT.

        .. note:: Requires RT 6.0.3 or newer, it is not available in RT 5.0. Older versions of RT answer with HTTP status 404,
                  i.e. :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param object_id: ID of the object (RT does not support names here), or 0 to remove the global application.
        :raises NotFoundError: If the custom field is not applied to the object.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('customfield', custom_field_id, 'appliesto', 'object', object_id))

    async def get_values(
        self,
        custom_field_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the values of a custom field, e.g. the selectable values of the type Select.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'value': 'High'}]``. All values if not specified.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the values, each a dictionary with the keys id, name, type and _url. Empty if the custom
                  field does not exist (RT does not report it).
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'customfieldvalues', 'custom_fields.get_values')
        async for item in self._t.paged_request(
            _path('customfield', custom_field_id, 'values'), json_data=list(search_params or []), params=_order_params(order)
        ):
            yield item

    async def get_value(self, custom_field_id: str | int, value_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a value of a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the value itself.
        :returns: The value as dictionary, e.g. with the keys id, Name, Description, Category and SortOrder.
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('customfield', custom_field_id, 'value', value_id), params=fields))

    async def add_value(self, custom_field_id: str | int, name: str, **kwargs: JSONInput) -> int:
        """Add a value to a custom field, e.g. a selectable value of the type Select.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param name: The value. RT does not require it to be unique.
        :param kwargs: Other fields to set, e.g. Description, Category, SortOrder.
        :returns: ID of the new value.
        :raises BadRequestError: If RT rejects the request, also if the custom field does not exist ("Couldn't load
                                 Custom Field #").
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CUSTOM_FIELD_VALUE_FIELDS, 'custom_fields.add_value')
        response = await self._t.send('POST', _path('customfield', custom_field_id, 'value'), json_data={'Name': name, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit_value(self, custom_field_id: str | int, value_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit a value of a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :param kwargs: Fields to set, e.g. Name, Description, Category, SortOrder. RT ignores unknown fields.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CUSTOM_FIELD_VALUE_FIELDS, 'custom_fields.edit_value')
        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('customfield', custom_field_id, 'value', value_id), json_data=kwargs)))

    async def delete_value(self, custom_field_id: str | int, value_id: str | int) -> None:
        """Remove a value from a custom field.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_field_id: ID of the custom field (RT does not support names here).
        :param value_id: ID of the value.
        :raises NotFoundError: If the custom field or the value does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('customfield', custom_field_id, 'value', value_id))

    async def get_file(self, value_id: str | int) -> bytes:
        """Get the content of a file stored as value of an Image or Binary custom field of an object, e.g. a ticket.

        The custom field values of a ticket or asset contain a ``_url`` like ``.../REST/2.0/download/cf/12`` for
        each file, its last part is the ID. To set a file as value, pass an :py:class:`~rt.common.Attachment`
        converted with ``to_dict()``, e.g. ``tickets.edit(1, CustomFields={'Screenshot': attachment.to_dict()})``.

        .. note:: Requires RT 5.0.0 or newer.

        :param value_id: ID of the custom field value of the object (not of a value of the custom field).
        :returns: Content of the file.
        :raises NotAllowedError: If the value does not exist or the user is not allowed to see it
                                 (RT returns status code 403 for both).
        :raises RtConnectionError: In case of a connection error.
        """
        response = await self._t.send('GET', _path('download', 'cf', value_id))

        return response.content

    async def search(
        self,
        *,
        object_type: CustomFieldObjectType | None = None,
        object_id: str | int | None = None,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search custom fields, all or those applied to a queue, catalog or class.

        Example::

            >>> tracker.custom_fields.search(object_type='queue', object_id=1)
            >>> tracker.custom_fields.search(search_params=[{'field': 'LookupType', 'value': 'RT::Queue-RT::Ticket'}])

        .. note:: Requires RT 5.0.0 or newer.

        :param object_type: ``'queue'``, ``'catalog'`` or ``'class'`` to search only the custom fields applied to
                            the object *object_id* (RT includes the custom fields applied globally to all queues,
                            catalogs or classes), ``None`` (default) to search all custom fields.
        :param object_id: ID of the queue, catalog or class (RT does not support names here).
        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'value': 'Severity'}]``. All custom fields if not specified.
        :param fields: Fields returned for each custom field: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Name, Type, Description,
                       LookupType, MaxValues and Disabled.
        :param include_disabled: Set to True to also return disabled custom fields.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the found custom fields.
        :raises InvalidUseError: If *object_type* is not supported, or only one of *object_type* and *object_id*
                                 is specified.
        :raises NotFoundError: If the queue, catalog or class does not exist.
        :raises NotAllowedError: If the user is not allowed to see the queue, catalog or class.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_conditions(search_params, 'customfields', 'custom_fields.search')
        if (object_type is None) != (object_id is None):
            raise InvalidUseError('object_type and object_id must be specified together.')

        if object_type is None:
            selector = 'customfields'
        else:
            if object_type not in VALID_CUSTOM_FIELD_OBJECT_TYPES:
                raise InvalidUseError(f'Unsupported object type. Use one of "{", ".join(VALID_CUSTOM_FIELD_OBJECT_TYPES)}".')
            object_id = typing.cast('str | int', object_id)
            # For an object which does not exist, RT (6.0.4 at least) searches all custom fields with the conditions
            await self._t.send('GET', _path(object_type, object_id))
            selector = _path(object_type, object_id, 'customfields')

        search_params = list(search_params or [])
        if not search_params and object_type is None:
            # RT returns no custom field for a search of all custom fields without a condition
            search_params = [{'field': 'id', 'operator': '>', 'value': 0}]

        params: dict[str, str | int | list[str]] = {
            **_order_params(order),
            **_fields_params(fields, default_fields='Name,Type,Description,LookupType,MaxValues,Disabled'),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._t.paged_request(selector, json_data=search_params, params=params):
            yield item


class AsyncCustomRoles:
    """Custom roles of RT.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.custom_roles``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    async def get(self, custom_role_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a custom role.

        .. note:: Requires RT 5.0.0 or newer.

        :param custom_role_id: ID of the custom role (RT does not support names here).
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the custom role itself.
        :returns: The custom role as dictionary, e.g. with the keys id, Name, Description, MaxValues (1 for a single
                  member, 0 for several), LookupType, EntryHint and Disabled.
        :raises NotFoundError: If the custom role does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('customrole', custom_role_id), params=fields))

    async def search(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search custom roles.

        Custom roles can only be read with REST2, not created or changed.

        .. note:: Requires RT 5.0.0 or newer.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'value': 'Manager'}]``. All custom roles if not specified.
        :param fields: Fields returned for each custom role: a comma separated string or list of fields, or a
                       dictionary with query parameters as defined by RT. By default Name, Description, MaxValues,
                       LookupType and Disabled.
        :param include_disabled: Set to True to also return disabled custom roles.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the found custom roles.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._t.search_objects(
            'customroles',
            search_params,
            fields,
            'Name,Description,MaxValues,LookupType,Disabled',
            include_disabled=include_disabled,
            order=order,
            method='custom_roles.search',
        ):
            yield item
