"""Integration tests for MCP server functionality."""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch

from src.vps_manager.server import VPSManagerServer
from mcp.types import TextContent, Resource


class TestMCPServerIntegration:
    """Test MCP server integration."""

    @pytest.fixture
    async def server(self, sample_vps_config, mock_connection_manager):
        """Create VPS manager server for testing."""
        with patch('src.vps_manager.connection_pool.ConnectionManager', return_value=mock_connection_manager):
            server = VPSManagerServer(sample_vps_config)
            await server.initialize()
            yield server
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_list_resources(self, server):
        """Test listing available resources."""
        resources = await server.list_resources()
        
        assert len(resources) > 0
        
        # Check for server resources
        server_resources = [r for r in resources if r.name.startswith("server://")]
        assert len(server_resources) > 0
        assert server_resources[0].name == "server://test-server"
        assert server_resources[0].mimeType == "application/json"

    @pytest.mark.asyncio
    async def test_read_server_resource(self, server, mock_connection_manager):
        """Test reading server resource."""
        # Mock connection manager status
        mock_status = {
            "total_connections": 2,
            "healthy_connections": 1,
            "max_connections": 3,
            "server_name": "test-server"
        }
        mock_connection_manager.get_status_all.return_value = {"test-server": mock_status}
        
        resource_content = await server.read_resource("server://test-server")
        
        assert len(resource_content) == 1
        assert isinstance(resource_content[0], TextContent)
        
        # Parse the JSON content
        content_data = json.loads(resource_content[0].text)
        assert content_data["server_name"] == "test-server"
        assert content_data["status"] == mock_status

    @pytest.mark.asyncio
    async def test_read_nonexistent_resource(self, server):
        """Test reading non-existent resource."""
        with pytest.raises(Exception, match="Resource not found"):
            await server.read_resource("server://nonexistent")

    @pytest.mark.asyncio
    async def test_list_tools(self, server):
        """Test listing available tools."""
        tools = await server.list_tools()
        
        expected_tools = [
            "exec_command",
            "read_file",
            "write_file",
            "list_directory",
            "system_info",
            "service_management"
        ]
        
        tool_names = [tool.name for tool in tools]
        
        for expected_tool in expected_tools:
            assert expected_tool in tool_names

    @pytest.mark.asyncio
    async def test_exec_command_tool(self, server, mock_connection_manager, mock_command_result):
        """Test exec_command tool execution."""
        # Mock successful command execution
        mock_conn = MagicMock()
        mock_conn.connection.run = AsyncMock(return_value=mock_command_result)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("exec_command", {
            "server_name": "test-server",
            "command": "ls -la",
            "working_directory": "/home/user"
        })
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        
        # Parse result
        result_data = json.loads(result[0].text)
        assert result_data["returncode"] == 0
        assert result_data["stdout"] == "command output"

    @pytest.mark.asyncio
    async def test_exec_command_tool_missing_args(self, server):
        """Test exec_command tool with missing arguments."""
        with pytest.raises(Exception, match="Missing required argument"):
            await server.call_tool("exec_command", {
                "command": "ls -la"
                # Missing server_name
            })

    @pytest.mark.asyncio
    async def test_read_file_tool(self, server, mock_connection_manager, sample_file_content):
        """Test read_file tool execution."""
        # Mock successful file read
        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.readfile = AsyncMock(return_value=sample_file_content.encode())
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("read_file", {
            "server_name": "test-server",
            "file_path": "/test/file.txt"
        })
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        
        result_data = json.loads(result[0].text)
        assert result_data["content"] == sample_file_content
        assert result_data["encoding"] == "utf-8"

    @pytest.mark.asyncio
    async def test_write_file_tool(self, server, mock_connection_manager, sample_file_content):
        """Test write_file tool execution."""
        # Mock successful file write
        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.writefile = AsyncMock()
        mock_conn.connection.start_sftp_client = AsyncMock(return_value=mock_sftp)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("write_file", {
            "server_name": "test-server",
            "file_path": "/test/output.txt",
            "content": sample_file_content
        })
        
        assert len(result) == 1
        result_data = json.loads(result[0].text)
        assert result_data["success"] is True

    @pytest.mark.asyncio
    async def test_list_directory_tool(self, server, mock_connection_manager):
        """Test list_directory tool execution."""
        # Mock successful directory listing
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "total 8\n-rw-r--r-- 1 user user 1024 Jan 1 12:00 file.txt\ndrwxr-xr-x 2 user user 4096 Jan 1 12:00 subdir"
        mock_conn.connection.run = AsyncMock(return_value=mock_result)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("list_directory", {
            "server_name": "test-server",
            "directory_path": "/test"
        })
        
        assert len(result) == 1
        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert len(result_data["entries"]) == 2

    @pytest.mark.asyncio
    async def test_system_info_tool(self, server, mock_connection_manager):
        """Test system_info tool execution."""
        # Mock system info commands
        mock_conn = MagicMock()
        
        def mock_run(command, **kwargs):
            if "cpu usage" in command:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "25.5"
                return result
            elif "cat /proc/meminfo" in command:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "MemTotal:    8388608 kB\nMemAvailable: 4194304 kB"
                return result
            return MagicMock(returncode=1, stdout="")
        
        mock_conn.connection.run = AsyncMock(side_effect=mock_run)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("system_info", {
            "server_name": "test-server"
        })
        
        assert len(result) == 1
        result_data = json.loads(result[0].text)
        assert "cpu" in result_data or "memory" in result_data  # At least one should be present

    @pytest.mark.asyncio
    async def test_service_management_tool(self, server, mock_connection_manager):
        """Test service_management tool execution."""
        # Mock service status command
        mock_conn = MagicMock()
        
        def mock_run(command, **kwargs):
            if "which systemctl" in command:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "/bin/systemctl"
                return result
            elif "systemctl status nginx" in command:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "● nginx.service - nginx web server\n   Active: active (running)"
                return result
            return MagicMock(returncode=1, stdout="")
        
        mock_conn.connection.run = AsyncMock(side_effect=mock_run)
        mock_connection_manager.get_connection.return_value = mock_conn
        
        result = await server.call_tool("service_management", {
            "server_name": "test-server",
            "action": "status",
            "service_name": "nginx"
        })
        
        assert len(result) == 1
        result_data = json.loads(result[0].text)
        assert result_data["service_name"] == "nginx"

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self, server):
        """Test calling non-existent tool."""
        with pytest.raises(Exception, match="Tool not found"):
            await server.call_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_security_validation_integration(self, server, mock_connection_manager):
        """Test security validation integration across tools."""
        # Mock connection
        mock_conn = MagicMock()
        mock_connection_manager.get_connection.return_value = mock_conn
        
        # Test dangerous command blocked
        with patch('src.vps_manager.security.SecurityValidator') as MockValidator:
            validator_instance = MockValidator.return_value
            validator_instance.validate_command.return_value = False, "Dangerous command detected"
            
            with pytest.raises(Exception, match="Dangerous command detected"):
                await server.call_tool("exec_command", {
                    "server_name": "test-server",
                    "command": "rm -rf /"
                })

        # Test dangerous path blocked for file operations
        with patch('src.vps_manager.security.SecurityValidator') as MockValidator:
            validator_instance = MockValidator.return_value
            validator_instance.validate_path.return_value = False, "Path not allowed"
            
            with pytest.raises(Exception, match="Path not allowed"):
                await server.call_tool("read_file", {
                    "server_name": "test-server",
                    "file_path": "/etc/shadow"
                })

    @pytest.mark.asyncio
    async def test_connection_error_handling(self, server, mock_connection_manager):
        """Test connection error handling."""
        # Mock connection failure
        mock_connection_manager.get_connection.return_value = None
        
        with pytest.raises(Exception, match="Failed to get connection"):
            await server.call_tool("exec_command", {
                "server_name": "test-server",
                "command": "ls"
            })

    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self, server, mock_connection_manager):
        """Test concurrent tool execution."""
        # Mock successful responses
        mock_conn1 = MagicMock()
        mock_conn1.connection.run = AsyncMock(return_value=MagicMock(returncode=0, stdout="result1"))
        
        mock_conn2 = MagicMock()
        mock_conn2.connection.run = AsyncMock(return_value=MagicMock(returncode=0, stdout="result2"))
        
        # Return different connections for concurrent requests
        mock_connection_manager.get_connection.side_effect = [mock_conn1, mock_conn2]
        
        # Execute two commands concurrently
        task1 = server.call_tool("exec_command", {
            "server_name": "test-server",
            "command": "echo test1"
        })
        
        task2 = server.call_tool("exec_command", {
            "server_name": "test-server",
            "command": "echo test2"
        })
        
        results = await asyncio.gather(task1, task2)
        
        assert len(results) == 2
        assert all(len(result) == 1 for result in results)
        
        # Both should succeed
        result1_data = json.loads(results[0][0].text)
        result2_data = json.loads(results[1][0].text)
        
        assert result1_data["returncode"] == 0
        assert result2_data["returncode"] == 0

    @pytest.mark.asyncio
    async def test_server_initialization_and_cleanup(self, sample_vps_config):
        """Test server initialization and cleanup."""
        with patch('src.vps_manager.connection_pool.ConnectionManager') as MockManager:
            mock_manager = MockManager.return_value
            mock_manager.cleanup = AsyncMock()
            
            server = VPSManagerServer(sample_vps_config)
            
            # Test initialization
            await server.initialize()
            MockManager.assert_called_once_with(sample_vps_config)
            
            # Test cleanup
            await server.cleanup()
            mock_manager.cleanup.assert_called_once()