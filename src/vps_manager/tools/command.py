"""Command execution tool for MCP VPS Manager."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..connection_pool import ConnectionManager, SSHConnection
from ..queue import QueueManager, QueuePriority
from ..security import CommandSecurityError, SecurityValidator
from ..utils.mcp_responses import MCPCommandError, MCPResponse
from ..utils.secure_sudo import SecureSudoHandler

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

    def __init__(
        self, connection_manager: ConnectionManager, enable_queue: bool = True
    ):
        """Initialize command tool.

        Args:
            connection_manager: SSH connection manager
            enable_queue: Enable command queuing system
        """
        self.connection_manager = connection_manager
        self.background_jobs: Dict[str, BackgroundJob] = {}
        self._job_counter = 0

        # Initialize queue system
        self.enable_queue = enable_queue
        if enable_queue:
            self.queue_manager = QueueManager()
            # Initialize queues for existing servers
            self._initialize_queues()
        else:
            self.queue_manager = None

    def _initialize_queues(self) -> None:
        """Initialize command queues for all configured servers."""
        if not self.queue_manager:
            return

        for server_name in self.connection_manager.list_servers():
            # Create queue with default settings
            # TODO: Make these configurable per server
            self.queue_manager.create_queue(
                server_name=server_name,
                max_concurrent=3,  # Conservative default
                rate_limit=5,  # 5 commands per second
            )

    def ensure_queue_for_server(self, server_name: str) -> None:
        """Ensure a queue exists for the given server."""
        if self.queue_manager and not self.queue_manager.get_queue(server_name):
            self.queue_manager.create_queue(
                server_name=server_name, max_concurrent=3, rate_limit=5
            )

    async def exec_command(
        self,
        command: str,
        server: Optional[str] = None,
        timeout: int = 30,
        background: bool = False,
        stream_output: bool = False,
        priority: str = "normal",
        use_queue: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Execute a shell command on a VPS server.

        Args:
            command: Shell command to execute
            server: Target server name (uses first available if None)
            timeout: Command timeout in seconds
            background: Run command in background
            stream_output: Stream output for long-running commands
            priority: Command priority (low, normal, high, critical)
            use_queue: Force use/bypass of queue system (None=auto-decide)

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

            # Determine if we should use queuing
            should_use_queue = use_queue
            if should_use_queue is None:
                # Auto-decide: use queue for non-background, non-urgent
                # commands
                should_use_queue = (
                    self.enable_queue
                    and not background
                    and priority.lower() != "critical"
                    and timeout > 5  # Don't queue very short commands
                )

            # Parse priority
            priority_map = {
                "low": QueuePriority.LOW,
                "normal": QueuePriority.NORMAL,
                "high": QueuePriority.HIGH,
                "critical": QueuePriority.CRITICAL,
            }
            queue_priority = priority_map.get(priority.lower(), QueuePriority.NORMAL)

            # If using queue, enqueue the command
            if should_use_queue and self.queue_manager:
                self.ensure_queue_for_server(server)
                queue = self.queue_manager.get_queue(server)

                if queue:
                    command_id = await queue.enqueue_command(
                        self._execute_direct,
                        command,
                        server,
                        timeout,
                        stream_output,
                        start_time,
                        timestamp,
                        priority=queue_priority,
                        max_attempts=(1 if priority.lower() == "critical" else 3),
                    )

                    # For queued commands, wait for completion
                    while True:
                        status = await queue.get_command_status(command_id)
                        if status["status"] == "completed":
                            return status["result"]
                        elif status["status"] == "failed":
                            raise CommandExecutionError(
                                f"Queued command failed: {status['error']}"
                            )
                        await asyncio.sleep(0.1)  # Brief polling interval

            # Handle background execution (always direct, not queued)
            if background:
                return await self._execute_background(command, server, timeout)

            # Execute directly (bypass queue)
            return await self._execute_direct(
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
                    "execution_time_ms": execution_time,
                },
            )

    async def _execute_direct(
        self,
        command: str,
        server: str,
        timeout: int,
        stream_output: bool,
        start_time: float,
        timestamp: str,
    ) -> Dict[str, Any]:
        """Execute command directly without queueing.

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
        # Get server configuration for security validation
        server_pools = self.connection_manager.pools
        if server not in server_pools:
            raise CommandExecutionError(f"Server {server} not found")

        server_config = server_pools[server].server_config

        # Security validation
        validator = SecurityValidator(
            server_config.allowed_paths, server_config.blocked_commands
        )

        is_valid, error = validator.validate_command(command, 10000)
        if not is_valid:
            raise CommandSecurityError(error)

        # Execute the command using the original sync method
        return await self._execute_sync(
            command, server, timeout, stream_output, start_time, timestamp
        )

    async def _execute_sync(
        self,
        command: str,
        server: str,
        timeout: int,
        stream_output: bool,
        start_time: float,
        timestamp: str,
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
                raise CommandExecutionError(
                    f"No available connections for server {server}"
                )

            server_config = self.connection_manager.pools[server].server_config

            # Check if command needs sudo and handle securely
            validator = SecurityValidator(server_config.allowed_paths)
            needs_sudo = validator.check_sudo_requirements(
                command
            ) and not command.strip().startswith("sudo")

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
                        timeout=timeout,
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
                command=command,
            )

            # For failed commands, raise MCP exception instead of returning
            # error in response
            if result.returncode != 0:
                raise MCPCommandError(
                    message=f"Command exited with code {result.returncode}",
                    error_code="COMMAND_FAILED",
                    details={
                        "stdout": result.stdout or "",
                        "stderr": result.stderr or "",
                        "exit_code": result.returncode,
                        "command": command,
                        "server": server,
                    },
                )

            return result_data

        except asyncio.TimeoutError:
            execution_time = int((time.time() - start_time) * 1000)
            raise MCPCommandError(
                message=f"Command timed out after {timeout} seconds",
                error_code="COMMAND_TIMEOUT",
                details={
                    "timeout": timeout,
                    "server": server,
                    "command": command,
                },
            )

        except MCPCommandError:
            # Re-raise MCP exceptions
            raise

        except Exception as e:
            raise MCPCommandError(
                message=f"Command execution failed: {str(e)}",
                error_code="EXECUTION_ERROR",
                details={
                    "server": server,
                    "command": command,
                    "error": str(e),
                },
            )

        finally:
            if conn:
                await self.connection_manager.release_connection(server, conn)

    async def _execute_with_streaming(
        self, conn: SSHConnection, command: str, timeout: int
    ) -> Any:
        """Execute command with output streaming for long-running operations.

        Args:
            conn: SSH connection
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command result
        """

        # Use asyncssh process for streaming output
        try:
            # Start the process
            process = await conn.connection.create_process(command)

            # Collect output chunks for streaming
            stdout_chunks = []
            stderr_chunks = []

            # Stream stdout and stderr concurrently
            async def read_stdout():
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        break
                    stdout_chunks.append(chunk.decode("utf-8", errors="replace"))

            async def read_stderr():
                while True:
                    chunk = await process.stderr.read(1024)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

            # Run readers concurrently with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(read_stdout(), read_stderr()),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Kill the process if it times out
                process.kill()
                raise

            # Wait for process completion
            exit_code = await process.wait()

            # Combine output chunks
            stdout = "".join(stdout_chunks)
            stderr = "".join(stderr_chunks)

            # Create result object compatible with asyncssh.run
            class StreamResult:
                def __init__(self, stdout, stderr, returncode):
                    self.stdout = stdout
                    self.stderr = stderr
                    self.returncode = returncode

            return StreamResult(stdout, stderr, exit_code)

        except Exception as e:
            # Fallback to regular execution if streaming fails
            logger.warning(
                f"Streaming execution failed, falling back to regular execution: {e}"
            )
            return await asyncio.wait_for(
                conn.connection.run(command, check=False), timeout=timeout
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
        job.task = asyncio.create_task(self._background_job_runner(job, timeout))

        # Return MCP-compliant response for background job start
        return {
            "job_id": job_id,
            "command": command,
            "server": server,
            "status": "started",
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
                datetime.utcnow().isoformat() + "Z",
            )
            job.result = result
            job.status = "completed"

        except Exception as e:
            # Store MCP exception details for background jobs
            job.result = {
                "error": {
                    "code": type(e).__name__,
                    "message": str(e),
                    "details": getattr(e, "details", {}),
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
                details={"job_id": job_id},
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
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
                details={"job_id": job_id},
            )

        job = self.background_jobs[job_id]

        if job.task and not job.task.done():
            job.task.cancel()
            job.status = "cancelled"

        # Return MCP-compliant response for job cancellation
        return {
            "job_id": job_id,
            "status": job.status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
                jobs.append(
                    {
                        "job_id": job_id,
                        "command": job.command,
                        "server": job.server_name,
                        "status": job.status,
                        "start_time": job.start_time,
                    }
                )

        # Return MCP-compliant response for job list
        return {
            "jobs": jobs,
            "total_count": len(jobs),
            "server_filter": server,
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
            if (
                job.status in ["completed", "failed", "cancelled"]
                and job_age > max_age_seconds
            ):
                jobs_to_remove.append(job_id)

        for job_id in jobs_to_remove:
            del self.background_jobs[job_id]

        logger.info(f"Cleaned up {len(jobs_to_remove)} old background jobs")
        return len(jobs_to_remove)

    async def get_queue_status(self, server: Optional[str] = None) -> Dict[str, Any]:
        """Get status of command queues.

        Args:
            server: Specific server name (optional, gets all if None)

        Returns:
            Queue status information
        """
        if not self.queue_manager:
            return {"error": "Queue system not enabled"}

        if server:
            queue = self.queue_manager.get_queue(server)
            if not queue:
                return {"error": f"No queue found for server {server}"}
            return queue.get_metrics()
        else:
            return self.queue_manager.get_all_metrics()

    async def cleanup_queue_results(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """Clean up old queue results.

        Args:
            max_age_hours: Maximum age of results to keep

        Returns:
            Cleanup summary
        """
        if not self.queue_manager:
            return {"error": "Queue system not enabled"}

        cleaned = self.queue_manager.cleanup_all_old_results(max_age_hours)
        return {
            "cleaned_results": cleaned,
            "max_age_hours": max_age_hours,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    async def shutdown_queues(self) -> None:
        """Shutdown all command queues."""
        if self.queue_manager:
            await self.queue_manager.shutdown_all()
            logger.info("Command queues shutdown")
