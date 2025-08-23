"""Security validation module for command and path safety."""

import logging
import re
import shlex
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class VPSManagerError(Exception):
    """Base exception for VPS Manager errors."""

    pass


class SecurityError(VPSManagerError):
    """Security validation errors."""

    pass


class CommandSecurityError(SecurityError):
    """Command security validation errors."""

    pass


class PathSecurityError(SecurityError):
    """Path security validation errors."""

    pass


class SecurityValidator:
    """Security validation for commands and file paths."""

    # Dangerous command patterns that should be blocked
    DANGEROUS_PATTERNS = [
        # System destruction
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+\*",
        r">\s*/dev/sd[a-z]",
        r"dd\s+if=/dev/(zero|random|urandom)",
        r"mkfs\.",
        r"fdisk",
        r"parted",
        # Fork bombs and resource exhaustion
        r":(){ :|:& };:",  # Classic fork bomb
        r"while\s+true.*do.*done",  # Infinite loops
        r"yes\s*>",  # Disk filling
        # Dangerous permissions
        r"chmod\s+-R\s+777\s+/",
        r"chown\s+-R\s+.*\s+/",
        # Network attacks
        r"iptables\s+-F",  # Flush firewall rules
        r"ufw\s+--force\s+reset",
        # System modification
        r"init\s+0",  # Shutdown
        r"init\s+6",  # Reboot
        r"shutdown",
        r"reboot",
        r"poweroff",
        r"halt",
        # Package management dangers
        r"apt\s+remove\s+--purge.*kernel",
        r"yum\s+remove.*kernel",
        r"dnf\s+remove.*kernel",
        # Crypto mining indicators
        r"xmrig",
        r"cpuminer",
        r"minerd",
    ]

    # Additional patterns for sudo commands
    DANGEROUS_SUDO_PATTERNS = [
        r"sudo\s+su\s+-",  # Switch to root permanently
        r"sudo\s+bash",  # Root shell
        r"sudo\s+sh",  # Root shell
        r"sudo\s+passwd",  # Password changes
        r"sudo\s+visudo",  # Sudoers modification
        r"sudo\s+deluser",  # User deletion
        r"sudo\s+userdel",  # User deletion
    ]

    # File extensions that should not be executed
    DANGEROUS_EXTENSIONS = {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".pif",
        ".scr",
        ".vbs",
        ".vbe",
        ".js",
        ".jar",
        ".app",
        ".deb",
        ".rpm",
    }

    def __init__(
        self,
        allowed_paths: List[str],
        additional_blocked_commands: Optional[List[str]] = None,
    ):
        """Initialize security validator.

        Args:
            allowed_paths: List of allowed filesystem paths
            additional_blocked_commands: Additional command patterns to block
        """
        # Don't resolve() allowed paths as they are for remote filesystem, not local
        self.allowed_paths = [Path(p).absolute() for p in allowed_paths]
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS
        ]
        self.compiled_sudo_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.DANGEROUS_SUDO_PATTERNS
        ]

        # Add additional blocked commands
        if additional_blocked_commands:
            additional_patterns = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in additional_blocked_commands
            ]
            self.compiled_patterns.extend(additional_patterns)

        logger.info(
            f"Security validator initialized with {len(self.allowed_paths)} "
            "allowed paths"
        )

    def validate_command(
        self, command: str, max_length: int = 10000
    ) -> Tuple[bool, Optional[str]]:
        """Validate a command for security issues.

        Args:
            command: Command string to validate
            max_length: Maximum allowed command length

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check command length
        if len(command) > max_length:
            return (
                False,
                f"Command exceeds maximum length of {max_length} characters",
            )

        # Check for null bytes
        if "\x00" in command:
            return False, "Command contains null bytes"

        # Normalize whitespace for pattern matching
        normalized_command = " ".join(command.split())

        # Check against dangerous patterns
        for pattern in self.compiled_patterns:
            if pattern.search(normalized_command):
                return (
                    False,
                    f"Command matches dangerous pattern: {pattern.pattern}",
                )

        # Additional checks for sudo commands
        if "sudo" in normalized_command.lower():
            for pattern in self.compiled_sudo_patterns:
                if pattern.search(normalized_command):
                    return (
                        False,
                        f"Sudo command matches dangerous pattern: {
                            pattern.pattern}",
                    )

        # Check for command chaining that might bypass restrictions
        dangerous_chains = ["&&", "||", ";", "|", "$(", "`"]
        for chain in dangerous_chains:
            if chain in command:
                # Allow some safe chaining patterns
                if not self._is_safe_chaining(command, chain):
                    logger.warning(
                        f"Command contains potentially dangerous chaining: {chain}"
                    )

        return True, None

    def _is_safe_chaining(self, command: str, chain_type: str) -> bool:
        """Check if command chaining is safe.

        Args:
            command: Full command string
            chain_type: Type of chaining found

        Returns:
            True if chaining appears safe
        """
        # Simple heuristics for safe chaining
        safe_patterns = [
            r"echo\s+.*\s*\|\s*grep",  # echo | grep
            r"cat\s+.*\s*\|\s*grep",  # cat | grep
            r"ls\s+.*\s*\|\s*grep",  # ls | grep
            r"ps\s+.*\s*\|\s*grep",  # ps | grep
            r"find\s+.*\s*\|\s*head",  # find | head
        ]

        for pattern in safe_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        return False

    def sanitize_command_input(self, user_input: str) -> str:
        """Sanitize user input that will be part of a command.

        Args:
            user_input: Raw user input

        Returns:
            Sanitized input safe for shell execution
        """
        # Use shlex to properly quote the input
        return shlex.quote(user_input.strip())

    def validate_file_path(
        self, file_path: str, operation: str = "access"
    ) -> Tuple[bool, Optional[str], Path]:
        """Validate a file path for security.

        Args:
            file_path: Path to validate
            operation: Type of operation (read, write, execute)

        Returns:
            Tuple of (is_valid, error_message, resolved_path)
        """
        try:
            # Convert to Path object and resolve
            path = Path(file_path).expanduser()

            # Check for directory traversal attempts
            if ".." in path.parts:
                return False, "Path contains directory traversal (..)", path

            # Get absolute path without resolving symlinks (for remote filesystem)
            # Note: We don't resolve() because that would use local filesystem symlinks
            resolved_path = path.absolute()

            # Check against allowed paths
            is_allowed = False
            for allowed_path in self.allowed_paths:
                try:
                    resolved_path.relative_to(allowed_path)
                    is_allowed = True
                    break
                except ValueError:
                    continue

            if not is_allowed:
                return (
                    False,
                    f"Path not in allowed directories: {resolved_path}",
                    resolved_path,
                )

            # Check file extension for execution operations
            if (
                operation == "execute"
                and resolved_path.suffix.lower() in self.DANGEROUS_EXTENSIONS
            ):
                return (
                    False,
                    f"Dangerous file extension for execution: {
                        resolved_path.suffix}",
                    resolved_path,
                )

            # Additional checks for special files
            if self._is_special_file(resolved_path):
                if operation in ["write", "execute"]:
                    return (
                        False,
                        f"Cannot {operation} special file: {resolved_path}",
                        resolved_path,
                    )

            return True, None, resolved_path

        except Exception as e:
            return False, f"Path validation error: {e}", Path(file_path)

    def _is_special_file(self, path: Path) -> bool:
        """Check if path points to a special file that should be protected.

        Args:
            path: Path to check

        Returns:
            True if it's a special file
        """
        special_paths = [
            "/dev",
            "/proc",
            "/sys",
            "/boot",
            "/etc/passwd",
            "/etc/shadow",
            "/etc/sudoers",
            "/etc/ssh",
            "/root",
        ]

        path_str = str(path)
        for special in special_paths:
            if path_str.startswith(special):
                return True

        return False

    def validate_file_size(
        self, file_size: int, max_size_mb: int
    ) -> Tuple[bool, Optional[str]]:
        """Validate file size against limits.

        Args:
            file_size: File size in bytes
            max_size_mb: Maximum allowed size in MB

        Returns:
            Tuple of (is_valid, error_message)
        """
        max_size_bytes = max_size_mb * 1024 * 1024

        if file_size > max_size_bytes:
            return (
                False,
                f"File size {file_size} exceeds limit of {max_size_mb}MB",
            )

        return True, None

    def check_sudo_requirements(self, command: str) -> bool:
        """Check if command requires sudo privileges.

        Args:
            command: Command to check

        Returns:
            True if sudo is required
        """
        # Commands that typically require sudo
        sudo_required_commands = [
            "systemctl",
            "service",
            "mount",
            "umount",
            "iptables",
            "ufw",
            "apt",
            "yum",
            "dnf",
            "pacman",
            "nginx",
            "apache2",
        ]

        # Paths that typically require sudo
        sudo_required_paths = [
            "/etc/",
            "/var/log/",
            "/usr/",
            "/opt/",
            "/boot/",
            "/sys/",
        ]

        command_lower = command.lower()

        # Check if command starts with sudo
        if command_lower.startswith("sudo"):
            return True

        # Check for commands that need sudo
        for cmd in sudo_required_commands:
            if cmd in command_lower:
                return True

        # Check for paths that need sudo
        for path in sudo_required_paths:
            if path in command_lower:
                return True

        return False

    def create_safe_command(
        self,
        base_command: str,
        user_args: List[str],
        use_sudo: bool = False,
        sudo_password: Optional[str] = None,
    ) -> str:
        """Create a safe command with properly escaped arguments.

        Args:
            base_command: Base command (e.g., 'ls', 'cat')
            user_args: User-provided arguments
            use_sudo: Whether to use sudo
            sudo_password: Sudo password if needed

        Returns:
            Safe command string
        """
        # Validate base command
        is_valid, error = self.validate_command(base_command)
        if not is_valid:
            raise CommandSecurityError(f"Base command validation failed: {error}")

        # Sanitize all arguments
        safe_args = [self.sanitize_command_input(arg) for arg in user_args]

        # Build command
        command_parts = [base_command] + safe_args
        command = " ".join(command_parts)

        # Add sudo if required (NOTE: Actual secure sudo execution handled by
        # SecureSudoHandler)
        if use_sudo:
            # This method only prepares commands for validation
            # Secure sudo execution is handled by SecureSudoHandler in command
            # execution
            command = f"sudo {command}"

        return command

    def log_security_event(self, event_type: str, details: dict) -> None:
        """Log security-related events for audit purposes.

        Args:
            event_type: Type of security event
            details: Event details dictionary
        """
        logger.warning(f"Security event: {event_type} - {details}")


# Convenience functions for common validations
def validate_command_safe(
    command: str,
    allowed_paths: List[str],
    additional_blocked: List[str] = None,
) -> None:
    """Validate command and raise exception if unsafe.

    Args:
        command: Command to validate
        allowed_paths: List of allowed filesystem paths
        additional_blocked: Additional blocked command patterns

    Raises:
        CommandSecurityError: If command is unsafe
    """
    validator = SecurityValidator(allowed_paths, additional_blocked)
    is_valid, error = validator.validate_command(command)

    if not is_valid:
        raise CommandSecurityError(error)


def validate_path_safe(
    file_path: str, allowed_paths: List[str], operation: str = "access"
) -> Path:
    """Validate path and return resolved path if safe.

    Args:
        file_path: Path to validate
        allowed_paths: List of allowed filesystem paths
        operation: Type of operation

    Returns:
        Resolved path if valid

    Raises:
        PathSecurityError: If path is unsafe
    """
    validator = SecurityValidator(allowed_paths)
    is_valid, error, resolved_path = validator.validate_file_path(file_path, operation)

    if not is_valid:
        raise PathSecurityError(error)

    return resolved_path
