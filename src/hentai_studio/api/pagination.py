"""Opaque keyset cursors, scoped to the collection/filter that created them."""

import base64
import json

from ..errors import StudioError
from .schemas import Page


def paginate(items, *, key, limit, cursor, scope):
    boundary = None
    if cursor:
        try:
            payload = json.loads(
                base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
            )
            if (
                payload["scope"] != scope
                or not isinstance(payload["after"], list)
                or not all(isinstance(value, str) for value in payload["after"])
            ):
                raise ValueError()
            boundary = tuple(payload["after"])
            if len(boundary) != 2:
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            raise StudioError(
                422,
                "invalid_cursor",
                "Use next_cursor from the same collection and filters.",
            ) from error
    selected = [item for item in items if boundary is None or key(item) < boundary]
    page = selected[:limit]
    following = None
    if len(selected) > limit:
        raw = json.dumps(
            {"scope": scope, "after": key(page[-1])}, separators=(",", ":")
        ).encode()
        following = base64.urlsafe_b64encode(raw).decode()
    return Page(items=page, next_cursor=following)
