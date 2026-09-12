"""Text-to-action agent for NHS Care Identity Management (CIM).

Turns unstructured Registration Authority (RA) correspondence into validated,
policy-checked CIM action activities, and applies them through a pluggable
backend. Every module here is standard library only; the MCP server module is
the sole exception and needs the `mcp` package.
"""

__version__ = "0.1.0"
