"""File operations tools for MCP VPS Manager."""

import base64
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import asyncssh

from ..connection_pool import ConnectionManager
from ..security import PathSecurityError, SecurityValidator
from ..utils.mcp_responses import MCPFileError, MCPResponse

logger = logging.getLogger(__name__)


class FileOperationError(Exception):
    """File operation errors."""

    pass


class FileOperationsTool:
    """Tool for file operations on VPS servers via SFTP."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize file operations tool.

        Args:
            connection_manager: SSH connection manager
        """
        self.connection_manager = connection_manager
        self.max_chunk_size = 1024 * 1024  # 1MB chunks

    async def read_file(
        self,
        path: str,
        server: Optional[str] = None,
        encoding: str = "utf-8",
        max_size_mb: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Read a file from a VPS server.

        Args:
            path: File path to read
            server: Target server name
            encoding: Text encoding (default: utf-8)
            max_size_mb: Maximum file size limit

        Returns:
            File content and metadata
        """
        start_time = time.time()
        _ = datetime.utcnow().isoformat() + "Z"

        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise FileOperationError("No servers configured")
                server = servers[0]

            # Get server configuration
            if server not in self.connection_manager.pools:
                raise FileOperationError(f"Server {server} not found")

            server_config = self.connection_manager.pools[
                server
            ].server_config  # server_config unused

            # Security validation
            validator = SecurityValidator(server_config.allowed_paths)
            is_valid, error, resolved_path = validator.validate_file_path(path, "read")
            if not is_valid:
                raise PathSecurityError(error)

            # File size limit
            if max_size_mb is None:
                max_size_mb = server_config.max_file_size_mb

            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise FileOperationError(
                    f"No available connections for server {server}"
                )

            try:
                # Get file stats first
                sftp = await conn.connection.start_sftp_client()
                try:
                    stat_result = await sftp.stat(str(resolved_path))
                    file_size = stat_result.size

                    # Validate file size
                    is_size_valid, size_error = validator.validate_file_size(
                        file_size, max_size_mb
                    )
                    if not is_size_valid:
                        raise FileOperationError(size_error)

                    # Detect if file is binary
                    is_binary = await self._is_binary_file(sftp, resolved_path)

                    if is_binary:
                        # Read as binary and encode as base64
                        content = await sftp.readfile(str(resolved_path))
                        content_b64 = base64.b64encode(content).decode("ascii")

                        result_data = {
                            "content": content_b64,
                            "encoding": "base64",
                            "is_binary": True,
                            "size_bytes": file_size,
                            "path": str(resolved_path),
                        }
                    else:
                        # Read as text
                        try:
                            content_bytes = await sftp.readfile(str(resolved_path))
                            content_text = content_bytes.decode(encoding)

                            result_data = {
                                "content": content_text,
                                "encoding": encoding,
                                "is_binary": False,
                                "size_bytes": file_size,
                                "path": str(resolved_path),
                                "line_count": (
                                    content_text.count("\n") + 1 if content_text else 0
                                ),
                            }
                        except UnicodeDecodeError:
                            # Fallback to base64 if text decoding fails
                            content_b64 = base64.b64encode(content_bytes).decode(
                                "ascii"
                            )
                            result_data = {
                                "content": content_b64,
                                "encoding": "base64",
                                "is_binary": True,
                                "size_bytes": file_size,
                                "path": str(resolved_path),
                                "decode_error": f"Failed to decode as {encoding}",
                            }

                    execution_time = int((time.time() - start_time) * 1000)

                    # Return MCP-compliant response - data directly
                    return MCPResponse.file_read_result(
                        content=result_data.get("content", ""),
                        path=str(resolved_path),
                        size_bytes=result_data.get("size_bytes", 0),
                        encoding=result_data.get("encoding", encoding),
                        server=server,
                    )

                finally:
                    sftp.close()

            finally:
                await self.connection_manager.release_connection(server, conn)

        except (MCPFileError, PathSecurityError):
            # Re-raise MCP and security exceptions
            raise

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"File read failed: {e}")

            # Convert to MCP exception
            raise MCPFileError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "path": path,
                    "server": server or "unknown",
                    "execution_time_ms": execution_time,
                },
            )

    async def write_file(
        self,
        path: str,
        content: str,
        server: Optional[str] = None,
        encoding: str = "utf-8",
        create_dirs: bool = False,
        backup: bool = True,
    ) -> Dict[str, Any]:
        """Write content to a file on a VPS server.

        Args:
            path: File path to write
            content: Content to write
            server: Target server name
            encoding: Text encoding
            create_dirs: Create parent directories if they don't exist
            backup: Create backup of existing file

        Returns:
            Write operation result
        """
        start_time = time.time()
        _ = datetime.utcnow().isoformat() + "Z"

        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise FileOperationError("No servers configured")
                server = servers[0]

            # Get server configuration
            if server not in self.connection_manager.pools:
                raise FileOperationError(f"Server {server} not found")

            server_config = self.connection_manager.pools[
                server
            ].server_config  # server_config unused

            # Security validation
            validator = SecurityValidator(server_config.allowed_paths)
            is_valid, error, resolved_path = validator.validate_file_path(path, "write")
            if not is_valid:
                raise PathSecurityError(error)

            # Validate content size
            content_bytes = content.encode(encoding)
            _ = len(content_bytes) / (1024 * 1024)
            is_size_valid, size_error = validator.validate_file_size(
                len(content_bytes), server_config.max_file_size_mb
            )
            if not is_size_valid:
                raise FileOperationError(size_error)

            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise FileOperationError(
                    f"No available connections for server {server}"
                )

            try:
                sftp = await conn.connection.start_sftp_client()
                try:
                    # Create parent directories if requested
                    if create_dirs:
                        await self._ensure_parent_dirs(sftp, resolved_path)

                    # Create backup if file exists and backup is requested
                    backup_path = None
                    if backup:
                        try:
                            await sftp.stat(str(resolved_path))
                            # File exists, create backup
                            backup_path = f"{resolved_path}.bak"
                            await sftp.rename(str(resolved_path), backup_path)
                            logger.info(f"Created backup: {backup_path}")
                        except FileNotFoundError:
                            # File doesn't exist, no backup needed
                            pass

                    # Write content atomically (write to temp file, then
                    # rename)
                    temp_path = f"{resolved_path}.tmp"
                    try:
                        await sftp.writefile(temp_path, content_bytes)
                        await sftp.rename(temp_path, str(resolved_path))
                    except Exception as e:
                        # Clean up temp file on error
                        try:
                            await sftp.remove(temp_path)
                        except BaseException:
                            pass
                        raise e

                    # Get final file stats
                    final_stat = await sftp.stat(str(resolved_path))

                    execution_time = int((time.time() - start_time) * 1000)

                    # Return MCP-compliant response - data directly
                    created_dirs = []
                    return MCPResponse.file_write_result(
                        path=str(resolved_path),
                        size_bytes=final_stat.size,
                        backup_path=backup_path,
                        created_dirs=created_dirs if created_dirs else None,
                        server=server,
                    )

                finally:
                    sftp.close()

            finally:
                await self.connection_manager.release_connection(server, conn)

        except (MCPFileError, PathSecurityError):
            # Re-raise MCP and security exceptions
            raise

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"File write failed: {e}")

            # Convert to MCP exception
            raise MCPFileError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "path": path,
                    "server": server or "unknown",
                    "execution_time_ms": execution_time,
                },
            )

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        server: Optional[str] = None,
        create_dirs: bool = False,
    ) -> Dict[str, Any]:
        """Upload a file from local system to VPS server.

        Args:
            local_path: Local file path
            remote_path: Remote destination path
            server: Target server name
            create_dirs: Create parent directories if needed

        Returns:
            Upload operation result
        """
        start_time = time.time()
        _ = datetime.utcnow().isoformat() + "Z"

        try:
            # Validate local file exists
            local_file = Path(local_path)
            if not local_file.exists():
                raise FileOperationError(f"Local file not found: {local_path}")

            if not local_file.is_file():
                raise FileOperationError(f"Path is not a file: {local_path}")

            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise FileOperationError("No servers configured")
                server = servers[0]

            # Get server configuration
            if server not in self.connection_manager.pools:
                raise FileOperationError(f"Server {server} not found")

            server_config = self.connection_manager.pools[
                server
            ].server_config  # server_config unused

            # Security validation
            validator = SecurityValidator(server_config.allowed_paths)
            is_valid, error, resolved_path = validator.validate_file_path(
                remote_path, "write"
            )
            if not is_valid:
                raise PathSecurityError(error)

            # Validate file size
            file_size = local_file.stat().st_size
            is_size_valid, size_error = validator.validate_file_size(
                file_size, server_config.max_file_size_mb
            )
            if not is_size_valid:
                raise FileOperationError(size_error)

            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise FileOperationError(
                    f"No available connections for server {server}"
                )

            try:
                sftp = await conn.connection.start_sftp_client()
                try:
                    # Create parent directories if requested
                    if create_dirs:
                        await self._ensure_parent_dirs(sftp, resolved_path)

                    # Upload with progress tracking
                    await self._upload_with_progress(sftp, local_file, resolved_path)

                    # Verify upload
                    remote_stat = await sftp.stat(str(resolved_path))
                    if remote_stat.size != file_size:
                        raise FileOperationError(
                            "Upload verification failed: size mismatch"
                        )

                    execution_time = int((time.time() - start_time) * 1000)

                    # Return MCP-compliant response - data directly
                    return MCPResponse.file_transfer_result(
                        local_path=str(local_file),
                        remote_path=str(resolved_path),
                        size_bytes=file_size,
                        direction="upload",
                        server=server,
                    )

                finally:
                    sftp.close()

            finally:
                await self.connection_manager.release_connection(server, conn)

        except (MCPFileError, PathSecurityError):
            # Re-raise MCP and security exceptions
            raise

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"File upload failed: {e}")

            # Convert to MCP exception
            raise MCPFileError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "local_path": local_path,
                    "remote_path": remote_path,
                    "server": server or "unknown",
                    "execution_time_ms": execution_time,
                },
            )

    async def download_file(
        self, remote_path: str, local_path: str, server: Optional[str] = None
    ) -> Dict[str, Any]:
        """Download a file from VPS server to local system.

        Args:
            remote_path: Remote file path
            local_path: Local destination path
            server: Target server name

        Returns:
            Download operation result
        """
        start_time = time.time()
        _ = datetime.utcnow().isoformat() + "Z"

        try:
            # Determine target server
            if server is None:
                servers = self.connection_manager.list_servers()
                if not servers:
                    raise FileOperationError("No servers configured")
                server = servers[0]

            # Get server configuration
            if server not in self.connection_manager.pools:
                raise FileOperationError(f"Server {server} not found")

            server_config = self.connection_manager.pools[
                server
            ].server_config  # server_config unused

            # Security validation
            validator = SecurityValidator(server_config.allowed_paths)
            is_valid, error, resolved_path = validator.validate_file_path(
                remote_path, "read"
            )
            if not is_valid:
                raise PathSecurityError(error)

            # Validate local destination
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            conn = await self.connection_manager.get_connection(server)
            if not conn:
                raise FileOperationError(
                    f"No available connections for server {server}"
                )

            try:
                sftp = await conn.connection.start_sftp_client()
                try:
                    # Get remote file stats
                    remote_stat = await sftp.stat(str(resolved_path))
                    file_size = remote_stat.size

                    # Download with progress tracking
                    await self._download_with_progress(sftp, resolved_path, local_file)

                    # Verify download
                    local_stat = local_file.stat()
                    if local_stat.st_size != file_size:
                        raise FileOperationError(
                            "Download verification failed: size mismatch"
                        )

                    execution_time = int((time.time() - start_time) * 1000)

                    # Return MCP-compliant response - data directly
                    return MCPResponse.file_transfer_result(
                        local_path=str(local_file),
                        remote_path=str(resolved_path),
                        size_bytes=file_size,
                        direction="download",
                        server=server,
                    )

                finally:
                    sftp.close()

            finally:
                await self.connection_manager.release_connection(server, conn)

        except (MCPFileError, PathSecurityError):
            # Re-raise MCP and security exceptions
            raise

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"File download failed: {e}")

            # Convert to MCP exception
            raise MCPFileError(
                message=str(e),
                error_code=type(e).__name__.upper(),
                details={
                    "remote_path": remote_path,
                    "local_path": local_path,
                    "server": server or "unknown",
                    "execution_time_ms": execution_time,
                },
            )

    async def _is_binary_file(self, sftp: asyncssh.SFTPClient, file_path: Path) -> bool:
        """Check if a file is binary by reading the first few bytes.

        Args:
            sftp: SFTP client
            file_path: Path to check

        Returns:
            True if file appears to be binary
        """
        try:
            # Read first 1024 bytes
            with await sftp.open(str(file_path), "rb") as f:
                chunk = await f.read(1024)

            # Check for null bytes (common in binary files)
            if b"\x00" in chunk:
                return True

            # Check for high ratio of non-printable characters
            if chunk:
                printable_count = sum(
                    1 for b in chunk if 32 <= b <= 126 or b in [9, 10, 13]
                )
                ratio = printable_count / len(chunk)
                return ratio < 0.7

            return False

        except Exception:
            # If we can't determine, assume text
            return False

    async def _ensure_parent_dirs(
        self, sftp: asyncssh.SFTPClient, file_path: Path
    ) -> None:
        """Ensure parent directories exist.

        Args:
            sftp: SFTP client
            file_path: File path whose parent dirs to create
        """
        parent = file_path.parent
        if parent != file_path:  # Avoid infinite recursion
            try:
                await sftp.stat(str(parent))
            except FileNotFoundError:
                # Parent doesn't exist, create it recursively
                await self._ensure_parent_dirs(sftp, parent)
                await sftp.mkdir(str(parent))

    async def _upload_with_progress(
        self, sftp: asyncssh.SFTPClient, local_file: Path, remote_path: Path
    ) -> None:
        """Upload file with progress tracking.

        Args:
            sftp: SFTP client
            local_file: Local file to upload
            remote_path: Remote destination
        """
        # For now, use simple put. TODO: Add chunked upload with progress
        await sftp.put(str(local_file), str(remote_path))

    async def _download_with_progress(
        self, sftp: asyncssh.SFTPClient, remote_path: Path, local_file: Path
    ) -> None:
        """Download file with progress tracking.

        Args:
            sftp: SFTP client
            remote_path: Remote file to download
            local_file: Local destination
        """
        # For now, use simple get. TODO: Add chunked download with progress
        await sftp.get(str(remote_path), str(local_file))
