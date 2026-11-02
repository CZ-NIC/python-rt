# ruff: noqa: S311

import collections.abc
import contextlib
import random
import string


def random_string(length: int = 15) -> str:
    """Return a random string."""
    return ''.join([random.choice(string.ascii_letters) for i in range(length)])


@contextlib.contextmanager
def no_type_checks() -> collections.abc.Iterator[None]:
    """Disable the runtime type checks of typeguard, for tests passing invalid types on purpose.

    typeguard is optional: without it (or without ``--typeguard-packages``), this does nothing.
    """
    try:
        import typeguard  # noqa: PLC0415
    except ImportError:
        yield
        return

    with typeguard.suppress_type_checks():
        yield
