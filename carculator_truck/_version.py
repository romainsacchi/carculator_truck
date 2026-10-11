"""Package version; readable by the build backend without runtime imports."""

VERSION = "0.5.2"
__version__ = tuple(
    int(part) if part.isdigit() else part for part in VERSION.split(".")
)
