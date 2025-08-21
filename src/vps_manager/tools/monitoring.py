"""System monitoring tool for MCP VPS Manager."""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import json
import re

from ..connection_pool import ConnectionManager, SSHConnection
from ..security import SecurityValidator
from ..config import ServerConfig
from ..utils.mcp_responses import MCPResponse, MCPMonitoringError

logger = logging.getLogger(__name__)


class MonitoringError(Exception):
    """Monitoring operation errors."""
    pass


class SystemMonitoringTool:
    """Tool for monitoring VPS system status and metrics."""
    
    def __init__(self, connection_manager: ConnectionManager):
        """Initialize monitoring tool.
        
        Args:
            connection_manager: SSH connection manager
        """
        self.connection_manager = connection_manager
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 5  # 5 seconds cache TTL
    
    async def get_system_status(
        self,
        server: Optional[str] = None,
        detailed: bool = False
    ) -> Dict[str, Any]:
        """Get comprehensive system status for a VPS server.
        
        Args:
            server: Target server name
            detailed: Include detailed metrics
            
        Returns:
            System status dictionary
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise MonitoringError("No servers configured")
                server = servers[0]
            
            # Check cache first
            cache_key = f"{server}-status-{detailed}"
            if cache_key in self._cache:
                cached_data = self._cache[cache_key]
                if time.time() - cached_data["timestamp"] < self._cache_ttl:
                    logger.debug(f"Returning cached status for {server}")
                    return cached_data["data"]
            
            # Get server configuration
            if server not in self.connection_manager.pools:
                raise MonitoringError(f"Server {server} not found")
            
            server_config = self.connection_manager.pools[server].server_config
            
            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise MonitoringError(f"No available connections for server {server}")
            
            try:
                # Collect system metrics
                status_data = await self._collect_system_metrics(conn, detailed)
                
                execution_time = int((time.time() - start_time) * 1000)
                
                # Extract required data for MCP response
                cpu_percent = status_data.get("cpu", {}).get("usage_percent", 0.0)
                memory_percent = status_data.get("memory", {}).get("usage_percent", 0.0)
                disk_usage = status_data.get("disk", {})
                load_avg_data = status_data.get("load_average", {})
                load_average = [load_avg_data.get("1min", 0.0), load_avg_data.get("5min", 0.0), load_avg_data.get("15min", 0.0)]
                uptime_seconds = status_data.get("uptime", {}).get("uptime_seconds", 0)
                
                # Prepare additional metrics for detailed mode
                additional_metrics = None
                if detailed:
                    additional_metrics = {
                        "network": status_data.get("network", {}),
                        "processes": status_data.get("processes", {}),
                        "system": status_data.get("system", {})
                    }
                
                # Return MCP-compliant response - data directly
                result = MCPResponse.system_status_result(
                    cpu_percent=cpu_percent,
                    memory_percent=memory_percent,
                    disk_usage=disk_usage,
                    load_average=load_average,
                    uptime_seconds=uptime_seconds,
                    server=server,
                    additional_metrics=additional_metrics
                )
                
                # Cache the result
                self._cache[cache_key] = {
                    "data": result,
                    "timestamp": time.time()
                }
                
                return result
                
            finally:
                await self.connection_manager.release_connection(server, conn)
                
        except MCPMonitoringError:
            # Re-raise MCP exceptions
            raise
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"System monitoring failed: {e}")
            
            # Convert to MCP exception
            raise MCPMonitoringError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "server": server or "unknown",
                    "execution_time_ms": execution_time
                }
            )
    
    async def _collect_system_metrics(
        self, conn: SSHConnection, detailed: bool
    ) -> Dict[str, Any]:
        """Collect system metrics from the server.
        
        Args:
            conn: SSH connection
            detailed: Whether to collect detailed metrics
            
        Returns:
            Dictionary of system metrics
        """
        metrics = {}
        
        # Get basic metrics in parallel
        basic_tasks = [
            self._get_cpu_info(conn),
            self._get_memory_info(conn),
            self._get_disk_info(conn),
            self._get_load_average(conn),
            self._get_uptime(conn),
        ]
        
        cpu_info, memory_info, disk_info, load_avg, uptime = await asyncio.gather(
            *basic_tasks, return_exceptions=True
        )
        
        # Process results
        if not isinstance(cpu_info, Exception):
            metrics["cpu"] = cpu_info
        
        if not isinstance(memory_info, Exception):
            metrics["memory"] = memory_info
        
        if not isinstance(disk_info, Exception):
            metrics["disk"] = disk_info
        
        if not isinstance(load_avg, Exception):
            metrics["load_average"] = load_avg
        
        if not isinstance(uptime, Exception):
            metrics["uptime"] = uptime
        
        # Get detailed metrics if requested
        if detailed:
            detailed_tasks = [
                self._get_network_info(conn),
                self._get_process_info(conn),
                self._get_system_info(conn),
            ]
            
            network_info, process_info, system_info = await asyncio.gather(
                *detailed_tasks, return_exceptions=True
            )
            
            if not isinstance(network_info, Exception):
                metrics["network"] = network_info
            
            if not isinstance(process_info, Exception):
                metrics["processes"] = process_info
            
            if not isinstance(system_info, Exception):
                metrics["system"] = system_info
        
        return metrics
    
    async def _get_cpu_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get CPU usage information."""
        try:
            # Try to read from /proc/stat for current usage
            result = await conn.connection.run("cat /proc/stat | head -1", check=True)
            stat_line = result.stdout.strip()
            
            # Parse CPU times
            fields = stat_line.split()
            if len(fields) >= 8:
                user, nice, system, idle, iowait, irq, softirq, steal = map(int, fields[1:9])
                
                total = user + nice + system + idle + iowait + irq + softirq + steal
                used = total - idle - iowait
                
                cpu_percent = (used / total) * 100 if total > 0 else 0.0
            else:
                cpu_percent = 0.0
            
            # Get CPU info
            cpuinfo_result = await conn.connection.run("nproc", check=True)
            cpu_count = int(cpuinfo_result.stdout.strip())
            
            return {
                "usage_percent": round(cpu_percent, 2),
                "core_count": cpu_count
            }
            
        except Exception as e:
            logger.warning(f"Failed to get CPU info: {e}")
            # Fallback to top command
            try:
                result = await conn.connection.run("top -bn1 | grep 'Cpu(s)' | head -1", check=True)
                output = result.stdout.strip()
                
                # Parse top output for CPU usage
                match = re.search(r'(\d+\.?\d*)%us', output)
                if match:
                    cpu_percent = float(match.group(1))
                else:
                    cpu_percent = 0.0
                
                return {"usage_percent": round(cpu_percent, 2), "core_count": 1}
            except:
                return {"usage_percent": 0.0, "core_count": 1}
    
    async def _get_memory_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get memory usage information."""
        try:
            result = await conn.connection.run("cat /proc/meminfo", check=True)
            meminfo = result.stdout
            
            # Parse memory info
            memory_data = {}
            for line in meminfo.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip().split()[0]  # Get numeric value
                    try:
                        memory_data[key] = int(value) * 1024  # Convert KB to bytes
                    except ValueError:
                        continue
            
            total_memory = memory_data.get('MemTotal', 0)
            free_memory = memory_data.get('MemFree', 0)
            available_memory = memory_data.get('MemAvailable', free_memory)
            buffers = memory_data.get('Buffers', 0)
            cached = memory_data.get('Cached', 0)
            
            used_memory = total_memory - available_memory
            memory_percent = (used_memory / total_memory) * 100 if total_memory > 0 else 0.0
            
            return {
                "total_bytes": total_memory,
                "used_bytes": used_memory,
                "free_bytes": available_memory,
                "usage_percent": round(memory_percent, 2),
                "buffers_bytes": buffers,
                "cached_bytes": cached
            }
            
        except Exception as e:
            logger.warning(f"Failed to get memory info: {e}")
            # Fallback to free command
            try:
                result = await conn.connection.run("free -b", check=True)
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    memory_line = lines[1].split()
                    total = int(memory_line[1])
                    used = int(memory_line[2])
                    free = int(memory_line[3])
                    
                    return {
                        "total_bytes": total,
                        "used_bytes": used,
                        "free_bytes": free,
                        "usage_percent": round((used / total) * 100, 2) if total > 0 else 0.0
                    }
            except:
                pass
            
            return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "usage_percent": 0.0}
    
    async def _get_disk_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get disk usage information."""
        try:
            result = await conn.connection.run("df -B1", check=True)
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            
            filesystems = []
            total_used = 0
            total_size = 0
            
            for line in lines:
                fields = line.split()
                if len(fields) >= 6:
                    filesystem = fields[0]
                    size = int(fields[1])
                    used = int(fields[2])
                    available = int(fields[3])
                    use_percent = fields[4].rstrip('%')
                    mount = fields[5]
                    
                    # Skip special filesystems
                    if filesystem.startswith(('/dev/loop', 'tmpfs', 'udev', 'devtmpfs')):
                        continue
                    
                    try:
                        use_percent_num = float(use_percent)
                    except ValueError:
                        use_percent_num = 0.0
                    
                    filesystems.append({
                        "filesystem": filesystem,
                        "mount_point": mount,
                        "total_bytes": size,
                        "used_bytes": used,
                        "available_bytes": available,
                        "usage_percent": use_percent_num
                    })
                    
                    # Aggregate for root filesystem
                    if mount == "/":
                        total_size = size
                        total_used = used
            
            total_percent = (total_used / total_size) * 100 if total_size > 0 else 0.0
            
            return {
                "total_bytes": total_size,
                "used_bytes": total_used,
                "available_bytes": total_size - total_used,
                "usage_percent": round(total_percent, 2),
                "filesystems": filesystems
            }
            
        except Exception as e:
            logger.warning(f"Failed to get disk info: {e}")
            return {
                "total_bytes": 0,
                "used_bytes": 0,
                "available_bytes": 0,
                "usage_percent": 0.0,
                "filesystems": []
            }
    
    async def _get_load_average(self, conn: SSHConnection) -> Dict[str, float]:
        """Get system load average."""
        try:
            result = await conn.connection.run("cat /proc/loadavg", check=True)
            load_data = result.stdout.strip().split()[:3]
            
            return {
                "1min": float(load_data[0]),
                "5min": float(load_data[1]),
                "15min": float(load_data[2])
            }
            
        except Exception as e:
            logger.warning(f"Failed to get load average: {e}")
            return {"1min": 0.0, "5min": 0.0, "15min": 0.0}
    
    async def _get_uptime(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get system uptime."""
        try:
            result = await conn.connection.run("cat /proc/uptime", check=True)
            uptime_seconds = float(result.stdout.strip().split()[0])
            
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            
            return {
                "uptime_seconds": int(uptime_seconds),
                "uptime_formatted": f"{days}d {hours}h {minutes}m"
            }
            
        except Exception as e:
            logger.warning(f"Failed to get uptime: {e}")
            return {"uptime_seconds": 0, "uptime_formatted": "0d 0h 0m"}
    
    async def _get_network_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get network interface information."""
        try:
            result = await conn.connection.run("cat /proc/net/dev", check=True)
            lines = result.stdout.strip().split('\n')[2:]  # Skip headers
            
            interfaces = []
            for line in lines:
                if ':' in line:
                    interface, data = line.split(':', 1)
                    interface = interface.strip()
                    fields = data.split()
                    
                    if len(fields) >= 16:
                        rx_bytes = int(fields[0])
                        tx_bytes = int(fields[8])
                        
                        interfaces.append({
                            "interface": interface,
                            "rx_bytes": rx_bytes,
                            "tx_bytes": tx_bytes
                        })
            
            return {"interfaces": interfaces}
            
        except Exception as e:
            logger.warning(f"Failed to get network info: {e}")
            return {"interfaces": []}
    
    async def _get_process_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get running process information."""
        try:
            result = await conn.connection.run("ps aux --no-headers | wc -l", check=True)
            process_count = int(result.stdout.strip())
            
            # Get top processes by CPU usage
            result = await conn.connection.run(
                "ps aux --no-headers --sort=-%cpu | head -10", check=True
            )
            
            top_processes = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    fields = line.split(None, 10)
                    if len(fields) >= 11:
                        top_processes.append({
                            "user": fields[0],
                            "pid": int(fields[1]),
                            "cpu_percent": float(fields[2]),
                            "memory_percent": float(fields[3]),
                            "command": fields[10][:50]  # Truncate long commands
                        })
            
            return {
                "total_processes": process_count,
                "top_cpu_processes": top_processes
            }
            
        except Exception as e:
            logger.warning(f"Failed to get process info: {e}")
            return {"total_processes": 0, "top_cpu_processes": []}
    
    async def _get_system_info(self, conn: SSHConnection) -> Dict[str, Any]:
        """Get general system information."""
        try:
            # Get hostname
            hostname_result = await conn.connection.run("hostname", check=True)
            hostname = hostname_result.stdout.strip()
            
            # Get OS info
            try:
                os_result = await conn.connection.run("cat /etc/os-release", check=True)
                os_info = {}
                for line in os_result.stdout.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        os_info[key] = value.strip('"')
                
                os_name = os_info.get('PRETTY_NAME', 'Unknown')
            except:
                os_name = "Unknown"
            
            # Get kernel version
            try:
                kernel_result = await conn.connection.run("uname -r", check=True)
                kernel_version = kernel_result.stdout.strip()
            except:
                kernel_version = "Unknown"
            
            return {
                "hostname": hostname,
                "os_name": os_name,
                "kernel_version": kernel_version
            }
            
        except Exception as e:
            logger.warning(f"Failed to get system info: {e}")
            return {
                "hostname": "Unknown",
                "os_name": "Unknown",
                "kernel_version": "Unknown"
            }
    
    def clear_cache(self, server: Optional[str] = None) -> None:
        """Clear monitoring cache.
        
        Args:
            server: Clear cache for specific server, or all if None
        """
        if server:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"{server}-")]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()
        
        logger.info(f"Cleared monitoring cache for {server or 'all servers'}")