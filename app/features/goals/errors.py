class FutureMeasurement(Exception):
    """A measurement date is later than today in the account timezone."""


class MeasurementRequestConflict(Exception):
    """A saved request ID was reused for a different measurement."""


class ObjectiveChanged(Exception):
    """The requested target no longer matches the selected objective."""
