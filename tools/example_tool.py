"""
Example dynamic tool.

HOW TO ADD YOUR OWN TOOLS
─────────────────────────
1. Copy this file and give it a descriptive name (e.g. tools/weather.py).
2. Implement one or more tools inside register().
3. Restart the server — it auto-discovers every *.py file in tools/ that
   exports a register(mcp) function.

The `mcp` object passed to register() is the same FastMCP instance used
by the rest of the server, so all standard decorators work:
  @mcp.tool()      — callable function Claude can invoke
  @mcp.resource()  — data source Claude can read
  @mcp.prompt()    — reusable prompt template

REMOVING THIS EXAMPLE
──────────────────────
Delete this file. It will no longer be loaded on the next restart.
"""


def register(mcp) -> None:  # noqa: ANN001

    @mcp.tool()
    def greet(name: str) -> str:
        """
        Greet someone by name.

        This is an example tool — feel free to delete or replace it.

        Args:
            name: The name of the person to greet.

        Returns a greeting string.
        """
        return f"Hello, {name}! (from my-own-mcp-server)"
