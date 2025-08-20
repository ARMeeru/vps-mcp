"""Service management tool for MCP VPS Manager."""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import re

from ..connection_pool import ConnectionManager, SSHConnection
from ..security import SecurityValidator, CommandSecurityError
from ..config import ServerConfig
from ..utils.distro import DistroDetector, InitSystem, DistroFamily, ServiceCommandMapper

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Service management errors."""
    pass


class ServiceManagementTool:
    """Tool for managing system services on VPS servers."""
    
    def __init__(self, connection_manager: ConnectionManager):
        """Initialize service management tool.
        
        Args:
            connection_manager: SSH connection manager
        """
        self.connection_manager = connection_manager
        self._server_info_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes cache for server info
    
    async def service_control(
        self,
        service_name: str,
        action: str,
        server: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """Control a system service (start, stop, restart, etc.).
        
        Args:
            service_name: Name of the service
            action: Action to perform (start, stop, restart, status, enable, disable)
            server: Target server name
            force: Force action even if risky
            
        Returns:
            Service control result
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        try:
            # Validate action
            valid_actions = ["start", "stop", "restart", "reload", "status", "enable", "disable", 
                           "is-enabled", "is-active"]
            if action not in valid_actions:
                raise ServiceError(f"Invalid action: {action}. Valid actions: {valid_actions}")
            
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise ServiceError("No servers configured")
                server = servers[0]
            
            # Get server configuration
            if server not in self.connection_manager.pools:
                raise ServiceError(f"Server {server} not found")
            
            server_config = self.connection_manager.pools[server].server_config
            
            # Security validation
            validator = SecurityValidator(server_config.allowed_paths)
            
            # Check if service is in blocked list
            service_lower = service_name.lower()
            blocked_services = ["ssh", "sshd", "networking", "network", "systemd"]
            
            if not force and service_lower in blocked_services:
                raise ServiceError(f"Service '{service_name}' is protected. Use force=True to override.")
            
            # Get server system information
            server_info = await self._get_server_info(server)
            init_system = server_info["init_system"]
            distro_family = server_info["distro_family"]
            
            # Normalize service name for the init system
            normalized_service = ServiceCommandMapper.normalize_service_name(service_name, init_system)
            
            # Get the appropriate command
            command = ServiceCommandMapper.get_command(init_system, action, normalized_service, distro_family)
            if not command:
                raise ServiceError(f"Action '{action}' not supported for {init_system.value}")
            
            # Add sudo if needed
            if action in ["start", "stop", "restart", "reload", "enable", "disable"]:
                command = f"sudo {command}"
            
            # Validate command security
            is_valid, error = validator.validate_command(command)
            if not is_valid:
                raise CommandSecurityError(error)
            
            # Execute the command
            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise ServiceError(f"No available connections for server {server}")
            
            try:
                # Set appropriate timeout for different actions
                timeout = 60 if action in ["start", "stop", "restart"] else 30
                
                result = await asyncio.wait_for(
                    conn.connection.run(command, check=False),
                    timeout=timeout
                )
                
                # Parse result based on action and init system
                parsed_result = self._parse_service_result(result, action, init_system, normalized_service)
                
                execution_time = int((time.time() - start_time) * 1000)
                
                logger.info(f"Service {action} executed on {server}: {service_name}")
                
                return {
                    "success": True,
                    "data": {
                        "service": service_name,
                        "normalized_service": normalized_service,
                        "action": action,
                        "init_system": init_system.value,
                        "command_executed": command,
                        "exit_code": result.returncode,
                        "result": parsed_result
                    },
                    "metadata": {
                        "execution_time_ms": execution_time,
                        "server": server,
                        "timestamp": timestamp,
                        "user": server_config.username
                    },
                    "error": None if result.returncode == 0 or action == "status" else {
                        "code": "SERVICE_COMMAND_FAILED",
                        "message": f"Service {action} failed with exit code {result.returncode}",
                        "details": {"stderr": result.stderr, "stdout": result.stdout}
                    }
                }
                
            finally:
                await self.connection_manager.release_connection(server, conn)
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"Service control failed: {e}")
            
            return {
                "success": False,
                "data": None,
                "metadata": {
                    "execution_time_ms": execution_time,
                    "server": server or "unknown",
                    "timestamp": timestamp,
                    "user": server_config.username if 'server_config' in locals() else "unknown"
                },
                "error": {
                    "code": type(e).__name__,
                    "message": str(e),
                    "details": {"service": service_name, "action": action}
                }
            }
    
    async def list_services(
        self,
        server: Optional[str] = None,
        running_only: bool = False,
        pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """List system services.
        
        Args:
            server: Target server name
            running_only: Show only running services
            pattern: Filter services by name pattern (regex)
            
        Returns:
            List of services
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise ServiceError("No servers configured")
                server = servers[0]
            
            # Get server configuration
            if server not in self.connection_manager.pools:
                raise ServiceError(f"Server {server} not found")
            
            server_config = self.connection_manager.pools[server].server_config
            
            # Get server system information
            server_info = await self._get_server_info(server)
            init_system = server_info["init_system"]
            
            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise ServiceError(f"No available connections for server {server}")
            
            try:
                services = await self._list_services_by_init_system(conn, init_system, running_only)
                
                # Apply pattern filtering if specified
                if pattern:
                    try:
                        regex = re.compile(pattern, re.IGNORECASE)
                        services = [svc for svc in services if regex.search(svc["name"])]
                    except re.error as e:
                        raise ServiceError(f"Invalid regex pattern: {e}")
                
                execution_time = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "data": {
                        "services": services,
                        "total_count": len(services),
                        "init_system": init_system.value,
                        "running_only": running_only,
                        "pattern": pattern
                    },
                    "metadata": {
                        "execution_time_ms": execution_time,
                        "server": server,
                        "timestamp": timestamp,
                        "user": server_config.username
                    },
                    "error": None
                }
                
            finally:
                await self.connection_manager.release_connection(server, conn)
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"Service listing failed: {e}")
            
            return {
                "success": False,
                "data": None,
                "metadata": {
                    "execution_time_ms": execution_time,
                    "server": server or "unknown",
                    "timestamp": timestamp,
                    "user": server_config.username if 'server_config' in locals() else "unknown"
                },
                "error": {
                    "code": type(e).__name__,
                    "message": str(e),
                    "details": {"running_only": running_only, "pattern": pattern}
                }
            }
    
    async def get_service_logs(
        self,
        service_name: str,
        server: Optional[str] = None,
        lines: int = 50,
        follow: bool = False
    ) -> Dict[str, Any]:
        """Get service logs.
        
        Args:
            service_name: Service name
            server: Target server name
            lines: Number of lines to retrieve
            follow: Follow logs (not implemented for security)
            
        Returns:
            Service logs
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        try:
            if follow:
                raise ServiceError("Log following is not supported for security reasons")
            
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise ServiceError("No servers configured")
                server = servers[0]
            
            # Get server configuration
            if server not in self.connection_manager.pools:
                raise ServiceError(f"Server {server} not found")
            
            server_config = self.connection_manager.pools[server].server_config
            
            # Get server system information
            server_info = await self._get_server_info(server)
            init_system = server_info["init_system"]
            
            # Normalize service name
            normalized_service = ServiceCommandMapper.normalize_service_name(service_name, init_system)
            
            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise ServiceError(f"No available connections for server {server}")
            
            try:
                logs = ""
                
                if init_system == InitSystem.SYSTEMD:
                    # Use journalctl for systemd
                    command = f"journalctl -u {normalized_service} -n {lines} --no-pager"
                    result = await conn.connection.run(command, check=False)
                    logs = result.stdout
                    
                elif init_system in [InitSystem.UPSTART, InitSystem.SYSVINIT]:
                    # Try common log locations
                    log_locations = [
                        f"/var/log/{service_name}.log",
                        f"/var/log/{service_name}/{service_name}.log",
                        f"/var/log/syslog | grep {service_name}",
                        f"/var/log/messages | grep {service_name}"
                    ]
                    
                    for log_path in log_locations:
                        try:
                            if "grep" in log_path:
                                command = f"tail -n {lines} {log_path}"
                            else:
                                command = f"tail -n {lines} {log_path} 2>/dev/null"
                            
                            result = await conn.connection.run(command, check=False)
                            if result.returncode == 0 and result.stdout.strip():
                                logs = result.stdout
                                break
                        except:
                            continue
                
                execution_time = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "data": {
                        "service": service_name,
                        "normalized_service": normalized_service,
                        "logs": logs,
                        "lines_requested": lines,
                        "init_system": init_system.value
                    },
                    "metadata": {
                        "execution_time_ms": execution_time,
                        "server": server,
                        "timestamp": timestamp,
                        "user": server_config.username
                    },
                    "error": None
                }
                
            finally:
                await self.connection_manager.release_connection(server, conn)
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"Service logs retrieval failed: {e}")
            
            return {
                "success": False,
                "data": None,
                "metadata": {
                    "execution_time_ms": execution_time,
                    "server": server or "unknown",
                    "timestamp": timestamp,
                    "user": server_config.username if 'server_config' in locals() else "unknown"
                },
                "error": {
                    "code": type(e).__name__,
                    "message": str(e),
                    "details": {"service": service_name, "lines": lines}
                }
            }
    
    async def _get_server_info(self, server: str) -> Dict[str, Any]:
        """Get cached server information (init system, distro family).
        
        Args:
            server: Server name
            
        Returns:
            Server information dictionary
        """
        cache_key = server
        
        # Check cache
        if cache_key in self._server_info_cache:
            cached_info = self._server_info_cache[cache_key]
            if time.time() - cached_info["timestamp"] < self._cache_ttl:
                return cached_info
        
        # Detect server information
        conn = await self.connection_manager.get_connection(server)
        if not conn:
            raise ServiceError(f"No available connections for server {server}")
        
        try:
            init_system = await DistroDetector.detect_init_system(conn.connection)
            distro_family, distro_name = await DistroDetector.detect_distro_family(conn.connection)
            
            server_info = {
                "init_system": init_system,
                "distro_family": distro_family,
                "distro_name": distro_name,
                "timestamp": time.time()
            }
            
            # Cache the information
            self._server_info_cache[cache_key] = server_info
            
            logger.info(f"Detected {server}: {init_system.value} init system, {distro_name}")
            
            return server_info
            
        finally:
            await self.connection_manager.release_connection(server, conn)
    
    async def _list_services_by_init_system(
        self, conn: SSHConnection, init_system: InitSystem, running_only: bool
    ) -> List[Dict[str, Any]]:
        """List services based on the init system.
        
        Args:
            conn: SSH connection
            init_system: Detected init system
            running_only: Show only running services
            
        Returns:
            List of service dictionaries
        """
        services = []
        
        if init_system == InitSystem.SYSTEMD:
            services = await self._list_systemd_services(conn, running_only)
        elif init_system == InitSystem.UPSTART:
            services = await self._list_upstart_services(conn, running_only)
        elif init_system == InitSystem.SYSVINIT:
            services = await self._list_sysv_services(conn, running_only)
        
        return services
    
    async def _list_systemd_services(self, conn: SSHConnection, running_only: bool) -> List[Dict[str, Any]]:
        """List systemd services."""
        try:
            if running_only:
                command = "systemctl list-units --type=service --state=running --no-pager --no-legend"
            else:
                command = "systemctl list-units --type=service --all --no-pager --no-legend"
            
            result = await conn.connection.run(command, check=True)
            services = []
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                
                parts = line.split(None, 4)
                if len(parts) >= 4:
                    service_name = parts[0]
                    load_state = parts[1]
                    active_state = parts[2]
                    sub_state = parts[3]
                    description = parts[4] if len(parts) > 4 else ""
                    
                    services.append({
                        "name": service_name,
                        "load_state": load_state,
                        "active_state": active_state,
                        "sub_state": sub_state,
                        "description": description,
                        "running": active_state == "active" and sub_state == "running"
                    })
            
            return services
            
        except Exception as e:
            logger.warning(f"Failed to list systemd services: {e}")
            return []
    
    async def _list_upstart_services(self, conn: SSHConnection, running_only: bool) -> List[Dict[str, Any]]:
        """List upstart services."""
        try:
            result = await conn.connection.run("initctl list", check=True)
            services = []
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                
                # Parse initctl output: "service start/running, process 1234" or "service stop/waiting"
                parts = line.split(' ', 1)
                if len(parts) >= 2:
                    service_name = parts[0]
                    status_info = parts[1]
                    
                    is_running = "start/running" in status_info
                    
                    if not running_only or is_running:
                        services.append({
                            "name": service_name,
                            "status": status_info,
                            "running": is_running
                        })
            
            return services
            
        except Exception as e:
            logger.warning(f"Failed to list upstart services: {e}")
            return []
    
    async def _list_sysv_services(self, conn: SSHConnection, running_only: bool) -> List[Dict[str, Any]]:
        """List SysV init services."""
        try:
            # List services from /etc/init.d/
            result = await conn.connection.run("ls /etc/init.d/", check=True)
            service_files = result.stdout.strip().split()
            
            services = []
            
            # Skip common non-service files
            skip_files = {'README', 'skeleton', 'rcS', 'rc', 'rc.local', 'functions'}
            
            for service_file in service_files:
                if service_file in skip_files or service_file.startswith('.'):
                    continue
                
                try:
                    # Check if service is running
                    status_result = await conn.connection.run(
                        f"/etc/init.d/{service_file} status 2>/dev/null", check=False
                    )
                    
                    is_running = status_result.returncode == 0
                    
                    if not running_only or is_running:
                        services.append({
                            "name": service_file,
                            "status": "running" if is_running else "stopped",
                            "running": is_running
                        })
                        
                except:
                    # If status check fails, just list the service
                    if not running_only:
                        services.append({
                            "name": service_file,
                            "status": "unknown",
                            "running": False
                        })
            
            return services
            
        except Exception as e:
            logger.warning(f"Failed to list SysV services: {e}")
            return []
    
    def _parse_service_result(
        self, result, action: str, init_system: InitSystem, service: str
    ) -> Dict[str, Any]:
        """Parse service command result based on init system and action.
        
        Args:
            result: Command execution result
            action: Service action performed
            init_system: Init system used
            service: Service name
            
        Returns:
            Parsed result dictionary
        """
        parsed = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
        
        # Parse status output for different init systems
        if action == "status":
            if init_system == InitSystem.SYSTEMD:
                # Parse systemctl status output
                stdout = result.stdout.lower()
                if "active (running)" in stdout:
                    parsed["status"] = "running"
                elif "inactive (dead)" in stdout:
                    parsed["status"] = "stopped"
                elif "failed" in stdout:
                    parsed["status"] = "failed"
                else:
                    parsed["status"] = "unknown"
                    
            elif init_system == InitSystem.UPSTART:
                # Parse upstart status
                stdout = result.stdout.lower()
                if "start/running" in stdout:
                    parsed["status"] = "running"
                elif "stop/waiting" in stdout:
                    parsed["status"] = "stopped"
                else:
                    parsed["status"] = "unknown"
                    
            elif init_system == InitSystem.SYSVINIT:
                # Parse SysV status (varies by service)
                if result.returncode == 0:
                    parsed["status"] = "running"
                else:
                    parsed["status"] = "stopped"
        
        return parsed