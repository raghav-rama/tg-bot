from __future__ import annotations


class BotError(Exception):
    """Base class for handled bot errors."""


class UnauthorizedUserError(BotError):
    """Raised when a user is not on the allowlist."""


class UnsupportedMessageError(BotError):
    """Raised when the inbound Telegram message type is out of scope."""


class ValidationError(BotError):
    """Raised when a supported inbound message fails validation."""


class ProviderTimeoutError(BotError):
    """Raised when the provider times out."""


class ProviderUpstreamError(BotError):
    """Raised when the provider returns an upstream failure."""


class DraftDeliveryError(BotError):
    """Raised when a partial Telegram draft cannot be delivered."""


class DraftRateLimitedError(DraftDeliveryError):
    """Raised when Telegram rate limits partial draft delivery."""

    def __init__(self, *, retry_after: int) -> None:
        super().__init__(f"Draft delivery rate limited; retry after {retry_after} seconds")
        self.retry_after = retry_after


class StorageError(BotError):
    """Raised when SQLite operations fail."""
