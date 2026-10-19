"""Small helpers for constructing deferred trigger actions."""
from functools import wraps


class _DeferredAction:
    def __init__(self, function, args, kwargs):
        self.function, self.args, self.kwargs = function, args, kwargs

    def __call__(self):
        return self.function(*self.args, **self.kwargs)


def pseudotrigger(func):
    """Capture arguments now and return a zero-argument action to connect or call."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return _DeferredAction(func, args, kwargs)
    return wrapper


@pseudotrigger
def announce(message):
    """Return an action that prints message when invoked."""
    print(message)
