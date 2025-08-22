# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP VPS Manager is a secure, production-ready Model Context Protocol (MCP) server that enables Large Language Models to safely manage Virtual Private Servers via SSH. The project provides comprehensive VPS management capabilities with built-in security controls, connection pooling, and audit logging.

## Development Commands

### Testing
```bash
# Run all tests
./run_tests.sh

# Run specific test suites
./run_tests.sh unit          # Unit tests only
./run_tests.sh integration   # Integration tests only
./run_tests.sh coverage      # Tests with coverage report
./run_tests.sh lint          # Linting and code quality checks
./run_tests.sh format        # Code formatting

# Run tests with Poetry
poetry run pytest

# Run specific test with verbose output
poetry run pytest tests/unit/test_security.py -v

# Run tests with coverage
poetry run pytest --cov=src/vps_manager --cov-report=html
```

### Code Quality
```bash
# Format code
make format
# Or with individual tools
poetry run black src/ tests/
poetry run isort src/ tests/

# Run linting
make lint
# Or with individual tools
poetry run flake8 src/ tests/
poetry run mypy src/

# Run all quality checks
make check
```

### Development Server
```bash
# Run development server with debug logging
make dev-server
# Or directly
python bin/mcp-vps-manager --config config/servers.yaml --log-level DEBUG

# Run with Poetry
poetry run mcp-vps-manager --config config/servers.yaml
```

### Package Management
```bash
# Install in development mode
make install-dev
# Or with Poetry
poetry install

# Build package
make build
# Or with Poetry
poetry build

# Clean build artifacts
make clean
```

## Architecture Overview

### Core Components

The project follows a layered architecture with clear separation of concerns:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Claude/LLM    │───▶│  MCP VPS Server  │───▶│  VPS Servers    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Security Layer  │
                    │  Connection Pool │
                    │  Command Queue   │
                    │  Audit Logging   │
                    └──────────────────┘
```

### Key Modules

1. **MCP Server Layer** (`src/vps_manager/server.py`)
   - Main MCP protocol handler and entry point
   - Coordinates all tool operations and server management

2. **Connection Management** (`src/vps_manager/connection_pool.py`)
   - SSH connection pooling with health checks
   - Automatic reconnection and exponential backoff
   - Per-server connection limits and monitoring

3. **Command Queue** (`src/vps_manager/queue.py`)
   - Priority-based command queuing system
   - Rate limiting and concurrency control per server
   - Real-time command streaming support

4. **Security Layer** (`src/vps_manager/security.py`)
   - Command validation against dangerous patterns
   - Path restrictions and access control
   - Input sanitization and validation

5. **Configuration** (`src/vps_manager/config.py`)
   - Pydantic-based configuration validation
   - Server definitions and security settings
   - Environment variable integration

### Tool Categories

**Command Execution** (`src/vps_manager/tools/command.py`)
- `exec_command`: Execute shell commands with streaming and queuing
- Priority-based execution (low/normal/high/critical)
- Real-time output streaming for long-running commands
- Comprehensive error handling and timeout management

**File Operations** (`src/vps_manager/tools/file_ops.py`)
- `read_file`: Read file contents with encoding support
- `write_file`: Write files with backup and directory creation
- `upload_file`: Upload files via SFTP with progress tracking
- `download_file`: Download files with integrity validation

**System Monitoring** (`src/vps_manager/tools/monitoring.py`)
- `get_system_status`: Comprehensive system metrics (CPU, memory, disk)
- Resource usage monitoring and threshold alerting
- System information gathering (uptime, OS version, kernel)

**Service Management** (`src/vps_manager/tools/services.py`)
- `service_control`: Control systemd/sysv/upstart services
- `list_services`: List and filter system services
- `get_service_logs`: Retrieve service logs with line limits
- Container-aware init system detection for Docker/Podman

**Queue Management**
- `get_queue_status`: Monitor command queue metrics
- `cleanup_queue_results`: Memory management for queue results

### Utility Components

**Distribution Detection** (`src/vps_manager/utils/distro.py`)
- Operating system and init system detection
- Container environment awareness (Docker/Podman)
- Enhanced systemd detection in containerized environments

**Error Handling** (`src/vps_manager/utils/error_handling.py`)
- Structured error responses with categories and severity levels
- MCP-compliant error formatting and user-friendly messages
- Comprehensive validation helpers

**Secure Operations** (`src/vps_manager/utils/secure_sudo.py`)
- Secure sudo password handling with in-memory storage
- Automatic cleanup and timeout management
- Security-first approach to privileged operations

## Configuration Structure

### Server Configuration (`config/servers.yaml`)
```yaml
servers:
  - name: server-identifier
    host: server-hostname-or-ip
    port: 22
    username: ssh-username
    ssh_key_path: ~/.ssh/private_key
    ssh_key_passphrase_env: SSH_KEY_PASS  # Optional
    allowed_paths:
      - /home/user
      - /var/www
      - /var/log
    blocked_commands:  # Additional patterns beyond defaults
      - shutdown
      - reboot
    max_file_size_mb: 50
    connection_timeout: 30
    command_timeout: 300
```

### Environment Variables
- `SSH_KEY_PASS`: SSH key passphrase (if needed)
- `SERVERS_CONFIG_PATH`: Path to servers.yaml
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARN, ERROR)
- `LOG_DIR`: Directory for log files

## Security Architecture

### Multi-layered Security
1. **SSH Key Authentication**: Only SSH key-based authentication supported
2. **Command Validation**: Blocks dangerous patterns (rm -rf /, fork bombs, etc.)
3. **Path Restrictions**: File access limited to configured allowed paths
4. **Input Sanitization**: All parameters validated and sanitized
5. **Audit Logging**: Comprehensive logging of all operations

### Security Best Practices Implemented
- Dedicated SSH keys for MCP operations
- Non-root user execution with selective sudo privileges
- Path traversal protection with absolute path validation
- Command pattern matching with regex-based blocking
- Connection rate limiting and timeout enforcement

## Testing Strategy

### Test Structure
```
tests/
├── unit/                    # Individual component tests
│   ├── test_security.py     # Security validation tests
│   ├── test_connection_pool.py  # Connection management tests
│   ├── test_config.py       # Configuration validation tests
│   └── test_tools.py        # Tool functionality tests
├── integration/             # End-to-end MCP tests
│   ├── test_mcp_server.py   # MCP protocol compliance
│   └── test_basic_functionality.py  # Core features
└── configs/                 # Test configurations
    └── test_multiple_servers.yaml
```

### Test Categories
- **Unit Tests**: Component isolation with mocking
- **Integration Tests**: MCP protocol and tool coordination
- **Validation Tests**: Real server testing with `validate_deployment.py`
- **Performance Tests**: Connection pool load testing
- **Security Tests**: Command blocking and path restriction validation

## New Features (v0.2.0)

### Real-time Command Streaming
- Live output streaming for long-running commands
- Configurable streaming modes and buffer management
- Stream timeout handling and cancellation support

### Priority-based Command Queuing
- Four priority levels: low, normal, high, critical
- Rate limiting and concurrency control per server
- Queue monitoring and metrics collection
- Memory management with automatic cleanup

### Container-aware Service Detection
- Enhanced init system detection for Docker/Podman environments
- Improved systemd service management in containers
- Container-specific service discovery patterns

## Common Development Patterns

### Adding New MCP Tools
1. Create tool class in appropriate `tools/` module
2. Implement MCP tool interface with proper validation
3. Add tool registration in `server.py`
4. Include comprehensive error handling
5. Add unit tests and integration tests

### Error Handling Pattern
```python
from utils.error_handling import ErrorHandler, ErrorCategory, ErrorSeverity

try:
    # Operation logic
    result = perform_operation()
    return format_success_response(result)
except Exception as e:
    return ErrorHandler.handle_error(
        e, ErrorCategory.OPERATION_FAILED, ErrorSeverity.HIGH
    )
```

### Connection Pool Usage
```python
async def tool_operation(self, server_name: str):
    async with self.connection_manager.get_connection(server_name) as conn:
        # Use connection for operations
        return await conn.run("command")
```

## Deployment Considerations

### Production Setup
- Use dedicated SSH keys with restricted permissions
- Configure appropriate `allowed_paths` for each server
- Set up log rotation for audit trails
- Monitor connection pool health and queue metrics
- Implement network security (VPN, firewall rules)

### Claude Desktop Integration
Add to Claude Desktop MCP configuration:
```json
{
  "mcpServers": {
    "mcp-vps-manager": {
      "command": "python",
      "args": ["-m", "vps_manager.server", "--config", "path/to/servers.yaml"],
      "env": {
        "SSH_KEY_PASS": "passphrase_if_needed"
      }
    }
  }
}
```

## Performance Optimization

### Connection Pool Tuning
- Adjust `max_connections_per_server` based on server capacity
- Configure `health_check_interval` for connection monitoring
- Set appropriate `connection_timeout` for network conditions

### Queue Configuration
- Configure rate limits based on server performance
- Set appropriate priority levels for different operation types
- Monitor queue metrics and adjust concurrency settings

### Memory Management
- Regular cleanup of queue results with `cleanup_queue_results`
- Monitor connection pool memory usage
- Configure appropriate log rotation policies
