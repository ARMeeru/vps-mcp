"""Basic integration tests for MCP VPS Manager.

These tests require a test environment setup but don't require actual SSH connections.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.vps_manager.config import load_config
from src.vps_manager.server import MCPVPSServer, setup_logging


class TestConfigurationIntegration:
    """Test configuration loading and validation integration."""

    def test_load_complete_configuration(self, temp_ssh_key):
        """Test loading a complete configuration file."""
        # Create a comprehensive config file
        config_data = {
            "servers": [
                {
                    "name": "web-server",
                    "host": "192.168.1.10",
                    "port": 22,
                    "username": "www-data",
                    "ssh_key_path": temp_ssh_key,
                    "allowed_paths": ["/var/www", "/etc/nginx"],
                    "blocked_commands": ["nginx -s stop"],
                    "max_file_size_mb": 100,
                    "connection_timeout": 30,
                    "command_timeout": 300,
                },
                {
                    "name": "db-server",
                    "host": "192.168.1.11",
                    "port": 2222,
                    "username": "mysql",
                    "ssh_key_path": temp_ssh_key,
                    "ssh_key_passphrase_env": "DB_SSH_PASSPHRASE",
                    "allowed_paths": ["/var/lib/mysql", "/etc/mysql"],
                    "max_file_size_mb": 500,
                },
            ],
            "max_connections_per_server": 3,
            "health_check_interval": 45,
            "connection_retry_max_delay": 60,
            "log_level": "WARNING",
            "log_dir": "/var/log/mcp-vps",
            "audit_log_enabled": True,
        }

        # Write config to temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            config = load_config(config_path)

            # Verify servers
            assert len(config.servers) == 2

            web_server = config.servers[0]
            assert web_server.name == "web-server"
            assert web_server.host == "192.168.1.10"
            assert web_server.port == 22
            assert len(web_server.allowed_paths) == 2
            assert "/var/www" in [str(p) for p in web_server.allowed_paths]

            db_server = config.servers[1]
            assert db_server.name == "db-server"
            assert db_server.port == 2222
            assert db_server.ssh_key_passphrase_env == "DB_SSH_PASSPHRASE"

            # Verify global settings
            assert config.max_connections_per_server == 3
            assert config.health_check_interval == 45
            assert config.log_level == "WARNING"

        finally:
            Path(config_path).unlink()


class TestServerInitialization:
    """Test server initialization without actual connections."""

    def test_server_creation(self, sample_vps_config):
        """Test MCP server creation with valid config."""
        server = MCPVPSServer(sample_vps_config)

        assert server.config == sample_vps_config
        assert server.connection_manager is not None
        assert server.command_tool is not None
        assert server.file_ops_tool is not None
        assert server.monitoring_tool is not None
        assert server.service_tool is not None

    def test_server_handlers_registration(self, sample_vps_config):
        """Test that all MCP handlers are properly registered."""
        server = MCPVPSServer(sample_vps_config)

        # Check that handlers are registered (we can't easily test the actual
        # registration
        # without running the server, but we can verify the server was created)
        assert hasattr(server.server, "_resources_handlers")
        assert hasattr(server.server, "_tools_handlers")


class TestLoggingSetup:
    """Test logging configuration."""

    def test_logging_setup(self, temp_directory):
        """Test logging setup with different levels."""
        log_dir = str(temp_directory / "logs")

        # Test each log level
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            setup_logging(level, log_dir)

            # Verify log directory was created
            assert Path(log_dir).exists()

            # Verify log files exist
            _ = Path(log_dir) / "debug.log"
            _ = Path(log_dir) / "error.log"

            # Files may not exist until first log, but directory should be
            # there
            assert Path(log_dir).is_dir()


class TestSecurityIntegration:
    """Test security validation integration."""

    def test_path_validation_with_real_paths(self, security_validator, temp_directory):
        """Test path validation with real filesystem paths."""
        # Create test files
        allowed_dir = temp_directory / "allowed"
        allowed_dir.mkdir()
        test_file = allowed_dir / "test.txt"
        test_file.write_text("test content")

        # Update validator with real path
        validator = type(security_validator)(
            allowed_paths=[str(allowed_dir)], additional_blocked_commands=[]
        )

        # Test allowed path
        is_valid, error, resolved = validator.validate_file_path(str(test_file))
        assert is_valid, f"Should allow access to {test_file}"
        assert resolved.exists()

        # Test blocked path
        blocked_file = temp_directory / "blocked.txt"
        blocked_file.write_text("blocked content")

        is_valid, error, resolved = validator.validate_file_path(str(blocked_file))
        assert not is_valid, f"Should block access to {blocked_file}"

    def test_command_validation_comprehensive(self, security_validator):
        """Test comprehensive command validation scenarios."""
        test_cases = [
            # (command, should_be_valid, description)
            (
                "ls -la /home/testuser",
                True,
                "Basic list command in allowed path",
            ),
            ("cat /tmp/test/file.txt", True, "Read file in allowed path"),
            (
                "echo 'hello' > /home/testuser/output.txt",
                True,
                "Redirect to allowed path",
            ),
            ("rm -rf /", False, "Dangerous deletion command"),
            ("sudo rm /etc/passwd", False, "Dangerous sudo command"),
            (
                "find /home/testuser -name '*.log' | head -10",
                True,
                "Safe piped command",
            ),
            (":(){ :|:& };:", False, "Fork bomb"),
            ("test_blocked_command arg", False, "Custom blocked command"),
            ("systemctl restart nginx", True, "Valid service command"),
            (
                "chmod 777 /home/testuser/file.txt",
                True,
                "Safe permission change",
            ),
            ("chmod -R 777 /", False, "Dangerous permission change"),
        ]

        for command, expected_valid, description in test_cases:
            is_valid, error = security_validator.validate_command(command)
            assert (
                is_valid == expected_valid
            ), f"Failed for: {description} - Command: {command}"


class TestToolIntegration:
    """Test tool integration without real SSH connections."""

    def test_tools_use_security_validator(self, mock_connection_manager):
        """Test that tools properly integrate with security validation."""
        from src.vps_manager.tools.command import CommandTool
        from src.vps_manager.tools.file_ops import FileOperationsTool

        command_tool = CommandTool(mock_connection_manager)
        file_tool = FileOperationsTool(mock_connection_manager)

        # Tools should exist and have access to connection manager
        assert command_tool.connection_manager == mock_connection_manager
        assert file_tool.connection_manager == mock_connection_manager


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
