"""Articles and classes of articles of the REST2 client."""

import collections.abc
import typing

from rt._rest2_async.transport import _AsyncTransport
from rt.common import (
    _ARTICLE_FIELDS,
    _CLASS_FIELDS,
    _HISTORY_FIELDS,
    ActionResult,
    JSONInput,
    JSONSearchParams,
    SortOrder,
    _fields_params,
    _order_params,
    _path,
)


class AsyncArticles:
    """Articles of RT.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.articles``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    async def get(self, article_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the article itself.
        :returns: The article as dictionary, e.g. with the keys id, Name, Summary, Class, Disabled and CustomFields,
                  which contain its text in the custom field Content.
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('article', article_id), params=fields))

    async def create(self, name: str, class_id: str | int, **kwargs: JSONInput) -> int:
        """Create an article.

        Example::

            >>> tracker.articles.create('VPN setup', 'FAQ', Summary='How to set up the VPN', CustomFields={'Content': 'Install ...'})

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param name: Name of the article, which must be unique in its class.
        :param class_id: Identification of the class by name (str) or ID (int).
        :param kwargs: Other fields to set, e.g. Summary, SortOrder, or CustomFields, e.g.
                       ``CustomFields={'Content': 'Text of the article'}``.
        :returns: ID of the new article.
        :raises BadRequestError: If RT rejects the request, e.g. if an article with the name exists in the class
                                 (RT reports this only as "Create failed for unknown reason").
        :raises NotAllowedError: If the user is not allowed to create articles in the class, or the class does not
                                 exist (RT returns status code 403 for both).
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _ARTICLE_FIELDS, 'articles.create')
        response = await self._t.send('POST', 'article', json_data={'Name': name, 'Class': class_id, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit(self, article_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :param kwargs: Fields to set, e.g. Name, Summary, SortOrder, or CustomFields, e.g.
                       ``CustomFields={'Content': 'New text'}``. RT ignores unknown fields.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _ARTICLE_FIELDS, 'articles.edit')
        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('article', article_id), json_data=kwargs)))

    async def delete(self, article_id: str | int) -> None:
        """Delete (disable) an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :raises NotFoundError: If the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected, e.g. if the article is already
                                         deleted (RT fails with HTTP status 500 then).
        """
        await self._t.delete(_path('article', article_id))

    async def history(
        self,
        article_id: str | int,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get the history of an article.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param article_id: ID of the article.
        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g. only
                              the changes of the summary: ``[{'field': 'Field', 'value': 'Summary'}]``.
        :param fields: Fields returned for each transaction: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT, e.g. ``{'fields[Creator]': 'Name'}``. Defaults to the fields of :py:meth:`~AsyncTickets.history`.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``. Default: oldest first.
        :returns: Iterator of transactions, each a dictionary with the same keys as for
                  :py:meth:`~AsyncTickets.history`. Empty if the article does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.check_conditions(search_params, 'transactions', 'articles.history')
        async for transaction in self._t.paged_request(
            _path('article', article_id, 'history'),
            json_data=list(search_params) if search_params else None,
            params={
                'fields[Creator]': 'id,Name,RealName,EmailAddress',
                **_fields_params(fields, default_fields=_HISTORY_FIELDS),
                **_order_params(order),
            },
        ):
            yield transaction

    async def search(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search articles.

        Example::

            >>> tracker.articles.search(search_params=[{'field': 'Class', 'value': 1}, {'field': 'Name', 'operator': 'LIKE', 'value': 'VPN'}])

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'operator': 'LIKE', 'value': 'VPN'}]``. All articles if not
                              specified.
        :param fields: Fields returned for each article: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Summary, Class and Disabled.
        :param include_disabled: Set to True to also return disabled (deleted) articles.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the found articles.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._t.search_objects(
            'articles', search_params, fields, 'Name,Summary,Class,Disabled', include_disabled=include_disabled, order=order, method='articles.search'
        ):
            yield item


class AsyncClasses:
    """Classes of articles of RT.

    Use it as attribute of :py:class:`AsyncRt`, e.g. ``tracker.classes``.
    """

    def __init__(self, transport: _AsyncTransport) -> None:
        self._t = transport

    async def all(
        self,
        *,
        include_disabled: bool = False,
        fields: str | list[str] | dict[str, str] | None = None,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Get all classes of articles which the user can see.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param include_disabled: Set to True to also return disabled classes.
        :param fields: Fields returned for each class: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT, e.g. ``{'fields[Creator]': 'Name'}``. Defaults to the fields listed below.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the classes, each a dictionary with the keys id, type, _url, Name, Description and
                  Disabled.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        params: dict[str, str | int | list[str]] = {
            **_fields_params(fields, default_fields='Name,Description,Disabled'),
            **_order_params(order),
            'find_disabled_rows': int(include_disabled),
        }

        async for item in self._t.paged_request('classes/all', params=params):
            yield item

    async def get(self, class_id: str | int, *, fields: dict[str, str] | None = None) -> dict[str, typing.Any]:
        """Get a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :param fields: Query parameters as defined by RT to return fields of linked objects, e.g.
                       ``{'fields[Creator]': 'Name,EmailAddress'}``. RT always returns all fields of the class itself.
        :returns: The class as dictionary, e.g. with the keys id, Name, Description, Disabled and
                  ArticleCustomFields (the custom fields of its articles, e.g. Content).
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        return self._t.dict_result(await self._t.send('GET', _path('class', class_id), params=fields))

    async def create(self, name: str, **kwargs: JSONInput) -> int:
        """Create a class of articles.

        RT applies the custom field Content for the text of articles to new classes.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param name: Name of the class, which must be unique.
        :param kwargs: Other fields to set, e.g. Description or SortOrder.
        :returns: ID of the new class.
        :raises BadRequestError: If RT rejects the request, e.g. if a class with the name exists.
        :raises NotAllowedError: If the user is not allowed to create classes.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CLASS_FIELDS, 'classes.create')
        response = await self._t.send('POST', 'class', json_data={'Name': name, **kwargs})

        return int(self._t.created_id(self._t.dict_result(response)))

    async def edit(self, class_id: str | int, **kwargs: JSONInput) -> ActionResult:
        """Edit a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :param kwargs: Fields to set, e.g. Name, Description, SortOrder, Disabled. RT ignores unknown fields.
        :returns: The :py:class:`~rt.common.ActionResult`. It is true if RT executed the request, also if it refused a
                  part of it (e.g. an invalid status), which RT reports only as message: check
                  :py:attr:`~rt.common.ActionResult.complete` or call
                  :py:meth:`~rt.common.ActionResult.raise_for_refused`.
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        self._t.warn_unknown_fields(kwargs, _CLASS_FIELDS, 'classes.edit')
        return self._t.result(self._t.list_result(await self._t.send('PUT', _path('class', class_id), json_data=kwargs)))

    async def delete(self, class_id: str | int) -> None:
        """Disable a class of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param class_id: Identification of the class by name (str) or ID (int).
        :raises NotFoundError: If the class does not exist.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        await self._t.delete(_path('class', class_id))

    async def search(
        self,
        *,
        search_params: JSONSearchParams | None = None,
        fields: str | list[str] | dict[str, str] | None = None,
        include_disabled: bool = False,
        order: SortOrder | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, typing.Any]]:
        """Search classes of articles.

        .. note:: Requires RT 5.0.1 or newer. RT 5.0.0 answers with HTTP status 404, i.e.
                  :py:exc:`~rt.exceptions.NotFoundError` is raised.

        :param search_params: Conditions of the search as described for :py:meth:`~AsyncAssets.search`, e.g.
                              ``[{'field': 'Name', 'value': 'FAQ'}]``. All classes if not specified.
        :param fields: Fields returned for each class: a comma separated string or list of fields, or a dictionary
                       with query parameters as defined by RT. By default Name, Description and Disabled.
        :param include_disabled: Set to True to also return disabled classes.
        :param order: Field to sort by, with ``-`` in front for descending order, e.g. ``'-Created'``, or a list of
                      them, e.g. ``['Name', '-id']``.
        :returns: Iterator of the found classes.
        :raises UnexpectedResponseError: If the response from RT is not as expected.
        """
        async for item in self._t.search_objects(
            'classes', search_params, fields, 'Name,Description,Disabled', include_disabled=include_disabled, order=order, method='classes.search'
        ):
            yield item
