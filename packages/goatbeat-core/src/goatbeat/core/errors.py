"""Every error Goatbeat raises derives from GoatbeatError."""


class GoatbeatError(Exception):
    pass


class ConfigurationError(GoatbeatError):
    pass


class NaiveDatetimeError(GoatbeatError, ValueError):
    pass


class InvalidCronExpressionError(ConfigurationError):
    pass


class InvalidIntervalError(ConfigurationError):
    pass


class TaskNotFoundError(GoatbeatError):
    pass


class LeaseLostError(GoatbeatError):
    pass


class SubmissionError(GoatbeatError):
    pass


class StoreUnavailableError(GoatbeatError):
    pass
