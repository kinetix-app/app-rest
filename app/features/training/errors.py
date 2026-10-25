"""Expected training use-case failures, independent of HTTP transport."""


class TrainingError(Exception):
    """Base class for expected training failures."""


class TrainingNotFound(TrainingError):
    """Missing or inaccessible resource."""


class InvalidSelection(TrainingError):
    """An exercise, routine or template slot is unavailable."""


class IdempotencyConflict(TrainingError):
    """An account reused a client key for different normalized workout content."""
