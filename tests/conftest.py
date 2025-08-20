"""Pytest configuration and shared fixtures."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import asyncio

from src.vps_manager.config import ServerConfig, VPSManagerConfig
from src.vps_manager.connection_pool import ConnectionManager, SSHConnection
from src.vps_manager.security import SecurityValidator


@pytest.fixture
def temp_ssh_key():
    """Create a temporary SSH key file for testing."""
    with tempfile.NamedTemporaryFile(delete=False) as key_file:
        key_file.write(b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake key content for testing\n-----END OPENSSH PRIVATE KEY-----")
        key_path = key_file.name
    
    yield key_path
    
    # Cleanup
    try:
        os.unlink(key_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def sample_server_config(temp_ssh_key):
    """Create a sample server configuration for testing."""
    return ServerConfig(
        name="test-server",
        host="127.0.0.1",
        port=2222,
        username="testuser",
        ssh_key_path=temp_ssh_key,
        allowed_paths=["/home/testuser", "/tmp/test"],
        blocked_commands=["test_blocked"],
        max_file_size_mb=10,
        connection_timeout=15,
        command_timeout=60
    )


@pytest.fixture
def sample_vps_config(sample_server_config):
    """Create a sample VPS manager configuration."""
    return VPSManagerConfig(
        servers=[sample_server_config],
        max_connections_per_server=2,
        health_check_interval=30,
        connection_retry_max_delay=10,
        log_level="DEBUG",
        log_dir="/tmp/test-logs",
        audit_log_enabled=True
    )


@pytest.fixture
def mock_ssh_connection():
    """Create a mock SSH connection for testing."""
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock()
    mock_conn.is_closing.return_value = False
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()
    
    # Mock SFTP client
    mock_sftp = MagicMock()
    mock_sftp.stat = AsyncMock()
    mock_sftp.readfile = AsyncMock()
    mock_sftp.writefile = AsyncMock()
    mock_sftp.put = AsyncMock()
    mock_sftp.get = AsyncMock()
    mock_sftp.close = MagicMock()
    mock_conn.start_sftp_client = AsyncMock(return_value=mock_sftp)
    
    return mock_conn


@pytest.fixture
def mock_ssh_connection_wrapper(mock_ssh_connection):
    """Create a mock SSH connection wrapper."""
    wrapper = SSHConnection(
        connection=mock_ssh_connection,
        server_name="test-server",
        connection_id="test-conn-1"
    )
    wrapper.state = wrapper.state.READY
    return wrapper


@pytest.fixture
def mock_connection_manager(sample_server_config, mock_ssh_connection_wrapper):
    """Create a mock connection manager."""
    manager = MagicMock(spec=ConnectionManager)
    manager.pools = {"test-server": MagicMock()}
    manager.pools["test-server"].server_config = sample_server_config
    manager.pools["test-server"].sudo_password = None
    
    manager.get_connection = AsyncMock(return_value=mock_ssh_connection_wrapper)
    manager.release_connection = AsyncMock()
    manager.list_servers = MagicMock(return_value=["test-server"])
    manager.get_status_all = MagicMock(return_value={"test-server": {"status": "healthy"}})
    
    return manager


@pytest.fixture
def security_validator():
    """Create a security validator for testing."""
    allowed_paths = ["/home/testuser", "/tmp/test", "/var/www"]
    additional_blocked = ["test_blocked_command"]
    return SecurityValidator(allowed_paths, additional_blocked)


@pytest.fixture
def temp_directory():
    """Create a temporary directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Mock command execution results
@pytest.fixture
def mock_command_result():
    """Create a mock command execution result."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "command output"
    result.stderr = ""
    return result


@pytest.fixture
def mock_failed_command_result():
    """Create a mock failed command execution result."""
    result = MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = "command failed"
    return result


# Test data fixtures
@pytest.fixture
def sample_file_content():
    """Sample file content for testing."""
    return "Hello, World!\nThis is a test file.\nLine 3 with special chars: àáâã"


@pytest.fixture
def sample_binary_content():
    """Sample binary content for testing."""
    return b"\x00\x01\x02\x03\xFF\xFE\xFD\xFC"


@pytest.fixture
def system_status_data():
    """Sample system status data."""
    return {
        "cpu": {"usage_percent": 25.5, "core_count": 4},
        "memory": {
            "total_bytes": 8589934592,
            "used_bytes": 4294967296,
            "free_bytes": 4294967296,
            "usage_percent": 50.0
        },
        "disk": {
            "total_bytes": 107374182400,
            "used_bytes": 53687091200,
            "available_bytes": 53687091200,
            "usage_percent": 50.0,
            "filesystems": [
                {
                    "filesystem": "/dev/sda1",
                    "mount_point": "/",
                    "total_bytes": 107374182400,
                    "used_bytes": 53687091200,
                    "available_bytes": 53687091200,
                    "usage_percent": 50.0
                }
            ]
        },
        "load_average": {"1min": 0.5, "5min": 0.3, "15min": 0.2},
        "uptime": {"uptime_seconds": 86400, "uptime_formatted": "1d 0h 0m"}
    }


# Async test helpers
def async_test(coro):
    """Helper to run async tests in sync context."""
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()
    return wrapper