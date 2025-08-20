"""Command execution tool for MCP VPS Manager."""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import json

from ..connection_pool import ConnectionManager, SSHConnection
from ..security import SecurityValidator, CommandSecurityError
from ..config import ServerConfig

logger = logging.getLogger(__name__)


class CommandExecutionError(Exception):
    """Command execution errors."""
    pass


class BackgroundJob:
    """Represents a background command execution job."""
    
    def __init__(self, job_id: str, command: str, server_name: str):
        """Initialize background job.
        
        Args:
            job_id: Unique job identifier
            command: Command being executed
            server_name: Target server name
        """
        self.job_id = job_id
        self.command = command
        self.server_name = server_name
        self.start_time = time.time()
        self.task: Optional[asyncio.Task] = None
        self.result: Optional[Dict[str, Any]] = None
        self.status = "running"


class CommandTool:
    """Tool for executing shell commands on VPS servers."""
    
    def __init__(self, connection_manager: ConnectionManager):
        """Initialize command tool.
        
        Args:
            connection_manager: SSH connection manager
        """
        self.connection_manager = connection_manager
        self.background_jobs: Dict[str, BackgroundJob] = {}
        self._job_counter = 0
    
    async def exec_command(
        self,
        command: str,
        server: Optional[str] = None,
        timeout: int = 30,
        background: bool = False,
        stream_output: bool = False
    ) -> Dict[str, Any]:
        """Execute a shell command on a VPS server.
        
        Args:
            command: Shell command to execute
            server: Target server name (uses first available if None)
            timeout: Command timeout in seconds
            background: Run command in background
            stream_output: Stream output for long-running commands
            
        Returns:
            Command execution result dictionary
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise CommandExecutionError("No servers configured")
                server = servers[0]
            
            # Get server configuration for security validation
            server_pools = self.connection_manager.pools
            if server not in server_pools:
                raise CommandExecutionError(f"Server {server} not found")
            
            server_config = server_pools[server].server_config
            
            # Security validation
            validator = SecurityValidator(
                server_config.allowed_paths,
                server_config.blocked_commands
            )
            
            is_valid, error = validator.validate_command(command, 10000)
            if not is_valid:
                raise CommandSecurityError(error)
            
            # Handle background execution
            if background:
                return await self._execute_background(command, server, timeout)
            
            # Execute command synchronously
            return await self._execute_sync(
                command, server, timeout, stream_output, start_time, timestamp
            )
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"Command execution failed: {e}")
            
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
                    "details": {"command": command}
                }
            }
    
    async def _execute_sync(
        self,
        command: str,
        server: str,
        timeout: int,
        stream_output: bool,
        start_time: float,
        timestamp: str
    ) -> Dict[str, Any]:
        """Execute command synchronously.
        
        Args:
            command: Command to execute
            server: Target server
            timeout: Timeout in seconds
            stream_output: Whether to stream output
            start_time: Execution start time
            timestamp: ISO timestamp
            
        Returns:
            Execution result dictionary
        """
        conn = None
        try:
            # Get connection
            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise CommandExecutionError(f"No available connections for server {server}")
            
            server_config = self.connection_manager.pools[server].server_config
            
            # Prepare command with sudo if needed
            validator = SecurityValidator(server_config.allowed_paths)
            final_command = command
            
            if validator.check_sudo_requirements(command) and not command.strip().startswith('sudo'):
                sudo_password = self.connection_manager.pools[server].sudo_password
                if sudo_password:
                    # Use sudo with password
                    final_command = f"echo '{sudo_password}' | sudo -S {command}"
                else:
                    # Try sudo without password (might be configured for passwordless sudo)
                    final_command = f"sudo {command}"
            
            # Execute command
            if stream_output and timeout > 3:
                result = await self._execute_with_streaming(conn, final_command, timeout)
            else:
                result = await asyncio.wait_for(
                    conn.connection.run(final_command, check=False),
                    timeout=timeout
                )
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log command execution for audit
            logger.info(f"Command executed on {server}: {command[:100]}...")
            
            return {
                "success": result.returncode == 0,
                "data": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "command": command
                },
                "metadata": {
                    "execution_time_ms": execution_time,
                    "server": server,
                    "timestamp": timestamp,
                    "user": server_config.username
                },
                "error": None if result.returncode == 0 else {
                    "code": "COMMAND_FAILED",
                    "message": f"Command exited with code {result.returncode}",
                    "details": {"stderr": result.stderr}
                }
            }
            
        except asyncio.TimeoutError:
            execution_time = int((time.time() - start_time) * 1000)
            raise CommandExecutionError(f"Command timed out after {timeout} seconds")
            
        except Exception as e:
            raise CommandExecutionError(f"Command execution failed: {e}")
            
        finally:
            if conn:
                await self.connection_manager.release_connection(server, conn)
    
    async def _execute_with_streaming(
        self,
        conn: SSHConnection,
        command: str,
        timeout: int
    ) -> Any:
        """Execute command with output streaming for long-running operations.
        
        Args:
            conn: SSH connection
            command: Command to execute
            timeout: Timeout in seconds
            
        Returns:
            Command result
        """
        # For now, implement basic execution
        # TODO: Implement actual streaming with progress callbacks
        return await asyncio.wait_for(
            conn.connection.run(command, check=False),
            timeout=timeout
        )
    
    async def _execute_background(
        self, command: str, server: str, timeout: int
    ) -> Dict[str, Any]:
        """Execute command in background.
        
        Args:
            command: Command to execute
            server: Target server
            timeout: Timeout in seconds
            
        Returns:
            Background job information
        """
        # Generate job ID
        self._job_counter += 1
        job_id = f"job-{server}-{self._job_counter}"
        
        # Create background job
        job = BackgroundJob(job_id, command, server)
        self.background_jobs[job_id] = job
        
        # Start background task
        job.task = asyncio.create_task(
            self._background_job_runner(job, timeout)
        )
        
        return {
            "success": True,
            "data": {
                "job_id": job_id,
                "command": command,
                "server": server,
                "status": "started"
            },
            "metadata": {
                "execution_time_ms": 0,
                "server": server,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "user": self.connection_manager.pools[server].server_config.username
            },
            "error": None
        }
    
    async def _background_job_runner(self, job: BackgroundJob, timeout: int) -> None:
        """Run background job.
        
        Args:
            job: Background job to run
            timeout: Job timeout
        """
        try:
            result = await self._execute_sync(
                job.command,
                job.server_name,
                timeout,
                False,
                job.start_time,
                datetime.utcnow().isoformat() + "Z"
            )
            job.result = result
            job.status = "completed"
            
        except Exception as e:
            job.result = {
                "success": False,
                "error": {"code": type(e).__name__, "message": str(e)}
            }
            job.status = "failed"
            logger.error(f"Background job {job.job_id} failed: {e}")
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a background job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status dictionary
        """
        if job_id not in self.background_jobs:
            return {
                "success": False,
                "data": None,
                "error": {
                    "code": "JOB_NOT_FOUND",
                    "message": f"Job {job_id} not found"
                }
            }
        
        job = self.background_jobs[job_id]
        
        return {
            "success": True,
            "data": {
                "job_id": job_id,
                "command": job.command,
                "server": job.server_name,
                "status": job.status,
                "start_time": job.start_time,
                "result": job.result
            },
            "error": None
        }
    
    async def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a background job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Cancellation result
        """
        if job_id not in self.background_jobs:
            return {
                "success": False,
                "error": {
                    "code": "JOB_NOT_FOUND",
                    "message": f"Job {job_id} not found"
                }
            }
        
        job = self.background_jobs[job_id]
        
        if job.task and not job.task.done():
            job.task.cancel()
            job.status = "cancelled"
        
        return {
            "success": True,
            "data": {
                "job_id": job_id,
                "status": job.status
            },
            "error": None
        }
    
    def list_jobs(self, server: Optional[str] = None) -> Dict[str, Any]:
        """List background jobs.
        
        Args:
            server: Filter by server name (optional)
            
        Returns:
            List of jobs
        """
        jobs = []
        
        for job_id, job in self.background_jobs.items():
            if server is None or job.server_name == server:
                jobs.append({
                    "job_id": job_id,
                    "command": job.command,
                    "server": job.server_name,
                    "status": job.status,
                    "start_time": job.start_time
                })
        
        return {
            "success": True,
            "data": {"jobs": jobs},
            "error": None
        }
    
    def cleanup_completed_jobs(self, max_age_hours: int = 24) -> int:
        """Clean up old completed jobs.
        
        Args:
            max_age_hours: Maximum age of jobs to keep
            
        Returns:
            Number of jobs cleaned up
        """
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        jobs_to_remove = []
        
        for job_id, job in self.background_jobs.items():
            job_age = current_time - job.start_time
            if job.status in ["completed", "failed", "cancelled"] and job_age > max_age_seconds:
                jobs_to_remove.append(job_id)
        
        for job_id in jobs_to_remove:
            del self.background_jobs[job_id]
        
        logger.info(f"Cleaned up {len(jobs_to_remove)} old background jobs")
        return len(jobs_to_remove)