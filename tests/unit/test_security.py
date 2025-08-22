"""Unit tests for security module."""

from pathlib import Path

import pytest

from src.vps_manager.security import (
    CommandSecurityError,
    PathSecurityError,
    SecurityValidator,
    validate_command_safe,
    validate_path_safe,
)


class TestSecurityValidator:
    """Test security validation functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.allowed_paths = ["/home/test", "/var/www", "/tmp"]
        self.additional_blocked = ["custom_blocked_command"]
        self.validator = SecurityValidator(self.allowed_paths, self.additional_blocked)

    def test_validate_command_safe_commands(self):
        """Test validation of safe commands."""
        safe_commands = [
            "ls -la",
            "cat /home/test/file.txt",
            "ps aux",
            "grep pattern /var/log/app.log",
            "find /home/test -name '*.py'",
            "echo 'hello world'",
        ]

        for command in safe_commands:
            is_valid, error = self.validator.validate_command(command)
            assert (
                is_valid
            ), f"Command '{command}' should be valid but got error: {error}"

    def test_validate_command_dangerous_patterns(self):
        """Test blocking of dangerous command patterns."""
        dangerous_commands = [
            "rm -rf /",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "chmod -R 777 /",
            ":(){ :|:& };:",  # Fork bomb
            "> /dev/sda",
            "shutdown now",
            "reboot",
            "poweroff",
        ]

        for command in dangerous_commands:
            is_valid, error = self.validator.validate_command(command)
            assert not is_valid, f"Dangerous command '{command}' should be blocked"
            assert error is not None

    def test_validate_command_sudo_patterns(self):
        """Test blocking of dangerous sudo patterns."""
        dangerous_sudo_commands = [
            "sudo su -",
            "sudo bash",
            "sudo passwd root",
            "sudo visudo",
            "sudo deluser testuser",
        ]

        for command in dangerous_sudo_commands:
            is_valid, error = self.validator.validate_command(command)
            assert not is_valid, f"Dangerous sudo command '{command}' should be blocked"

    def test_validate_command_additional_blocked(self):
        """Test additional blocked command patterns."""
        is_valid, error = self.validator.validate_command("custom_blocked_command test")
        assert not is_valid
        assert "custom_blocked_command" in error

    def test_validate_command_length_limit(self):
        """Test command length validation."""
        long_command = "echo " + "a" * 10000
        is_valid, error = self.validator.validate_command(long_command, max_length=5000)
        assert not is_valid
        assert "exceeds maximum length" in error

    def test_validate_command_null_bytes(self):
        """Test null byte detection."""
        command_with_null = "echo hello\x00world"
        is_valid, error = self.validator.validate_command(command_with_null)
        assert not is_valid
        assert "null bytes" in error

    def test_sanitize_command_input(self):
        """Test command input sanitization."""
        dangerous_input = "'; rm -rf /; echo '"
        sanitized = self.validator.sanitize_command_input(dangerous_input)
        assert "rm -rf" not in sanitized
        assert sanitized.startswith("'") and sanitized.endswith("'")

    def test_validate_file_path_allowed_paths(self):
        """Test file path validation against allowed paths."""
        # Test allowed paths
        allowed_files = [
            "/home/test/document.txt",
            "/var/www/index.html",
            "/tmp/tempfile",
        ]

        for path in allowed_files:
            is_valid, error, resolved = self.validator.validate_file_path(path)
            assert is_valid, f"Path '{path}' should be allowed but got error: {error}"

    def test_validate_file_path_blocked_paths(self):
        """Test blocking of paths outside allowed directories."""
        blocked_files = [
            "/etc/passwd",
            "/root/.ssh/id_rsa",
            "/boot/vmlinuz",
            "/home/other/file.txt",
        ]

        for path in blocked_files:
            is_valid, error, resolved = self.validator.validate_file_path(path)
            assert not is_valid, f"Path '{path}' should be blocked"

    def test_validate_file_path_directory_traversal(self):
        """Test blocking of directory traversal attempts."""
        traversal_attempts = [
            "/home/test/../../../etc/passwd",
            "/var/www/../../../root/.ssh/id_rsa",
            "/tmp/../../etc/shadow",
        ]

        for path in traversal_attempts:
            is_valid, error, resolved = self.validator.validate_file_path(path)
            assert not is_valid, f"Directory traversal '{path}' should be blocked"
            assert "directory traversal" in error

    def test_validate_file_path_dangerous_extensions(self):
        """Test blocking of dangerous file extensions for execution."""
        dangerous_files = [
            "/home/test/malware.exe",
            "/tmp/script.bat",
            "/var/www/app.jar",
        ]

        for path in dangerous_files:
            is_valid, error, resolved = self.validator.validate_file_path(
                path, "execute"
            )
            assert not is_valid, f"Dangerous file '{path}' should not be executable"

    def test_validate_file_size(self):
        """Test file size validation."""
        # Test valid size
        is_valid, error = self.validator.validate_file_size(
            1024 * 1024, 2
        )  # 1MB file, 2MB limit
        assert is_valid

        # Test oversized file
        is_valid, error = self.validator.validate_file_size(
            5 * 1024 * 1024, 2
        )  # 5MB file, 2MB limit
        assert not is_valid
        assert "exceeds limit" in error

    def test_check_sudo_requirements(self):
        """Test sudo requirement detection."""
        sudo_required_commands = [
            "systemctl restart nginx",
            "mount /dev/sdb1 /mnt",
            "iptables -A INPUT -j DROP",
            "apt install package",
        ]

        for command in sudo_required_commands:
            requires_sudo = self.validator.check_sudo_requirements(command)
            assert requires_sudo, f"Command '{command}' should require sudo"

        # Test commands that don't require sudo
        no_sudo_commands = ["ls -la", "cat file.txt", "ps aux"]

        for command in no_sudo_commands:
            requires_sudo = self.validator.check_sudo_requirements(command)
            assert not requires_sudo, f"Command '{command}' should not require sudo"

    def test_create_safe_command(self):
        """Test safe command creation."""
        base_command = "ls"
        user_args = ["-la", "/home/test"]

        safe_command = self.validator.create_safe_command(base_command, user_args)
        expected = "ls '-la' '/home/test'"
        assert safe_command == expected

    def test_create_safe_command_with_sudo(self):
        """Test safe command creation with sudo."""
        base_command = "systemctl"
        user_args = ["restart", "nginx"]
        sudo_password = "testpass"

        safe_command = self.validator.create_safe_command(
            base_command, user_args, use_sudo=True, sudo_password=sudo_password
        )

        # After security fix: password should NOT appear in prepared command
        assert (
            "testpass" not in safe_command
        ), "Password should not appear in command string"
        assert "sudo systemctl restart nginx" == safe_command
        # Note: Actual secure password handling is done by SecureSudoHandler
        # during execution

    def test_create_safe_command_dangerous_base(self):
        """Test rejection of dangerous base commands."""
        with pytest.raises(CommandSecurityError):
            self.validator.create_safe_command("rm -rf /", [])


class TestConvenienceFunctions:
    """Test convenience validation functions."""

    def test_validate_command_safe_success(self):
        """Test successful command validation."""
        allowed_paths = ["/home/test"]
        validate_command_safe("ls -la", allowed_paths)  # Should not raise

    def test_validate_command_safe_failure(self):
        """Test failed command validation."""
        allowed_paths = ["/home/test"]
        with pytest.raises(CommandSecurityError):
            validate_command_safe("rm -rf /", allowed_paths)

    def test_validate_path_safe_success(self):
        """Test successful path validation."""
        allowed_paths = ["/home/test"]
        result_path = validate_path_safe("/home/test/file.txt", allowed_paths)
        assert isinstance(result_path, Path)

    def test_validate_path_safe_failure(self):
        """Test failed path validation."""
        allowed_paths = ["/home/test"]
        with pytest.raises(PathSecurityError):
            validate_path_safe("/etc/passwd", allowed_paths)


if __name__ == "__main__":
    pytest.main([__file__])
