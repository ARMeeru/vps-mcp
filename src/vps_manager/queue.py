"""Command queue and rate limiting system for MCP VPS Manager."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class QueuePriority(Enum):
    """Command queue priorities."""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class QueuedCommand:
    """Represents a queued command with metadata."""

    command_id: str
    server_name: str
    command_func: Callable[..., Awaitable[Any]]
    args: tuple
    kwargs: dict
    priority: QueuePriority = QueuePriority.NORMAL
    queued_at: float = field(default_factory=time.time)
    attempts: int = 0
    max_attempts: int = 3

    def __post_init__(self):
        """Set priority sort key."""
        self.priority_value = self.priority.value


class RateLimiter:
    """Token bucket rate limiter for command execution."""

    def __init__(self, rate: int = 10, burst: int = 20):
        """Initialize rate limiter.

        Args:
            rate: Commands per second
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire permission to execute a command."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update

            # Add tokens based on elapsed time
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            # Wait if no tokens available
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class CommandQueue:
    """Command queue with rate limiting and concurrency control."""

    def __init__(self, server_name: str, max_concurrent: int = 5, rate_limit: int = 10):
        """Initialize command queue for a server.

        Args:
            server_name: Server name this queue handles
            max_concurrent: Maximum concurrent commands
            rate_limit: Commands per second limit
        """
        self.server_name = server_name
        self.max_concurrent = max_concurrent
        self.rate_limiter = RateLimiter(rate_limit, rate_limit * 2)

        # Queue and execution tracking
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.executing: Dict[str, asyncio.Task] = {}
        self.completed: Dict[str, Any] = {}
        self.failed: Dict[str, Exception] = {}

        # Concurrency control
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._command_counter = 0
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Metrics
        self.metrics = {
            "total_queued": 0,
            "total_executed": 0,
            "total_failed": 0,
            "current_queue_size": 0,
            "current_executing": 0,
        }

        logger.info(
            f"Command queue initialized for {server_name} "
            f"(max_concurrent={max_concurrent}, rate_limit={rate_limit}/s)"
        )

    def start_worker(self) -> None:
        """Start the queue worker task."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info(f"Queue worker started for {self.server_name}")

    async def stop_worker(self) -> None:
        """Stop the queue worker task."""
        self._shutdown = True

        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        # Wait for executing commands to complete
        if self.executing:
            logger.info(
                f"Waiting for {len(self.executing)} executing commands to complete..."
            )
            await asyncio.gather(*self.executing.values(), return_exceptions=True)

        logger.info(f"Queue worker stopped for {self.server_name}")

    async def enqueue_command(
        self,
        command_func: Callable[..., Awaitable[Any]],
        *args,
        priority: QueuePriority = QueuePriority.NORMAL,
        max_attempts: int = 3,
        **kwargs,
    ) -> str:
        """Enqueue a command for execution.

        Args:
            command_func: Async function to execute
            *args: Positional arguments for the function
            priority: Command priority
            max_attempts: Maximum retry attempts
            **kwargs: Keyword arguments for the function

        Returns:
            Command ID for tracking
        """
        if self._shutdown:
            raise RuntimeError(f"Queue for {self.server_name} is shutting down")

        # Generate command ID
        self._command_counter += 1
        command_id = f"{self.server_name}-cmd-{self._command_counter}"

        # Create queued command
        queued_cmd = QueuedCommand(
            command_id=command_id,
            server_name=self.server_name,
            command_func=command_func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_attempts=max_attempts,
        )

        # Queue with priority (negative value for max-heap behavior)
        await self.queue.put((-priority.value, time.time(), queued_cmd))

        self.metrics["total_queued"] += 1
        self.metrics["current_queue_size"] = self.queue.qsize()

        logger.debug(f"Queued command {command_id} with priority {priority.name}")
        return command_id

    async def get_command_status(self, command_id: str) -> Dict[str, Any]:
        """Get the status of a command.

        Args:
            command_id: Command ID to check

        Returns:
            Command status dictionary
        """
        if command_id in self.executing:
            return {
                "status": "executing",
                "command_id": command_id,
                "server": self.server_name,
            }
        elif command_id in self.completed:
            return {
                "status": "completed",
                "command_id": command_id,
                "server": self.server_name,
                "result": self.completed[command_id],
            }
        elif command_id in self.failed:
            return {
                "status": "failed",
                "command_id": command_id,
                "server": self.server_name,
                "error": str(self.failed[command_id]),
            }
        else:
            return {
                "status": "queued",
                "command_id": command_id,
                "server": self.server_name,
                "queue_position": self._get_queue_position(command_id),
            }

    def _get_queue_position(self, command_id: str) -> int:
        """Get approximate position of command in queue."""
        # This is an approximation since PriorityQueue doesn't expose internals
        return self.queue.qsize()

    async def _worker_loop(self) -> None:
        """Main worker loop that processes queued commands."""
        logger.info(f"Queue worker loop started for {self.server_name}")

        while not self._shutdown:
            try:
                # Get next command with timeout
                try:
                    _, _, queued_cmd = await asyncio.wait_for(
                        self.queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Update metrics
                self.metrics["current_queue_size"] = self.queue.qsize()

                # Execute command
                await self._execute_command(queued_cmd)

            except Exception as e:
                logger.error(f"Error in queue worker for {self.server_name}: {e}")
                await asyncio.sleep(1)  # Brief pause on error

    async def _execute_command(self, queued_cmd: QueuedCommand) -> None:
        """Execute a single queued command.

        Args:
            queued_cmd: Command to execute
        """
        command_id = queued_cmd.command_id

        try:
            # Wait for concurrency slot and rate limit
            async with self.semaphore:
                await self.rate_limiter.acquire()

                # Track execution
                task = asyncio.create_task(self._run_command_with_retry(queued_cmd))
                self.executing[command_id] = task
                self.metrics["current_executing"] = len(self.executing)

                logger.debug(f"Executing command {command_id}")

                try:
                    result = await task
                    self.completed[command_id] = result
                    self.metrics["total_executed"] += 1
                    logger.debug(f"Command {command_id} completed successfully")

                except Exception as e:
                    self.failed[command_id] = e
                    self.metrics["total_failed"] += 1
                    logger.error(f"Command {command_id} failed: {e}")

                finally:
                    # Clean up tracking
                    if command_id in self.executing:
                        del self.executing[command_id]
                    self.metrics["current_executing"] = len(self.executing)

        except Exception as e:
            logger.error(f"Error executing command {command_id}: {e}")
            self.failed[command_id] = e
            self.metrics["total_failed"] += 1

    async def _run_command_with_retry(self, queued_cmd: QueuedCommand) -> Any:
        """Run command with retry logic.

        Args:
            queued_cmd: Command to execute

        Returns:
            Command result
        """
        last_exception = None

        for attempt in range(queued_cmd.max_attempts):
            try:
                queued_cmd.attempts = attempt + 1
                result = await queued_cmd.command_func(
                    *queued_cmd.args, **queued_cmd.kwargs
                )
                return result

            except Exception as e:
                last_exception = e
                if attempt < queued_cmd.max_attempts - 1:
                    wait_time = min(2**attempt, 30)  # Exponential backoff, max 30s
                    logger.warning(
                        f"Command {queued_cmd.command_id} attempt "
                        f"{attempt + 1} failed, retrying in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"Command {
                            queued_cmd.command_id} failed after {
                            queued_cmd.max_attempts} attempts: {e}"
                    )

        raise last_exception

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics and statistics.

        Returns:
            Metrics dictionary
        """
        return {
            **self.metrics,
            "server_name": self.server_name,
            "max_concurrent": self.max_concurrent,
            "rate_limit": self.rate_limiter.rate,
            "available_tokens": self.rate_limiter.tokens,
            "completed_commands": len(self.completed),
            "failed_commands": len(self.failed),
        }

    def cleanup_old_results(self, max_age_hours: int = 24) -> int:
        """Clean up old command results.

        Args:
            max_age_hours: Maximum age of results to keep

        Returns:
            Number of results cleaned up
        """
        # cutoff_time = time.time() - (max_age_hours * 3600)  # TODO: Use for
        # time-based cleanup
        cleaned = 0

        # Clean completed results (we'd need to track completion time for this)
        # For now, just limit the size of completed/failed dicts
        max_results = 1000

        if len(self.completed) > max_results:
            # Remove oldest half
            items_to_remove = len(self.completed) - (max_results // 2)
            keys_to_remove = list(self.completed.keys())[:items_to_remove]
            for key in keys_to_remove:
                del self.completed[key]
                cleaned += 1

        if len(self.failed) > max_results:
            items_to_remove = len(self.failed) - (max_results // 2)
            keys_to_remove = list(self.failed.keys())[:items_to_remove]
            for key in keys_to_remove:
                del self.failed[key]
                cleaned += 1

        if cleaned > 0:
            logger.info(
                f"Cleaned up {cleaned} old command results for {
                    self.server_name}"
            )

        return cleaned


class QueueManager:
    """Manages command queues for multiple servers."""

    def __init__(self):
        """Initialize the queue manager."""
        self.queues: Dict[str, CommandQueue] = {}
        self._default_max_concurrent = 5
        self._default_rate_limit = 10

    def create_queue(
        self,
        server_name: str,
        max_concurrent: int = None,
        rate_limit: int = None,
    ) -> CommandQueue:
        """Create a command queue for a server.

        Args:
            server_name: Server name
            max_concurrent: Maximum concurrent commands (optional)
            rate_limit: Commands per second limit (optional)

        Returns:
            Command queue instance
        """
        if server_name in self.queues:
            logger.warning(f"Queue for {server_name} already exists, replacing")
            asyncio.create_task(self.queues[server_name].stop_worker())

        max_concurrent = max_concurrent or self._default_max_concurrent
        rate_limit = rate_limit or self._default_rate_limit

        queue = CommandQueue(server_name, max_concurrent, rate_limit)
        queue.start_worker()
        self.queues[server_name] = queue

        logger.info(f"Created queue for server {server_name}")
        return queue

    def get_queue(self, server_name: str) -> Optional[CommandQueue]:
        """Get the command queue for a server.

        Args:
            server_name: Server name

        Returns:
            Command queue if exists, None otherwise
        """
        return self.queues.get(server_name)

    async def remove_queue(self, server_name: str) -> None:
        """Remove and shutdown a command queue.

        Args:
            server_name: Server name
        """
        if server_name in self.queues:
            await self.queues[server_name].stop_worker()
            del self.queues[server_name]
            logger.info(f"Removed queue for server {server_name}")

    async def shutdown_all(self) -> None:
        """Shutdown all command queues."""
        for server_name in list(self.queues.keys()):
            await self.remove_queue(server_name)

        logger.info("All command queues shutdown")

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all queues.

        Returns:
            Dictionary mapping server names to their metrics
        """
        return {
            server_name: queue.get_metrics()
            for server_name, queue in self.queues.items()
        }

    def cleanup_all_old_results(self, max_age_hours: int = 24) -> int:
        """Clean up old results from all queues.

        Args:
            max_age_hours: Maximum age of results to keep

        Returns:
            Total number of results cleaned up
        """
        total_cleaned = 0
        for queue in self.queues.values():
            total_cleaned += queue.cleanup_old_results(max_age_hours)

        return total_cleaned
