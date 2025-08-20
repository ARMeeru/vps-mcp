"""
MCP protocol-compliant response formatters.

This module provides response formatters that follow MCP protocol specifications.
Tools should return data directly and use exceptions for errors.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime


class MCPToolError(Exception):
    """Base exception for MCP tool errors that should be returned to clients."""
    
    def __init__(self, message: str, error_code: str = "TOOL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class MCPCommandError(MCPToolError):
    """Command execution error for MCP protocol."""
    pass


class MCPFileError(MCPToolError):
    """File operation error for MCP protocol."""
    pass


class MCPServiceError(MCPToolError):
    """Service management error for MCP protocol."""
    pass


class MCPMonitoringError(MCPToolError):
    """System monitoring error for MCP protocol."""
    pass


class MCPResponse:
    """MCP protocol-compliant response formatters."""
    
    @staticmethod
    def command_result(stdout: str, stderr: str, exit_code: int, execution_time_ms: int, 
                       server: str, command: str) -> Dict[str, Any]:
        """
        Format command execution result for MCP protocol.
        
        Args:
            stdout: Command standard output
            stderr: Command standard error  
            exit_code: Command exit code
            execution_time_ms: Execution time in milliseconds
            server: Target server name
            command: Executed command
            
        Returns:
            MCP-compliant response dictionary
        """
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "execution_time_ms": execution_time_ms,
            "server": server,
            "command": command[:100] + "..." if len(command) > 100 else command,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @staticmethod
    def file_read_result(content: str, path: str, size_bytes: int, 
                        encoding: str = "utf-8", server: str = None) -> Dict[str, Any]:
        """
        Format file read result for MCP protocol.
        
        Args:
            content: File content
            path: File path
            size_bytes: File size in bytes
            encoding: Text encoding used
            server: Server name
            
        Returns:
            MCP-compliant response dictionary
        """
        return {
            "content": content,
            "path": path,
            "size_bytes": size_bytes,
            "encoding": encoding,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @staticmethod
    def file_write_result(path: str, size_bytes: int, backup_path: Optional[str] = None, 
                         created_dirs: Optional[List[str]] = None, server: str = None) -> Dict[str, Any]:
        """
        Format file write result for MCP protocol.
        
        Args:
            path: Written file path
            size_bytes: Written file size
            backup_path: Backup file path if created
            created_dirs: List of directories created
            server: Server name
            
        Returns:
            MCP-compliant response dictionary
        """
        result = {
            "path": path,
            "size_bytes": size_bytes,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        if backup_path:
            result["backup_path"] = backup_path
            
        if created_dirs:
            result["created_directories"] = created_dirs
            
        return result
    
    @staticmethod
    def file_transfer_result(local_path: str, remote_path: str, size_bytes: int, 
                           direction: str, server: str = None) -> Dict[str, Any]:
        """
        Format file transfer result for MCP protocol.
        
        Args:
            local_path: Local file path
            remote_path: Remote file path
            size_bytes: Transferred file size
            direction: Transfer direction ("upload" or "download")
            server: Server name
            
        Returns:
            MCP-compliant response dictionary
        """
        return {
            "local_path": local_path,
            "remote_path": remote_path,
            "size_bytes": size_bytes,
            "direction": direction,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @staticmethod
    def system_status_result(cpu_percent: float, memory_percent: float, 
                           disk_usage: Dict[str, Any], load_average: List[float],
                           uptime_seconds: int, server: str = None,
                           additional_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Format system status result for MCP protocol.
        
        Args:
            cpu_percent: CPU usage percentage
            memory_percent: Memory usage percentage
            disk_usage: Disk usage information
            load_average: System load averages [1min, 5min, 15min]
            uptime_seconds: System uptime in seconds
            server: Server name
            additional_metrics: Additional system metrics
            
        Returns:
            MCP-compliant response dictionary
        """
        result = {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_usage": disk_usage,
            "load_average": load_average,
            "uptime_seconds": uptime_seconds,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        if additional_metrics:
            result.update(additional_metrics)
            
        return result
    
    @staticmethod
    def service_control_result(service: str, action: str, status: str, 
                             output: str = "", server: str = None) -> Dict[str, Any]:
        """
        Format service control result for MCP protocol.
        
        Args:
            service: Service name
            action: Action performed
            status: Service status after action
            output: Command output
            server: Server name
            
        Returns:
            MCP-compliant response dictionary
        """
        return {
            "service": service,
            "action": action,
            "status": status,
            "output": output,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @staticmethod
    def service_list_result(services: List[Dict[str, Any]], total_count: int, 
                          server: str = None, filter_applied: str = None) -> Dict[str, Any]:
        """
        Format service list result for MCP protocol.
        
        Args:
            services: List of service information dictionaries
            total_count: Total number of services
            server: Server name
            filter_applied: Filter that was applied
            
        Returns:
            MCP-compliant response dictionary
        """
        result = {
            "services": services,
            "total_count": total_count,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        if filter_applied:
            result["filter_applied"] = filter_applied
            
        return result
    
    @staticmethod
    def service_logs_result(service: str, logs: str, lines_returned: int,
                          server: str = None) -> Dict[str, Any]:
        """
        Format service logs result for MCP protocol.
        
        Args:
            service: Service name
            logs: Log content
            lines_returned: Number of log lines returned
            server: Server name
            
        Returns:
            MCP-compliant response dictionary
        """
        return {
            "service": service,
            "logs": logs,
            "lines_returned": lines_returned,
            "server": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }