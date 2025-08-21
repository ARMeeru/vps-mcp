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
from ..utils.secure_sudo import SecureSudoHandler
from ..utils.mcp_responses import MCPResponse, MCPCommandError

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
            
        except (MCPCommandError, CommandSecurityError):
            # Re-raise MCP and security exceptions
            raise
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"Command execution failed: {e}")
            
            # Convert to MCP exception
            raise MCPCommandError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "server": server or "unknown",
                    "command": command,
                    "execution_time_ms": execution_time
                }
            )
    
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
            
            # Check if command needs sudo and handle securely
            validator = SecurityValidator(server_config.allowed_paths)
            needs_sudo = validator.check_sudo_requirements(command) and not command.strip().startswith('sudo')
            
            if needs_sudo:
                # Use secure sudo handling
                sudo_password = self.connection_manager.pools[server].sudo_password
                
                if sudo_password:
                    # Secure sudo with password
                    result = await SecureSudoHandler.execute_with_sudo(
                        conn.connection, command, sudo_password, timeout
                    )
                else:
                    # Passwordless sudo
                    result = await SecureSudoHandler.execute_without_password(
                        conn.connection, command, timeout
                    )
                    
                # Convert SecureSudoResult to expected format
                class SudoResult:
                    def __init__(self, stdout, stderr, returncode):
                        self.stdout = stdout
                        self.stderr = stderr
                        self.returncode = returncode
                
                result = SudoResult(result.stdout, result.stderr, result.returncode)
                
            else:
                # Execute regular command
                if stream_output and timeout > 3:
                    result = await self._execute_with_streaming(conn, command, timeout)
                else:
                    result = await asyncio.wait_for(
                        conn.connection.run(command, check=False),
                        timeout=timeout
                    )
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log command execution for audit
            logger.info(f"Command executed on {server}: {command[:100]}...")
            
            # Return MCP-compliant response - data directly, no wrapper
            result_data = MCPResponse.command_result(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.returncode,
                execution_time_ms=execution_time,
                server=server,
                command=command
            )
            
            # For failed commands, raise MCP exception instead of returning error in response
            if result.returncode != 0:
                raise MCPCommandError(
                    message=f"Command exited with code {result.returncode}",
                    error_code="COMMAND_FAILED",
                    details={
                        "stdout": result.stdout or "",
                        "stderr": result.stderr or "",
                        "exit_code": result.returncode,
                        "command": command,
                        "server": server
                    }
                )
            
            return result_data
            
        except asyncio.TimeoutError:
            execution_time = int((time.time() - start_time) * 1000)
            raise MCPCommandError(
                message=f"Command timed out after {timeout} seconds",
                error_code="COMMAND_TIMEOUT",
                details={"timeout": timeout, "server": server, "command": command}
            )
            
        except MCPCommandError:
            # Re-raise MCP exceptions
            raise
            
        except Exception as e:
            raise MCPCommandError(
                message=f"Command execution failed: {str(e)}",
                error_code="EXECUTION_ERROR",
                details={"server": server, "command": command, "error": str(e)}
            )
            
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
        
        # Return MCP-compliant response for background job start
        return {
            "job_id": job_id,
            "command": command,
            "server": server,
            "status": "started",
            "timestamp": datetime.utcnow().isoformat() + "Z"
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
            # Store MCP exception details for background jobs
            job.result = {
                "error": {
                    "code": type(e).__name__,
                    "message": str(e),
                    "details": getattr(e, "details", {})
                }
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
            raise MCPCommandError(
                message=f"Job {job_id} not found",
                error_code="JOB_NOT_FOUND",
                details={"job_id": job_id}
            )
        
        job = self.background_jobs[job_id]
        
        # Return MCP-compliant response for job status
        return {
            "job_id": job_id,
            "command": job.command,
            "server": job.server_name,
            "status": job.status,
            "start_time": job.start_time,
            "result": job.result,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    async def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a background job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Cancellation result
        """
        if job_id not in self.background_jobs:
            raise MCPCommandError(
                message=f"Job {job_id} not found",
                error_code="JOB_NOT_FOUND",
                details={"job_id": job_id}
            )
        
        job = self.background_jobs[job_id]
        
        if job.task and not job.task.done():
            job.task.cancel()
            job.status = "cancelled"
        
        # Return MCP-compliant response for job cancellation
        return {
            "job_id": job_id,
            "status": job.status,
            "timestamp": datetime.utcnow().isoformat() + "Z"
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
        
        # Return MCP-compliant response for job list
        return {
            "jobs": jobs,
            "total_count": len(jobs),
            "server_filter": server,
            "timestamp": datetime.utcnow().isoformat() + "Z"
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