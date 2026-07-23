"""Code Intelligence Parser package.

Exports the public surface area of the parser subsystem.
"""

from backend.app.parsers.registry import ParserRegistry, get_parser_registry

__all__ = ["ParserRegistry", "get_parser_registry"]
