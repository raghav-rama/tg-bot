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


class StorageError(BotError):
    """Raised when SQLite operations fail."""

