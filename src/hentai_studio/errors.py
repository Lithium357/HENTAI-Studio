"""Application errors shared by services and translated by the HTTP boundary."""


class StudioError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: list | None = None
    ):
        self.status, self.code, self.message = status, code, message
        self.details = details or []
        super().__init__(message)
