"""Tests for MCP tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.vps_manager.tools.command import CommandTool
from src.vps_manager.tools.file_ops import FileOperationsTool
from src.vps_manager.tools.monitoring import SystemMonitoringTool
from src.vps_manager.tools.services import ServiceManagementTool


class TestCommandTool:
    """Test command execution tool."""

    @pytest.mark.asyncio
    async def test_exec_command_success(
        self, mock_connection_manager, mock_command_result
    ):
        """Test successful command execution."""
        tool = CommandTool(mock_connection_manager)

        # Mock the SSH connection execution
        mock_conn = MagicMock()
        mock_conn.connection.run = AsyncMock(return_value=mock_command_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.exec_command("test-server", "ls -la", "/home/user")

        assert result is not None
        assert "returncode" in result
        assert result["returncode"] == 0
        assert result["stdout"] == "command output"

        mock_connection_manager.get_connection.assert_called_once_with("test-server")
        mock_connection_manager.release_connection.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_exec_command_with_timeout(
        self, mock_connection_manager, mock_command_result
    ):
        """Test command execution with custom timeout."""
        tool = CommandTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_conn.connection.run = AsyncMock(return_value=mock_command_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        await tool.exec_command("test-server", "sleep 5", timeout=10)

        # Verify timeout was passed to the run command
        mock_conn.connection.run.assert_called_once()
        call_args = mock_conn.connection.run.call_args
        assert call_args[1].get("timeout") == 10

    @pytest.mark.asyncio
    async def test_exec_command_failure(
        self, mock_connection_manager, mock_failed_command_result
    ):
        """Test failed command execution."""
        tool = CommandTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_conn.connection.run = AsyncMock(return_value=mock_failed_command_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.exec_command("test-server", "invalid-command")

        assert result["returncode"] == 1
        assert result["stderr"] == "command failed"

    @pytest.mark.asyncio
    async def test_exec_command_no_connection(self, mock_connection_manager):
        """Test command execution when no connection available."""
        tool = CommandTool(mock_connection_manager)

        mock_connection_manager.get_connection.return_value = None

        with pytest.raises(Exception, match="Failed to get connection"):
            await tool.exec_command("test-server", "ls")

    @pytest.mark.asyncio
    async def test_exec_command_security_validation(self, mock_connection_manager):
        """Test command execution with security validation."""
        tool = CommandTool(mock_connection_manager)

        # Mock security validator
        with patch("src.vps_manager.security.SecurityValidator") as MockValidator:
            validator_instance = MockValidator.return_value
            validator_instance.validate_command.return_value = (
                False,
                "Dangerous command",
            )
            tool.security = validator_instance

            with pytest.raises(Exception, match="Dangerous command"):
                await tool.exec_command("test-server", "rm -rf /")


class TestFileOperationsTool:
    """Test file operations tool."""

    @pytest.mark.asyncio
    async def test_read_file_success(
        self, mock_connection_manager, sample_file_content
    ):
        """Test successful file reading."""
        tool = FileOperationsTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.readfile = AsyncMock(return_value=sample_file_content.encode())
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.read_file("test-server", "/test/file.txt")

        assert result["content"] == sample_file_content
        assert result["encoding"] == "utf-8"
        assert result["size"] == len(sample_file_content.encode())

        mock_connection_manager.get_connection.assert_called_once_with("test-server")
        mock_connection_manager.release_connection.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_read_binary_file(
        self, mock_connection_manager, sample_binary_content
    ):
        """Test reading binary file."""
        tool = FileOperationsTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.readfile = AsyncMock(return_value=sample_binary_content)
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.read_file("test-server", "/test/binary.dat")

        assert result["encoding"] == "binary"
        assert "content" in result

    @pytest.mark.asyncio
    async def test_write_file_success(
        self, mock_connection_manager, sample_file_content
    ):
        """Test successful file writing."""
        tool = FileOperationsTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.writefile = AsyncMock()
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.write_file(
            "test-server", "/test/output.txt", sample_file_content
        )

        assert result["success"] is True
        assert result["bytes_written"] == len(sample_file_content.encode())

        mock_sftp.writefile.assert_called_once_with(
            "/test/output.txt", sample_file_content.encode()
        )

    @pytest.mark.asyncio
    async def test_write_file_with_permissions(
        self, mock_connection_manager, sample_file_content
    ):
        """Test file writing with custom permissions."""
        tool = FileOperationsTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.writefile = AsyncMock()
        mock_sftp.chmod = AsyncMock()
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.write_file(
            "test-server",
            "/test/script.sh",
            sample_file_content,
            permissions=0o755,
        )

        assert result["success"] is True
        mock_sftp.chmod.assert_called_once_with("/test/script.sh", 0o755)

    @pytest.mark.asyncio
    async def test_list_directory_success(self, mock_connection_manager):
        """Test successful directory listing."""
        tool = FileOperationsTool(mock_connection_manager)

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "total 12\n"
            "-rw-r--r-- 1 user user 1024 Jan 1 12:00 file1.txt\n"
            "drwxr-xr-x 2 user user 4096 Jan 1 12:00 subdir"
        )
        mock_conn.connection.run = AsyncMock(return_value=mock_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.list_directory("test-server", "/test")

        assert result["success"] is True
        assert len(result["entries"]) == 2
        assert result["entries"][0]["name"] == "file1.txt"
        assert result["entries"][0]["type"] == "file"
        assert result["entries"][1]["name"] == "subdir"
        assert result["entries"][1]["type"] == "directory"

    @pytest.mark.asyncio
    async def test_security_validation_read(self, mock_connection_manager):
        """Test security validation for file read."""
        tool = FileOperationsTool(mock_connection_manager)

        with patch("src.vps_manager.security.SecurityValidator") as MockValidator:
            validator_instance = MockValidator.return_value
            validator_instance.validate_path.return_value = (
                False,
                "Path not allowed",
            )
            tool.security = validator_instance

            with pytest.raises(Exception, match="Path not allowed"):
                await tool.read_file("test-server", "/etc/shadow")

    @pytest.mark.asyncio
    async def test_security_validation_write(self, mock_connection_manager):
        """Test security validation for file write."""
        tool = FileOperationsTool(mock_connection_manager)

        with patch("src.vps_manager.security.SecurityValidator") as MockValidator:
            validator_instance = MockValidator.return_value
            validator_instance.validate_path.return_value = (
                False,
                "Path not allowed",
            )
            tool.security = validator_instance

            with pytest.raises(Exception, match="Path not allowed"):
                await tool.write_file(
                    "test-server",
                    "/root/.ssh/authorized_keys",
                    "malicious content",
                )


class TestMonitoringTool:
    """Test system monitoring tool."""

    @pytest.mark.asyncio
    async def test_get_system_info_success(
        self, mock_connection_manager, system_status_data
    ):
        """Test successful system info retrieval."""
        tool = SystemMonitoringTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock individual command results
        cpu_result = MagicMock()
        cpu_result.returncode = 0
        cpu_result.stdout = "25.5"

        mem_result = MagicMock()
        mem_result.returncode = 0
        mem_result.stdout = (
            "MemTotal:    8388608 kB\n"
            "MemAvailable: 4194304 kB\n"
            "MemFree:     2097152 kB"
        )

        disk_result = MagicMock()
        disk_result.returncode = 0
        disk_result.stdout = (
            "Filesystem     1K-blocks      Used Available Use% Mounted on\n"
            "/dev/sda1      104857600  52428800  52428800  50% /"
        )

        load_result = MagicMock()
        load_result.returncode = 0
        load_result.stdout = "0.50 0.30 0.20 1/200 12345"

        uptime_result = MagicMock()
        uptime_result.returncode = 0
        uptime_result.stdout = "86400.00 86400.00"

        # Set up the run method to return different results based on command
        def mock_run(command, **kwargs):
            if "cpu usage" in command:
                return cpu_result
            elif "cat /proc/meminfo" in command:
                return mem_result
            elif "df -k" in command:
                return disk_result
            elif "cat /proc/loadavg" in command:
                return load_result
            elif "cat /proc/uptime" in command:
                return uptime_result
            return MagicMock(returncode=1, stdout="")

        mock_conn.connection.run = AsyncMock(side_effect=mock_run)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.get_system_info("test-server")

        assert result is not None
        assert "cpu" in result
        assert "memory" in result
        assert "disk" in result
        assert "load_average" in result
        assert "uptime" in result

    @pytest.mark.asyncio
    async def test_get_system_info_partial_failure(self, mock_connection_manager):
        """Test system info retrieval with partial command failures."""
        tool = SystemMonitoringTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock some commands failing
        def mock_run(command, **kwargs):
            if "cpu usage" in command:
                _ = MagicMock()
                result.returncode = 0
                result.stdout = "25.5"
                return result
            else:
                # Simulate command failure
                _ = MagicMock()
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Command not found"
                return result

        mock_conn.connection.run = AsyncMock(side_effect=mock_run)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.get_system_info("test-server")

        # Should still return partial results
        assert result is not None
        assert "cpu" in result

    @pytest.mark.asyncio
    async def test_get_system_info_no_connection(self, mock_connection_manager):
        """Test system info when no connection available."""
        tool = SystemMonitoringTool(mock_connection_manager)

        mock_connection_manager.get_connection.return_value = None

        with pytest.raises(Exception, match="Failed to get connection"):
            await tool.get_system_info("test-server")


class TestServiceManagementTool:
    """Test service management tool."""

    @pytest.mark.asyncio
    async def test_list_services_systemd(self, mock_connection_manager):
        """Test listing services on systemd system."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock systemctl command
        systemctl_result = MagicMock()
        systemctl_result.returncode = 0
        systemctl_result.stdout = (
            "nginx.service loaded active running nginx web server\n"
            "ssh.service loaded active running OpenBSD Secure Shell server"
        )

        mock_conn.connection.run = AsyncMock(return_value=systemctl_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.list_services("test-server")

        assert result is not None
        assert len(result["services"]) == 2
        assert result["services"][0]["name"] == "nginx.service"
        assert result["services"][0]["status"] == "running"
        assert result["services"][1]["name"] == "ssh.service"
        assert result["services"][1]["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_service_status_systemd(self, mock_connection_manager):
        """Test getting service status on systemd system."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock systemctl status command
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = (
            "● nginx.service - nginx web server\n"
            "   Loaded: loaded (/lib/systemd/system/nginx.service; enabled; "
            "vendor preset: enabled)\n"
            "   Active: active (running) since Mon 2024-01-01 12:00:00 UTC; "
            "1h 30min ago"
        )

        mock_conn.connection.run = AsyncMock(return_value=status_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.get_service_status("test-server", "nginx")

        assert result is not None
        assert result["service_name"] == "nginx"
        assert result["status"] == "running"
        assert "enabled" in result["raw_output"]

    @pytest.mark.asyncio
    async def test_start_service_systemd(self, mock_connection_manager):
        """Test starting service on systemd system."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock successful start command
        start_result = MagicMock()
        start_result.returncode = 0
        start_result.stdout = ""

        mock_conn.connection.run = AsyncMock(return_value=start_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.start_service("test-server", "nginx")

        assert result["success"] is True
        assert result["action"] == "start"
        assert result["service_name"] == "nginx"

    @pytest.mark.asyncio
    async def test_start_service_failure(self, mock_connection_manager):
        """Test failed service start."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock failed start command
        start_result = MagicMock()
        start_result.returncode = 1
        start_result.stderr = "Job for nginx.service failed"

        mock_conn.connection.run = AsyncMock(return_value=start_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        result = await tool.start_service("test-server", "nginx")

        assert result["success"] is False
        assert "failed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_detect_init_system_systemd(self, mock_connection_manager):
        """Test detecting systemd init system."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock systemctl command exists
        which_result = MagicMock()
        which_result.returncode = 0
        which_result.stdout = "/bin/systemctl"

        mock_conn.connection.run = AsyncMock(return_value=which_result)
        mock_connection_manager.get_connection.return_value = mock_conn

        init_system = await tool._detect_init_system(mock_conn)

        assert init_system == "systemd"

    @pytest.mark.asyncio
    async def test_detect_init_system_sysv(self, mock_connection_manager):
        """Test detecting sysv init system."""
        tool = ServiceManagementTool(mock_connection_manager)

        mock_conn = MagicMock()

        # Mock systemctl not found, but service command exists
        def mock_run(command, **kwargs):
            if "which systemctl" in command:
                result = MagicMock()
                result.returncode = 1
                return result
            elif "which service" in command:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "/usr/sbin/service"
                return result
            return MagicMock(returncode=1)

        mock_conn.connection.run = AsyncMock(side_effect=mock_run)
        mock_connection_manager.get_connection.return_value = mock_conn

        init_system = await tool._detect_init_system(mock_conn)

        assert init_system == "sysv"

    @pytest.mark.asyncio
    async def test_security_validation_service_management(
        self, mock_connection_manager
    ):
        """Test security validation for service management."""
        tool = ServiceManagementTool(mock_connection_manager)

        # Test with potentially dangerous service name
        with pytest.raises(ValueError, match="Invalid service name"):
            await tool.start_service("test-server", "../../etc/passwd")
