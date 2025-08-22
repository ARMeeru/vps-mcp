"""Main MCP server for VPS Manager."""

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
)

from .config import VPSManagerConfig, load_config
from .connection_pool import ConnectionManager
from .tools.command import CommandTool
from .tools.file_ops import FileOperationsTool
from .tools.monitoring import SystemMonitoringTool
from .tools.services import ServiceManagementTool
from .utils.error_handling import (
    ErrorCategory,
    ErrorHandler,
    ErrorSeverity,
    VPSManagerError,
    format_success_response,
    validate_required_params,
    validate_server_name,
)

logger = logging.getLogger(__name__)


class MCPVPSServer:
    """Main MCP VPS Manager server."""

    def __init__(self, config: VPSManagerConfig):
        """Initialize the MCP server.

        Args:
            config: VPS Manager configuration
        """
        self.config = config
        self.server = Server("mcp-vps-manager")
        self.connection_manager = ConnectionManager()

        # Initialize tools
        self.command_tool = CommandTool(self.connection_manager)
        self.file_ops_tool = FileOperationsTool(self.connection_manager)
        self.monitoring_tool = SystemMonitoringTool(self.connection_manager)
        self.service_tool = ServiceManagementTool(self.connection_manager)

        # Set up server handlers
        self._setup_handlers()

        logger.info("MCP VPS Manager server initialized")

    def _setup_handlers(self) -> None:
        """Set up MCP server handlers."""

        # List available resources (servers)
        @self.server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            """List available VPS servers as resources."""
            resources = []

            for server_config in self.config.servers:
                resources.append(
                    Resource(
                        uri=f"vps://{server_config.name}",
                        name=f"VPS Server: {server_config.name}",
                        description=(
                            f"Connection to {server_config.host}:{server_config.port}"
                        ),
                        mimeType="application/json",
                    )
                )

            return resources

        # Read resource content (server status)
        @self.server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            """Read resource content (server status)."""
            if not uri.startswith("vps://"):
                raise ValueError(f"Unknown resource URI: {uri}")

            server_name = uri[6:]  # Remove "vps://" prefix

            # Get server status
            status = self.connection_manager.get_status_all().get(server_name)
            if not status:
                raise ValueError(f"Server not found: {server_name}")

            # Get detailed system status if connection is available
            try:
                system_status = await self.monitoring_tool.get_system_status(
                    server_name
                )
                status["system_metrics"] = system_status.get("data", {})
            except Exception as e:
                logger.warning(f"Could not get system metrics for {server_name}: {e}")
                status["system_metrics"] = {"error": str(e)}

            import json

            return json.dumps(status, indent=2)

        # List available tools
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """List available MCP tools."""
            return [
                Tool(
                    name="exec_command",
                    description=(
                        "Execute shell commands on VPS servers with security validation"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Shell command to execute",
                            },
                            "server": {
                                "type": "string",
                                "description": (
                                    "Target server name (optional, uses first "
                                    "available if not specified)"
                                ),
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Command timeout in seconds",
                                "default": 30,
                            },
                            "background": {
                                "type": "boolean",
                                "description": "Run command in background",
                                "default": False,
                            },
                            "stream_output": {
                                "type": "boolean",
                                "description": (
                                    "Stream output for long-running commands"
                                ),
                                "default": False,
                            },
                            "priority": {
                                "type": "string",
                                "description": "Command priority for queue",
                                "enum": ["low", "normal", "high", "critical"],
                                "default": "normal",
                            },
                            "use_queue": {
                                "type": "boolean",
                                "description": "Force use/bypass of queue system",
                            },
                        },
                        "required": ["command"],
                    },
                ),
                Tool(
                    name="read_file",
                    description="Read file content from VPS servers via SFTP",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to read",
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "encoding": {
                                "type": "string",
                                "description": "Text encoding",
                                "default": "utf-8",
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="write_file",
                    description="Write file content to VPS servers via SFTP",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to write",
                            },
                            "content": {
                                "type": "string",
                                "description": "File content to write",
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "encoding": {
                                "type": "string",
                                "description": "Text encoding",
                                "default": "utf-8",
                            },
                            "create_dirs": {
                                "type": "boolean",
                                "description": (
                                    "Create parent directories if they don't exist"
                                ),
                                "default": False,
                            },
                            "backup": {
                                "type": "boolean",
                                "description": "Create backup of existing file",
                                "default": True,
                            },
                        },
                        "required": ["path", "content"],
                    },
                ),
                Tool(
                    name="upload_file",
                    description="Upload file from local system to VPS server",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "local_path": {
                                "type": "string",
                                "description": "Local file path",
                            },
                            "remote_path": {
                                "type": "string",
                                "description": "Remote destination path",
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "create_dirs": {
                                "type": "boolean",
                                "description": "Create parent directories if needed",
                                "default": False,
                            },
                        },
                        "required": ["local_path", "remote_path"],
                    },
                ),
                Tool(
                    name="download_file",
                    description="Download file from VPS server to local system",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "remote_path": {
                                "type": "string",
                                "description": "Remote file path",
                            },
                            "local_path": {
                                "type": "string",
                                "description": "Local destination path",
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                        },
                        "required": ["remote_path", "local_path"],
                    },
                ),
                Tool(
                    name="get_system_status",
                    description="Get comprehensive system status and metrics",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "detailed": {
                                "type": "boolean",
                                "description": "Include detailed metrics",
                                "default": False,
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="service_control",
                    description="Control system services (start, stop, restart, etc.)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "service_name": {
                                "type": "string",
                                "description": "Name of the service",
                            },
                            "action": {
                                "type": "string",
                                "description": "Action to perform",
                                "enum": [
                                    "start",
                                    "stop",
                                    "restart",
                                    "reload",
                                    "status",
                                    "enable",
                                    "disable",
                                ],
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "force": {
                                "type": "boolean",
                                "description": "Force action even if risky",
                                "default": False,
                            },
                        },
                        "required": ["service_name", "action"],
                    },
                ),
                Tool(
                    name="list_services",
                    description="List system services",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "running_only": {
                                "type": "boolean",
                                "description": "Show only running services",
                                "default": False,
                            },
                            "pattern": {
                                "type": "string",
                                "description": (
                                    "Filter services by name pattern (regex)"
                                ),
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="get_service_logs",
                    description="Get service logs",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "service_name": {
                                "type": "string",
                                "description": "Service name",
                            },
                            "server": {
                                "type": "string",
                                "description": "Target server name (optional)",
                            },
                            "lines": {
                                "type": "integer",
                                "description": "Number of lines to retrieve",
                                "default": 50,
                            },
                        },
                        "required": ["service_name"],
                    },
                ),
                Tool(
                    name="get_queue_status",
                    description="Get status of command queues for monitoring",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "server": {
                                "type": "string",
                                "description": (
                                    "Target server name (optional, gets all if not "
                                    "specified)"
                                ),
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="cleanup_queue_results",
                    description="Clean up old command queue results",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "max_age_hours": {
                                "type": "integer",
                                "description": (
                                    "Maximum age of results to keep in hours"
                                ),
                                "default": 24,
                            }
                        },
                        "required": [],
                    },
                ),
            ]

        # Handle tool calls
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool execution calls with enhanced error handling."""
            logger.info(f"Tool call: {name} with arguments: {arguments}")

            try:
                # Validate tool exists
                valid_tools = {
                    "exec_command",
                    "read_file",
                    "write_file",
                    "upload_file",
                    "download_file",
                    "get_system_status",
                    "service_control",
                    "list_services",
                    "get_service_logs",
                }

                if name not in valid_tools:
                    error = VPSManagerError(
                        category=ErrorCategory.CONFIGURATION,
                        severity=ErrorSeverity.MEDIUM,
                        message=f"Unknown tool: {name}",
                        technical_details=f"Tool '{name}' is not supported",
                        user_action=f"Available tools: {
                            ', '.join(
                                sorted(valid_tools))}",
                        operation=name,
                        error_code="UNKNOWN_TOOL",
                    )
                    return [TextContent(type="text", text=error.to_json())]

                # Get available servers for validation
                available_servers = self.connection_manager.list_servers()

                # Tool-specific validation and execution
                result = await self._execute_tool(name, arguments, available_servers)

                # Format successful result
                if isinstance(result, dict) and result.get("error"):
                    # Result is already an error response
                    result_text = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    # Wrap successful result
                    success_response = format_success_response(
                        operation=name,
                        data=result,
                        server_name=arguments.get("server"),
                        message=f"Tool '{name}' executed successfully",
                    )
                    result_text = json.dumps(
                        success_response, indent=2, ensure_ascii=False
                    )

                return [TextContent(type="text", text=result_text)]

            except Exception as e:
                logger.exception(f"Unexpected error in tool execution: {e}")

                # Create comprehensive error response
                error = VPSManagerError(
                    category=ErrorCategory.SYSTEM,
                    severity=ErrorSeverity.HIGH,
                    message=f"Unexpected error executing tool '{name}'",
                    technical_details=(f"Exception: {type(e).__name__}: {str(e)}"),
                    user_action=(
                        "Please try again or contact support if the issue persists."
                    ),
                    operation=name,
                    error_code=type(e).__name__,
                )

                return [TextContent(type="text", text=error.to_json())]

    async def _execute_tool(
        self, name: str, arguments: dict, available_servers: list
    ) -> Any:
        """Execute individual tool with validation."""

        if name == "exec_command":
            # Validate required parameters
            error = validate_required_params(arguments, ["command"])
            if error:
                return error.to_dict()

            # Validate server if specified
            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.command_tool.exec_command(
                command=arguments["command"],
                server=server_name,
                timeout=arguments.get("timeout", 30),
                background=arguments.get("background", False),
                stream_output=arguments.get("stream_output", False),
                priority=arguments.get("priority", "normal"),
                use_queue=arguments.get("use_queue"),
            )

        elif name == "read_file":
            # Validate required parameters
            error = validate_required_params(arguments, ["path"])
            if error:
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.file_ops_tool.read_file(
                path=arguments["path"],
                server=server_name,
                encoding=arguments.get("encoding", "utf-8"),
            )

        elif name == "write_file":
            # Validate required parameters
            error = validate_required_params(arguments, ["path", "content"])
            if error:
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.file_ops_tool.write_file(
                path=arguments["path"],
                content=arguments["content"],
                server=server_name,
                encoding=arguments.get("encoding", "utf-8"),
                create_dirs=arguments.get("create_dirs", False),
                backup=arguments.get("backup", True),
            )

        elif name == "upload_file":
            error = validate_required_params(arguments, ["local_path", "remote_path"])
            if error:
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.file_ops_tool.upload_file(
                local_path=arguments["local_path"],
                remote_path=arguments["remote_path"],
                server=server_name,
                create_dirs=arguments.get("create_dirs", False),
            )

        elif name == "download_file":
            error = validate_required_params(arguments, ["remote_path", "local_path"])
            if error:
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.file_ops_tool.download_file(
                remote_path=arguments["remote_path"],
                local_path=arguments["local_path"],
                server=server_name,
            )

        elif name == "get_system_status":
            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.monitoring_tool.get_system_status(
                server=server_name, detailed=arguments.get("detailed", False)
            )

        elif name == "service_control":
            error = validate_required_params(arguments, ["service_name", "action"])
            if error:
                return error.to_dict()

            # Validate action
            valid_actions = [
                "start",
                "stop",
                "restart",
                "reload",
                "status",
                "enable",
                "disable",
            ]
            if arguments["action"] not in valid_actions:
                error = ErrorHandler.handle_configuration_error(
                    "service_action",
                    f"Invalid action '{arguments['action']}'",
                    f"Valid actions: {', '.join(valid_actions)}",
                )
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.service_tool.service_control(
                service_name=arguments["service_name"],
                action=arguments["action"],
                server=server_name,
                force=arguments.get("force", False),
            )

        elif name == "list_services":
            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.service_tool.list_services(
                server=server_name,
                running_only=arguments.get("running_only", False),
                pattern=arguments.get("pattern"),
            )

        elif name == "get_service_logs":
            error = validate_required_params(arguments, ["service_name"])
            if error:
                return error.to_dict()

            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.service_tool.get_service_logs(
                service_name=arguments["service_name"],
                server=server_name,
                lines=arguments.get("lines", 50),
            )

        elif name == "get_queue_status":
            server_name = arguments.get("server")
            if server_name:
                error = validate_server_name(server_name, available_servers)
                if error:
                    return error.to_dict()

            return await self.command_tool.get_queue_status(server=server_name)

        elif name == "cleanup_queue_results":
            return await self.command_tool.cleanup_queue_results(
                max_age_hours=arguments.get("max_age_hours", 24)
            )

        # This should never be reached due to validation above
        raise ValueError(f"Unhandled tool: {name}")

    async def initialize(self) -> None:
        """Initialize the server and connection pools."""
        # Add all configured servers to connection manager
        for server_config in self.config.servers:
            try:
                await self.connection_manager.add_server(
                    server_config, self.config.max_connections_per_server
                )
                logger.info(f"Added server: {server_config.name}")
            except Exception as e:
                logger.error(f"Failed to add server {server_config.name}: {e}")

        logger.info(
            f"Initialized {len(self.connection_manager.pools)} server connections"
        )

    async def shutdown(self) -> None:
        """Shutdown the server and close all connections."""
        logger.info("Shutting down MCP VPS Manager server")

        # Clean up background jobs
        self.command_tool.cleanup_completed_jobs()

        # Shutdown command queues
        await self.command_tool.shutdown_queues()

        # Shutdown all connection pools
        await self.connection_manager.shutdown_all()

        logger.info("Server shutdown complete")

    async def run(self) -> None:
        """Run the MCP server."""
        # Initialize server
        await self.initialize()

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            asyncio.create_task(self.shutdown())
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Run the MCP server with stdio transport
            async with stdio_server() as (read_stream, write_stream):
                logger.info("MCP VPS Manager server running on stdio")
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="mcp-vps-manager",
                        server_version="0.2.0",
                        capabilities={
                            "resources": {
                                "subscribe": False,
                                "listChanged": False,
                            },
                            "tools": {},
                        },
                    ),
                )
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            await self.shutdown()


def setup_logging(log_level: str, log_dir: str) -> None:
    """Set up logging configuration.

    Args:
        log_level: Logging level
        log_dir: Log directory path
    """
    import os
    from logging.handlers import RotatingFileHandler

    # Create log directory if it doesn't exist
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler for debug logs
    debug_handler = RotatingFileHandler(
        os.path.join(log_dir, "debug.log"),
        maxBytes=100 * 1024 * 1024,  # 100MB
        backupCount=5,
    )
    debug_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )
    debug_handler.setFormatter(debug_formatter)
    root_logger.addHandler(debug_handler)

    # File handler for errors
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "error.log"),
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=3,
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)


def main() -> None:
    """Main entry point for the MCP VPS Manager server."""
    parser = argparse.ArgumentParser(description="MCP VPS Manager Server")
    parser.add_argument("--config", type=str, help="Path to configuration file")
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override log level",
    )

    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config)

        # Override log level if specified
        if args.log_level:
            config.log_level = args.log_level

        # Set up logging
        setup_logging(config.log_level, config.log_dir)

        # Create and run server
        server = MCPVPSServer(config)
        asyncio.run(server.run())

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
