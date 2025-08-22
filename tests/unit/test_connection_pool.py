"""Tests for the SSH connection pool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asyncssh import PermissionDenied

from src.vps_manager.connection_pool import (
    ConnectionManager,
    ConnectionPool,
    ConnectionState,
    SSHConnection,
)


class TestSSHConnection:
    """Test SSH connection wrapper."""

    def test_init(self, mock_ssh_connection):
        """Test SSH connection initialization."""
        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name="test-server",
            connection_id="conn-1",
        )

        assert conn.connection == mock_ssh_connection
        assert conn.server_name == "test-server"
        assert conn.connection_id == "conn-1"
        assert conn.state == ConnectionState.CONNECTING
        assert conn.last_used is not None

    def test_is_healthy_ready_connection(self, mock_ssh_connection):
        """Test healthy connection check for ready connection."""
        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name="test-server",
            connection_id="conn-1",
        )
        conn.state = ConnectionState.READY

        # Mock connection as not closing
        with patch("builtins.getattr", return_value=False):
            assert conn.is_healthy() is True

    def test_is_healthy_closing_connection(self, mock_ssh_connection):
        """Test unhealthy connection check for closing connection."""
        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name="test-server",
            connection_id="conn-1",
        )
        conn.state = ConnectionState.READY

        # Mock connection as closing
        with patch("builtins.getattr", return_value=True):
            assert conn.is_healthy() is False

    def test_is_healthy_no_connection(self):
        """Test unhealthy connection check with no connection."""
        conn = SSHConnection(
            connection=None, server_name="test-server", connection_id="conn-1"
        )

        assert conn.is_healthy() is False

    @pytest.mark.asyncio
    async def test_close(self, mock_ssh_connection):
        """Test connection close."""
        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name="test-server",
            connection_id="conn-1",
        )

        await conn.close()

        mock_ssh_connection.close.assert_called_once()
        mock_ssh_connection.wait_closed.assert_called_once()
        assert conn.state == ConnectionState.CLOSED


class TestConnectionPool:
    """Test connection pool."""

    @pytest.mark.asyncio
    async def test_init(self, sample_server_config):
        """Test connection pool initialization."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        assert pool.server_config == sample_server_config
        assert pool.max_connections == 3
        assert pool.connection_timeout == sample_server_config.connection_timeout
        assert len(pool.connections) == 0

    @pytest.mark.asyncio
    async def test_get_connection_creates_new(self, sample_server_config):
        """Test getting connection creates new connection."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        mock_connection = MagicMock()

        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_connection

            conn = await pool.get_connection()

            assert conn is not None
            assert conn.server_name == sample_server_config.name
            assert conn.state == ConnectionState.READY
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_reuses_healthy(
        self, sample_server_config, mock_ssh_connection
    ):
        """Test getting connection reuses healthy connection."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        # Create a healthy connection
        existing_conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name=sample_server_config.name,
            connection_id="existing",
        )
        existing_conn.state = ConnectionState.READY
        pool.connections.append(existing_conn)

        with patch.object(existing_conn, "is_healthy", return_value=True):
            conn = await pool.get_connection()

            assert conn == existing_conn

    @pytest.mark.asyncio
    async def test_get_connection_removes_unhealthy(
        self, sample_server_config, mock_ssh_connection
    ):
        """Test getting connection removes unhealthy connections."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        # Create an unhealthy connection
        unhealthy_conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name=sample_server_config.name,
            connection_id="unhealthy",
        )
        unhealthy_conn.state = ConnectionState.READY
        pool.connections.append(unhealthy_conn)

        mock_new_connection = MagicMock()

        with (
            patch.object(unhealthy_conn, "is_healthy", return_value=False),
            patch.object(unhealthy_conn, "close", new_callable=AsyncMock),
            patch(
                "asyncssh.connect",
                new_callable=AsyncMock,
                return_value=mock_new_connection,
            ),
        ):

            conn = await pool.get_connection()

            assert conn is not None
            assert conn != unhealthy_conn
            assert unhealthy_conn not in pool.connections
            unhealthy_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_handles_connect_failure(self, sample_server_config):
        """Test getting connection handles SSH connection failure."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = PermissionDenied("Auth failed")

            conn = await pool.get_connection()

            assert conn is None

    @pytest.mark.asyncio
    async def test_release_connection(self, sample_server_config, mock_ssh_connection):
        """Test releasing connection back to pool."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name=sample_server_config.name,
            connection_id="test",
        )
        conn.state = ConnectionState.READY

        await pool.release_connection(conn)

        assert conn in pool.connections
        assert conn.state == ConnectionState.READY

    @pytest.mark.asyncio
    async def test_release_connection_closes_excess(
        self, sample_server_config, mock_ssh_connection
    ):
        """Test releasing connection closes excess connections."""
        pool = ConnectionPool(sample_server_config, max_connections=1)

        # Fill the pool
        existing_conn = SSHConnection(
            connection=MagicMock(),
            server_name=sample_server_config.name,
            connection_id="existing",
        )
        pool.connections.append(existing_conn)

        # Try to release another connection
        conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name=sample_server_config.name,
            connection_id="excess",
        )
        conn.state = ConnectionState.READY

        with patch.object(conn, "close", new_callable=AsyncMock) as mock_close:
            await pool.release_connection(conn)

            mock_close.assert_called_once()
            assert conn not in pool.connections

    @pytest.mark.asyncio
    async def test_cleanup_all_connections(
        self, sample_server_config, mock_ssh_connection
    ):
        """Test cleanup closes all connections."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        # Add some connections
        conn1 = SSHConnection(
            connection=MagicMock(), server_name="test", connection_id="1"
        )
        conn2 = SSHConnection(
            connection=MagicMock(), server_name="test", connection_id="2"
        )
        pool.connections.extend([conn1, conn2])

        with (
            patch.object(conn1, "close", new_callable=AsyncMock) as mock_close1,
            patch.object(conn2, "close", new_callable=AsyncMock) as mock_close2,
        ):

            await pool.cleanup()

            mock_close1.assert_called_once()
            mock_close2.assert_called_once()
            assert len(pool.connections) == 0

    def test_get_status(self, sample_server_config, mock_ssh_connection):
        """Test getting pool status."""
        pool = ConnectionPool(sample_server_config, max_connections=3)

        # Add a healthy connection
        healthy_conn = SSHConnection(
            connection=mock_ssh_connection,
            server_name=sample_server_config.name,
            connection_id="healthy",
        )
        healthy_conn.state = ConnectionState.READY

        # Add an unhealthy connection
        unhealthy_conn = SSHConnection(
            connection=None,
            server_name=sample_server_config.name,
            connection_id="unhealthy",
        )
        unhealthy_conn.state = ConnectionState.ERROR

        pool.connections.extend([healthy_conn, unhealthy_conn])

        with (
            patch.object(healthy_conn, "is_healthy", return_value=True),
            patch.object(unhealthy_conn, "is_healthy", return_value=False),
        ):

            status = pool.get_status()

            assert status["total_connections"] == 2
            assert status["healthy_connections"] == 1
            assert status["max_connections"] == 3
            assert status["server_name"] == sample_server_config.name


class TestConnectionManager:
    """Test connection manager."""

    @pytest.mark.asyncio
    async def test_init(self, sample_vps_config):
        """Test connection manager initialization."""
        manager = ConnectionManager(sample_vps_config)

        assert len(manager.pools) == 1
        assert "test-server" in manager.pools
        assert (
            manager.pools["test-server"].server_config == sample_vps_config.servers[0]
        )

    @pytest.mark.asyncio
    async def test_get_connection_success(self, sample_vps_config, mock_ssh_connection):
        """Test successful connection retrieval."""
        manager = ConnectionManager(sample_vps_config)

        with patch.object(
            manager.pools["test-server"],
            "get_connection",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_conn = SSHConnection(mock_ssh_connection, "test-server", "conn-1")
            mock_get.return_value = mock_conn

            conn = await manager.get_connection("test-server")

            assert conn == mock_conn
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_invalid_server(self, sample_vps_config):
        """Test connection retrieval with invalid server name."""
        manager = ConnectionManager(sample_vps_config)

        with pytest.raises(ValueError, match="Server not found"):
            await manager.get_connection("nonexistent-server")

    @pytest.mark.asyncio
    async def test_release_connection(self, sample_vps_config, mock_ssh_connection):
        """Test connection release."""
        manager = ConnectionManager(sample_vps_config)

        conn = SSHConnection(mock_ssh_connection, "test-server", "conn-1")

        with patch.object(
            manager.pools["test-server"],
            "release_connection",
            new_callable=AsyncMock,
        ) as mock_release:
            await manager.release_connection(conn)

            mock_release.assert_called_once_with(conn)

    def test_list_servers(self, sample_vps_config):
        """Test listing servers."""
        manager = ConnectionManager(sample_vps_config)

        servers = manager.list_servers()

        assert servers == ["test-server"]

    def test_get_status_all(self, sample_vps_config):
        """Test getting status for all pools."""
        manager = ConnectionManager(sample_vps_config)

        mock_status = {"total_connections": 1, "healthy_connections": 1}

        with patch.object(
            manager.pools["test-server"],
            "get_status",
            return_value=mock_status,
        ):
            status = manager.get_status_all()

            assert status == {"test-server": mock_status}

    @pytest.mark.asyncio
    async def test_cleanup_all_pools(self, sample_vps_config):
        """Test cleanup of all connection pools."""
        manager = ConnectionManager(sample_vps_config)

        with patch.object(
            manager.pools["test-server"], "cleanup", new_callable=AsyncMock
        ) as mock_cleanup:
            await manager.cleanup()

            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_removes_unhealthy_connections(self, sample_vps_config):
        """Test periodic health check removes unhealthy connections."""
        manager = ConnectionManager(sample_vps_config)

        with patch.object(
            manager.pools["test-server"],
            "cleanup_unhealthy_connections",
            new_callable=AsyncMock,
        ) as mock_cleanup:
            await manager.health_check()

            mock_cleanup.assert_called_once()
