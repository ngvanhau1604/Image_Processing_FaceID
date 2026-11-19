"""Default ASGI entry point for the Smart Door application."""
from smartdoor.server import app, create_app

__all__ = ["app", "create_app"]
