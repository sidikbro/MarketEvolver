"""Domain errors."""


class ValidationError(ValueError):
    """Raised when a domain invariant is violated."""


class PointInTimeViolation(ValidationError):
    """Raised when information was unavailable at the claimed cutoff."""


class GovernanceViolation(ValidationError):
    """Raised when a forbidden capability or flow is requested."""


class ConfigurationError(ValidationError):
    """Raised when persistence cannot be configured safely."""


class IntegrityViolation(ValidationError):
    """Raised when immutable content or its provenance does not match."""


class ImmutableRecordError(IntegrityViolation):
    """Raised on an attempted update or deletion of an immutable record."""
