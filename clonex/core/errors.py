"""Failures that end a copy."""


class CloneError(Exception):
    """A precondition failed; the copy must not continue."""


class CloneCancelled(CloneError):
    """The user declined a proposed recovery."""
