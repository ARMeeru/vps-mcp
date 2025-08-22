"""Enhanced error handling and user feedback utilities."""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for better user feedback."""

    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    SECURITY = "security"
    SYSTEM = "system"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    FILE_SYSTEM = "filesystem"
    SERVICE = "service"
    TIMEOUT = "timeout"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class VPSManagerError:
    """Enhanced error information for better user feedback."""

    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    technical_details: str
    user_action: str
    server_name: Optional[str] = None
    operation: Optional[str] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for JSON serialization."""
        return {
            "error": True,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "user_action": self.user_action,
            "server_name": self.server_name,
            "operation": self.operation,
            "error_code": self.error_code,
            "technical_details": self.technical_details,
        }

    def to_json(self) -> str:
        """Convert error to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class ErrorHandler:
    """Centralized error handling and user feedback."""

    @staticmethod
    def handle_connection_error(
        server_name: str, operation: str, exception: Exception
    ) -> VPSManagerError:
        """Handle SSH connection errors."""

        error_mapping = {
            "PermissionDenied": {
                "category": ErrorCategory.AUTHENTICATION,
                "severity": ErrorSeverity.HIGH,
                "message": f"Authentication failed for server '{server_name}'",
                "user_action": (
                    "Check your SSH key permissions and server configuration. "
                    "Ensure the public key is added to the server's "
                    "authorized_keys file."
                ),
            },
            "ConnectionRefused": {
                "category": ErrorCategory.CONNECTION,
                "severity": ErrorSeverity.HIGH,
                "message": f"Connection refused by server '{server_name}'",
                "user_action": (
                    "Verify the server is running, the hostname/IP is correct, "
                    "and SSH port is open. Check firewall settings."
                ),
            },
            "NoValidConnectionsError": {
                "category": ErrorCategory.CONNECTION,
                "severity": ErrorSeverity.HIGH,
                "message": f"No valid connections available for server '{server_name}'",
                "user_action": (
                    "Check network connectivity and server availability. "
                    "Verify SSH service is running on the server."
                ),
            },
            "ConnectionLost": {
                "category": ErrorCategory.CONNECTION,
                "severity": ErrorSeverity.MEDIUM,
                "message": f"Connection lost to server '{server_name}'",
                "user_action": (
                    "The connection was dropped. This may be temporary - try again. "
                    "Check network stability."
                ),
            },
            "TimeoutError": {
                "category": ErrorCategory.TIMEOUT,
                "severity": ErrorSeverity.MEDIUM,
                "message": f"Connection timeout to server '{server_name}'",
                "user_action": (
                    "The server is not responding. Check network connectivity and "
                    "server status."
                ),
            },
        }

        exception_type = type(exception).__name__
        error_info = error_mapping.get(
            exception_type,
            {
                "category": ErrorCategory.CONNECTION,
                "severity": ErrorSeverity.MEDIUM,
                "message": (
                    f"Connection error for server '{server_name}': {str(exception)}"
                ),
                "user_action": (
                    "Check your network connection and server configuration."
                ),
            },
        )

        return VPSManagerError(
            category=error_info["category"],
            severity=error_info["severity"],
            message=error_info["message"],
            technical_details=f"{exception_type}: {str(exception)}",
            user_action=error_info["user_action"],
            server_name=server_name,
            operation=operation,
            error_code=exception_type,
        )

    @staticmethod
    def handle_command_error(
        server_name: str,
        command: str,
        exception: Exception,
        exit_code: Optional[int] = None,
    ) -> VPSManagerError:
        """Handle command execution errors."""

        if exit_code is not None and exit_code != 0:
            return VPSManagerError(
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.LOW,
                message=(
                    f"Command failed on server '{server_name}' with exit code "
                    f"{exit_code}"
                ),
                technical_details=(
                    f"Command: {command}\nExit code: {exit_code}\nError: "
                    f"{str(exception)}"
                ),
                user_action=(
                    f"The command '{command}' failed. Check the command syntax and "
                    "server state."
                ),
                server_name=server_name,
                operation="exec_command",
                error_code=f"EXIT_{exit_code}",
            )

        if "Permission denied" in str(exception):
            return VPSManagerError(
                category=ErrorCategory.AUTHORIZATION,
                severity=ErrorSeverity.MEDIUM,
                message=(
                    f"Permission denied executing command on server '{server_name}'"
                ),
                technical_details=f"Command: {command}\nError: {str(exception)}",
                user_action=(
                    "Check user permissions. You may need sudo privileges or different "
                    "user account for this operation."
                ),
                server_name=server_name,
                operation="exec_command",
                error_code="PERMISSION_DENIED",
            )

        return VPSManagerError(
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.MEDIUM,
            message=f"Command execution failed on server '{server_name}'",
            technical_details=f"Command: {command}\nError: {str(exception)}",
            user_action=(
                "Check the command syntax and ensure the server is properly configured."
            ),
            server_name=server_name,
            operation="exec_command",
            error_code="COMMAND_FAILED",
        )

    @staticmethod
    def handle_file_operation_error(
        server_name: str, operation: str, file_path: str, exception: Exception
    ) -> VPSManagerError:
        """Handle file operation errors."""

        if "No such file" in str(exception) or "not found" in str(exception).lower():
            return VPSManagerError(
                category=ErrorCategory.FILE_SYSTEM,
                severity=ErrorSeverity.LOW,
                message=f"File or directory not found: {file_path}",
                technical_details=f"Operation: {operation}\nPath: {file_path}\nError: {
                    str(exception)}",
                user_action=f"Verify the path '{file_path}' exists and is accessible.",
                server_name=server_name,
                operation=operation,
                error_code="FILE_NOT_FOUND",
            )

        if "Permission denied" in str(exception):
            return VPSManagerError(
                category=ErrorCategory.AUTHORIZATION,
                severity=ErrorSeverity.MEDIUM,
                message=f"Permission denied accessing: {file_path}",
                technical_details=(
                    f"Operation: {operation}\nPath: {file_path}\nError: "
                    f"{str(exception)}"
                ),
                user_action=(
                    f"Check file permissions for '{file_path}'. You may need different "
                    "user privileges."
                ),
                server_name=server_name,
                operation=operation,
                error_code="FILE_PERMISSION_DENIED",
            )

        if "No space left" in str(exception):
            return VPSManagerError(
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.HIGH,
                message=f"Insufficient disk space on server '{server_name}'",
                technical_details=(
                    f"Operation: {operation}\nPath: {file_path}\nError: "
                    f"{str(exception)}"
                ),
                user_action=(
                    "Free up disk space on the server or use a different location."
                ),
                server_name=server_name,
                operation=operation,
                error_code="DISK_FULL",
            )

        return VPSManagerError(
            category=ErrorCategory.FILE_SYSTEM,
            severity=ErrorSeverity.MEDIUM,
            message=f"File operation failed: {operation}",
            technical_details=f"Operation: {operation}\nPath: {file_path}\nError: {
                str(exception)}",
            user_action="Check file system permissions and server state.",
            server_name=server_name,
            operation=operation,
            error_code="FILE_OPERATION_FAILED",
        )

    @staticmethod
    def handle_security_error(
        operation: str,
        reason: str,
        server_name: Optional[str] = None,
        details: Optional[str] = None,
    ) -> VPSManagerError:
        """Handle security validation errors."""

        return VPSManagerError(
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.HIGH,
            message=f"Security violation: {reason}",
            technical_details=(
                f"Operation: {operation}\nReason: {reason}\nDetails: {details or 'N/A'}"
            ),
            user_action=(
                "This operation was blocked for security reasons. Review your command "
                "or file path."
            ),
            server_name=server_name,
            operation=operation,
            error_code="SECURITY_VIOLATION",
        )

    @staticmethod
    def handle_configuration_error(
        component: str, issue: str, suggestion: str
    ) -> VPSManagerError:
        """Handle configuration errors."""

        return VPSManagerError(
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH,
            message=f"Configuration error in {component}: {issue}",
            technical_details=f"Component: {component}\nIssue: {issue}",
            user_action=suggestion,
            operation="configuration",
            error_code="CONFIG_ERROR",
        )

    @staticmethod
    def handle_service_error(
        server_name: str, service_name: str, action: str, exception: Exception
    ) -> VPSManagerError:
        """Handle service management errors."""

        if "Unit not found" in str(exception):
            return VPSManagerError(
                category=ErrorCategory.SERVICE,
                severity=ErrorSeverity.LOW,
                message=f"Service '{service_name}' not found on server '{server_name}'",
                technical_details=(
                    f"Action: {action}\nService: {service_name}\nError: "
                    f"{str(exception)}"
                ),
                user_action=(
                    f"Verify the service name '{service_name}' is correct and "
                    "installed on the server."
                ),
                server_name=server_name,
                operation="service_management",
                error_code="SERVICE_NOT_FOUND",
            )

        if "Failed to" in str(exception) and action in [
            "start",
            "stop",
            "restart",
        ]:
            return VPSManagerError(
                category=ErrorCategory.SERVICE,
                severity=ErrorSeverity.MEDIUM,
                message=(
                    f"Failed to {action} service '{service_name}' on server "
                    f"'{server_name}'"
                ),
                technical_details=(
                    f"Action: {action}\nService: {service_name}\nError: "
                    f"{str(exception)}"
                ),
                user_action=(
                    f"Check service configuration and dependencies for "
                    f"'{service_name}'. Review service logs for details."
                ),
                server_name=server_name,
                operation="service_management",
                error_code="SERVICE_ACTION_FAILED",
            )

        return VPSManagerError(
            category=ErrorCategory.SERVICE,
            severity=ErrorSeverity.MEDIUM,
            message=(
                f"Service management error for '{service_name}' on server "
                f"'{server_name}'"
            ),
            technical_details=(
                f"Action: {action}\nService: {service_name}\nError: "
                f"{str(exception)}"
            ),
            user_action="Check service status and server configuration.",
            server_name=server_name,
            operation="service_management",
            error_code="SERVICE_ERROR",
        )


def error_handler(operation: str):
    """Decorator for consistent error handling across tools."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Error in {operation}: {e}")

                # Extract server name if available
                server_name = None
                if args and len(args) > 1:
                    server_name = args[1] if isinstance(args[1], str) else None
                elif "server_name" in kwargs:
                    server_name = kwargs["server_name"]

                # Create appropriate error response
                if "connection" in operation.lower():
                    error = ErrorHandler.handle_connection_error(
                        server_name or "unknown", operation, e
                    )
                elif "command" in operation.lower():
                    error = ErrorHandler.handle_command_error(
                        server_name or "unknown",
                        kwargs.get("command", "unknown"),
                        e,
                    )
                elif "file" in operation.lower():
                    error = ErrorHandler.handle_file_operation_error(
                        server_name or "unknown",
                        operation,
                        kwargs.get("file_path")
                        or kwargs.get("directory_path", "unknown"),
                        e,
                    )
                elif "service" in operation.lower():
                    error = ErrorHandler.handle_service_error(
                        server_name or "unknown",
                        kwargs.get("service_name", "unknown"),
                        kwargs.get("action", "unknown"),
                        e,
                    )
                else:
                    error = VPSManagerError(
                        category=ErrorCategory.UNKNOWN,
                        severity=ErrorSeverity.MEDIUM,
                        message=f"Unexpected error in {operation}",
                        technical_details=str(e),
                        user_action=(
                            "Please try again or contact support if the issue persists."
                        ),
                        server_name=server_name,
                        operation=operation,
                        error_code=type(e).__name__,
                    )

                return error.to_dict()

        return wrapper

    return decorator


def format_success_response(
    operation: str,
    data: Any,
    server_name: Optional[str] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Format successful operation response."""

    response = {"success": True, "operation": operation, "data": data}

    if server_name:
        response["server_name"] = server_name

    if message:
        response["message"] = message

    return response


def validate_server_name(
    server_name: str, available_servers: list
) -> Optional[VPSManagerError]:
    """Validate server name and return error if invalid."""

    if not server_name:
        return ErrorHandler.handle_configuration_error(
            "server_name",
            "Server name is required",
            "Provide a valid server name from your configuration",
        )

    if server_name not in available_servers:
        return ErrorHandler.handle_configuration_error(
            "server_name",
            f"Server '{server_name}' not found in configuration",
            f"Available servers: {', '.join(available_servers)}",
        )

    return None


def validate_required_params(
    params: Dict[str, Any], required: list
) -> Optional[VPSManagerError]:
    """Validate required parameters and return error if missing."""

    missing = [param for param in required if not params.get(param)]

    if missing:
        return ErrorHandler.handle_configuration_error(
            "parameters",
            f"Missing required parameters: {', '.join(missing)}",
            f"Please provide values for: {', '.join(missing)}",
        )

    return None
