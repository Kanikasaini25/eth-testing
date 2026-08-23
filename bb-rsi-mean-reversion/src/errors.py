"""Operational errors for the BB/RSI bot. Programmer errors still raise built-ins."""


class StrategyError(Exception):
    """Base class for expected runtime failures."""


class ConfigError(StrategyError):
    """Missing or invalid environment configuration."""


class DeltaAPIError(StrategyError):
    """Delta REST/WebSocket returned an error or unexpected payload."""


class RateLimitError(DeltaAPIError):
    """HTTP 429 or exchange rate-limit payload."""


class OrderError(StrategyError):
    """Order placement, cancel, or bracket attach failed."""
