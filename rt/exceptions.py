"""Exceptions collection for the rt library."""


class RtError(Exception):
    """Super class of all Rt Errors.

    Errors caused by an HTTP response of RT carry its status code and body, other errors have ``None`` set.

    :ivar status_code: HTTP status code of the response from RT.
    :ivar response_message: Body of the response from RT.
    """

    def __init__(self, message: str = '', status_code: int | None = None, response_message: str | None = None) -> None:
        """Initialization.

        :param message: Description of the error.
        :param status_code: HTTP status code of the response from RT, if the error was caused by one.
        :param response_message: Body of the response from RT, if the error was caused by one.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_message = response_message


class AuthorizationError(RtError):
    """Exception raised when module cannot access :term:`API` due to invalid or missing credentials."""


class NotAllowedError(RtError):
    """Exception raised when request cannot be finished due to insufficient privileges.

    REST2 raises it for HTTP status 403 and if RT refuses an action with "Permission Denied".
    """


class UnexpectedResponseError(RtError):
    """Exception raised when unexpected HTTP code is received."""


class ConflictError(UnexpectedResponseError):
    """Exception raised when RT answers with HTTP status 409 (Conflict).

    REST2 raises it e.g. when granting a right which is already granted. It is a subclass of
    :py:exc:`UnexpectedResponseError`, which was raised for this status before.
    """


class UnexpectedMessageFormatError(RtError):
    """Exception raised when response has bad status code (not the HTTP code,
    but code in the first line of the body as 200 in `RT/4.0.7 200 Ok`)
    or message parsing fails because of unexpected format.
    """


class NotFoundError(RtError):
    """Exception raised if requested resource is not found."""


class APISyntaxError(RtError):
    """Exception raised when syntax error is received."""


class InvalidUseError(RtError, ValueError):
    """Exception raised when API method is not used correctly, or RT refused the requested action.

    It is a subclass of both :py:exc:`RtError` and the builtin :py:exc:`ValueError`,
    so it can be caught as either of them.
    """


class BadRequestError(RtError):
    """Exception raised when HTTP code 400 (Bad Request) is received."""


class RtConnectionError(RtError, ConnectionError):
    """Encapsulation of various exceptions indicating network problems.

    It is a subclass of both :py:exc:`RtError` and the builtin :py:exc:`ConnectionError`,
    so it can be caught as either of them.
    """

    def __init__(self, message: str, cause: Exception) -> None:
        """Initialization of exception extended by cause parameter.

        :keyword message: Exception details
        :keyword cause: Cause exception
        """
        super().__init__(f'{message} (Caused by {repr(cause)})')
        self.cause = cause


class InvalidQueryError(RtError):
    """Exception raised when attempting to search RT with an invalid raw query."""
