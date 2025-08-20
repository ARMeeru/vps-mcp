"""SSH Connection Pool Manager with health checks and automatic reconnection."""

import asyncio
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

import asyncssh
from asyncssh import SSHClientConnection, SSHClientConnectionOptions
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import ServerConfig

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """SSH connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class SSHConnection:
    """Wrapper for SSH connection with metadata."""
    
    connection: Optional[SSHClientConnection] = None
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_used: float = field(default_factory=time.time)
    error_count: int = 0
    server_name: str = ""
    connection_id: str = ""
    
    def mark_used(self) -> None:
        """Update last used timestamp."""
        self.last_used = time.time()
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy and ready."""
        return (self.connection is not None and 
                not getattr(self.connection, '_closing', False) and
                self.state == ConnectionState.READY)


class ConnectionPool:
    """Manages SSH connections to VPS servers with health checks and auto-reconnection."""
    
    def __init__(self, server_config: ServerConfig, pool_size: int = 3):
        """Initialize connection pool for a server.
        
        Args:
            server_config: Server configuration
            pool_size: Number of connections to maintain
        """
        self.server_config = server_config
        self.pool_size = pool_size
        self.connections: List[SSHConnection] = []
        self.sudo_password: Optional[str] = None
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # SSH connection options
        self.ssh_options = SSHClientConnectionOptions(
            username=server_config.username,
            client_keys=[server_config.ssh_key_path],
            known_hosts=None,  # Use default known_hosts
            connect_timeout=server_config.connection_timeout,
            keepalive_interval=30,
            keepalive_count_max=3
        )
        
        logger.info(f"Initialized connection pool for {server_config.name} with {pool_size} connections")
    
    async def initialize(self, sudo_password: Optional[str] = None) -> None:
        """Initialize the connection pool.
        
        Args:
            sudo_password: Sudo password for the server (stored in memory only)
        """
        self.sudo_password = sudo_password
        
        # Create initial connections
        for i in range(self.pool_size):
            conn = SSHConnection(
                server_name=self.server_config.name,
                connection_id=f"{self.server_config.name}-{i}"
            )
            self.connections.append(conn)
        
        # Start health check task
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Attempt initial connections
        await self._connect_all()
        
        logger.info(f"Connection pool initialized for {self.server_config.name}")
    
    async def get_connection(self, priority: str = "NORMAL") -> Optional[SSHConnection]:
        """Get an available connection from the pool.
        
        Args:
            priority: Connection priority (NORMAL, HIGH) - HIGH gets first available
            
        Returns:
            SSH connection if available, None if all busy or failed
        """
        async with self._lock:
            # Find ready connections
            ready_connections = [
                conn for conn in self.connections 
                if conn.is_healthy() and conn.state == ConnectionState.READY
            ]
            
            if not ready_connections:
                logger.warning(f"No ready connections available for {self.server_config.name}")
                return None
            
            # Sort by last used time (LRU)
            ready_connections.sort(key=lambda c: c.last_used)
            
            # Get the least recently used connection
            conn = ready_connections[0]
            conn.state = ConnectionState.BUSY
            conn.mark_used()
            
            logger.debug(f"Allocated connection {conn.connection_id}")
            return conn
    
    async def release_connection(self, conn: SSHConnection) -> None:
        """Release a connection back to the pool.
        
        Args:
            conn: Connection to release
        """
        async with self._lock:
            if conn in self.connections:
                if conn.is_healthy():
                    conn.state = ConnectionState.READY
                    logger.debug(f"Released connection {conn.connection_id}")
                else:
                    conn.state = ConnectionState.ERROR
                    logger.warning(f"Released unhealthy connection {conn.connection_id}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((ConnectionError, OSError, asyncssh.Error))
    )
    async def _connect_single(self, conn: SSHConnection) -> bool:
        """Connect a single SSH connection with retry logic.
        
        Args:
            conn: Connection to establish
            
        Returns:
            True if successful, False otherwise
        """
        if self._shutdown:
            return False
            
        try:
            conn.state = ConnectionState.CONNECTING
            logger.debug(f"Connecting {conn.connection_id} to {self.server_config.host}:{self.server_config.port}")
            
            # Establish SSH connection
            conn.connection = await asyncssh.connect(
                self.server_config.host,
                port=self.server_config.port,
                options=self.ssh_options
            )
            
            # Test connection with a simple command
            result = await conn.connection.run("echo 'connection-test'", check=True)
            if result.stdout.strip() != "connection-test":
                raise ConnectionError("Connection test failed")
            
            conn.state = ConnectionState.READY
            conn.error_count = 0
            conn.mark_used()
            
            logger.info(f"Successfully connected {conn.connection_id}")
            return True
            
        except Exception as e:
            conn.state = ConnectionState.ERROR
            conn.error_count += 1
            logger.error(f"Failed to connect {conn.connection_id}: {e}")
            
            # Clean up failed connection
            if conn.connection and not getattr(conn.connection, '_closing', False):
                conn.connection.close()
            conn.connection = None
            
            raise
    
    async def _connect_all(self) -> None:
        """Attempt to connect all disconnected connections."""
        tasks = []
        
        for conn in self.connections:
            if conn.state in [ConnectionState.DISCONNECTED, ConnectionState.ERROR]:
                task = asyncio.create_task(self._connect_single(conn))
                tasks.append(task)
        
        if tasks:
            # Wait for all connection attempts, but don't fail if some fail
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful = sum(1 for r in results if r is True)
            logger.info(f"Connected {successful}/{len(tasks)} connections for {self.server_config.name}")
    
    async def _health_check_loop(self) -> None:
        """Continuous health check loop."""
        while not self._shutdown:
            try:
                await asyncio.sleep(30)  # Health check every 30 seconds
                await self.health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error for {self.server_config.name}: {e}")
    
    async def health_check(self) -> Dict[str, int]:
        """Perform health check on all connections.
        
        Returns:
            Dictionary with connection state counts
        """
        async with self._lock:
            state_counts = {state.value: 0 for state in ConnectionState}
            
            for conn in self.connections:
                # Skip connections that are currently busy
                if conn.state == ConnectionState.BUSY:
                    state_counts[conn.state.value] += 1
                    continue
                
                # Check if connection is still alive
                if conn.connection and not getattr(conn.connection, '_closing', False):
                    try:
                        # Quick ping test
                        result = await asyncio.wait_for(
                            conn.connection.run("echo ping", check=True),
                            timeout=5.0
                        )
                        if result.stdout.strip() == "ping":
                            conn.state = ConnectionState.READY
                            conn.error_count = 0
                        else:
                            raise ConnectionError("Ping test failed")
                    except Exception as e:
                        logger.warning(f"Health check failed for {conn.connection_id}: {e}")
                        conn.state = ConnectionState.ERROR
                        conn.error_count += 1
                        
                        # Close bad connection
                        if conn.connection and not getattr(conn.connection, '_closing', False):
                            conn.connection.close()
                        conn.connection = None
                else:
                    # Connection is closed
                    conn.state = ConnectionState.DISCONNECTED
                    conn.connection = None
                
                state_counts[conn.state.value] += 1
            
            # Try to reconnect failed/disconnected connections
            await self._connect_all()
            
            logger.debug(f"Health check for {self.server_config.name}: {state_counts}")
            return state_counts
    
    async def shutdown(self) -> None:
        """Shutdown the connection pool and close all connections."""
        self._shutdown = True
        
        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections
        async with self._lock:
            for conn in self.connections:
                if conn.connection and not getattr(conn.connection, '_closing', False):
                    conn.connection.close()
                    await conn.connection.wait_closed()
                conn.state = ConnectionState.DISCONNECTED
                conn.connection = None
        
        logger.info(f"Connection pool shutdown for {self.server_config.name}")
    
    def get_status(self) -> Dict[str, any]:
        """Get current pool status.
        
        Returns:
            Status dictionary with connection information
        """
        state_counts = {state.value: 0 for state in ConnectionState}
        
        for conn in self.connections:
            state_counts[conn.state.value] += 1
        
        return {
            "server_name": self.server_config.name,
            "pool_size": self.pool_size,
            "connections": state_counts,
            "has_sudo_password": self.sudo_password is not None
        }


class ConnectionManager:
    """Manages connection pools for multiple servers."""
    
    def __init__(self):
        """Initialize the connection manager."""
        self.pools: Dict[str, ConnectionPool] = {}
        self.sudo_passwords: Dict[str, str] = {}
        
    async def add_server(self, server_config: ServerConfig, pool_size: int = 3) -> None:
        """Add a server to the connection manager.
        
        Args:
            server_config: Server configuration
            pool_size: Number of connections per pool
        """
        if server_config.name in self.pools:
            logger.warning(f"Server {server_config.name} already exists, replacing")
            await self.remove_server(server_config.name)
        
        pool = ConnectionPool(server_config, pool_size)
        sudo_password = self.sudo_passwords.get(server_config.name)
        
        await pool.initialize(sudo_password)
        self.pools[server_config.name] = pool
        
        logger.info(f"Added server {server_config.name} to connection manager")
    
    async def remove_server(self, server_name: str) -> None:
        """Remove a server from the connection manager.
        
        Args:
            server_name: Name of server to remove
        """
        if server_name in self.pools:
            await self.pools[server_name].shutdown()
            del self.pools[server_name]
            
            if server_name in self.sudo_passwords:
                del self.sudo_passwords[server_name]
            
            logger.info(f"Removed server {server_name} from connection manager")
    
    async def get_connection(self, server_name: str, priority: str = "NORMAL") -> Optional[SSHConnection]:
        """Get a connection for the specified server.
        
        Args:
            server_name: Name of the target server
            priority: Connection priority
            
        Returns:
            SSH connection if available
        """
        if server_name not in self.pools:
            raise ValueError(f"Server {server_name} not found")
        
        return await self.pools[server_name].get_connection(priority)
    
    async def release_connection(self, server_name: str, conn: SSHConnection) -> None:
        """Release a connection back to its pool.
        
        Args:
            server_name: Name of the server
            conn: Connection to release
        """
        if server_name in self.pools:
            await self.pools[server_name].release_connection(conn)
    
    def set_sudo_password(self, server_name: str, password: str) -> None:
        """Set sudo password for a server.
        
        Args:
            server_name: Server name
            password: Sudo password (stored in memory only)
        """
        self.sudo_passwords[server_name] = password
        
        # Update existing pool if present
        if server_name in self.pools:
            self.pools[server_name].sudo_password = password
        
        logger.info(f"Updated sudo password for {server_name}")
    
    async def health_check_all(self) -> Dict[str, Dict[str, int]]:
        """Perform health check on all server pools.
        
        Returns:
            Dictionary mapping server names to their health status
        """
        results = {}
        
        for server_name, pool in self.pools.items():
            try:
                results[server_name] = await pool.health_check()
            except Exception as e:
                logger.error(f"Health check failed for {server_name}: {e}")
                results[server_name] = {"error": str(e)}
        
        return results
    
    async def shutdown_all(self) -> None:
        """Shutdown all connection pools."""
        for server_name in list(self.pools.keys()):
            await self.remove_server(server_name)
        
        # Clear sudo passwords from memory
        self.sudo_passwords.clear()
        
        logger.info("All connection pools shutdown")
    
    def get_status_all(self) -> Dict[str, Dict[str, any]]:
        """Get status of all connection pools.
        
        Returns:
            Dictionary mapping server names to their status
        """
        return {
            server_name: pool.get_status()
            for server_name, pool in self.pools.items()
        }
    
    def list_servers(self) -> List[str]:
        """Get list of configured server names.
        
        Returns:
            List of server names
        """
        return list(self.pools.keys())