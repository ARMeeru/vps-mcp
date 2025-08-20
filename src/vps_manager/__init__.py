"""MCP VPS Manager - SSH-based Virtual Private Server management for LLMs."""

__version__ = "0.1.0"
__author__ = "Your Name"

from .server import MCPVPSServer, main

__all__ = ["MCPVPSServer", "main"]