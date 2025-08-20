# MCP VPS Manager

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-v1.0.0-green.svg)](https://modelcontextprotocol.io/)

**MCP VPS Manager** is a secure, production-ready Model Context Protocol (MCP) server that enables Large Language Models to safely manage Virtual Private Servers via SSH. This tool provides comprehensive VPS management capabilities with built-in security controls, connection pooling, and comprehensive audit logging.

## Features

### 🔧 **Core Functionality**
- **SSH Command Execution**: Execute shell commands with security validation
- **File Operations**: Upload, download, read, and write files via SFTP
- **System Monitoring**: Real-time system metrics (CPU, memory, disk, processes)
- **Service Management**: Control systemd, upstart, and SysV init services
- **Multi-Server Support**: Manage multiple VPS servers from a single interface

### 🔒 **Security Features**
- **Command Validation**: Blocks dangerous commands (rm -rf /, fork bombs, etc.)
- **Path Restrictions**: Restricts file access to configured allowed paths
- **SSH Key Authentication**: Only supports SSH key-based authentication
- **Sudo Password Management**: Secure in-memory sudo password handling
- **Audit Logging**: Comprehensive logging of all operations

### ⚡ **Performance & Reliability**
- **Connection Pooling**: Maintains multiple SSH connections per server
- **Auto-Reconnection**: Automatic reconnection with exponential backoff
- **Health Monitoring**: Continuous connection health checks
- **Async Operations**: Full async/await support for better performance

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- SSH access to your VPS
- Claude Desktop or MCP-compatible client

### Installation & Setup
```bash
# 1. Clone and install
git clone https://github.com/your-org/mcp-vps-manager.git
cd mcp-vps-manager
pip install -r requirements.txt

# 2. Configure your servers
cp templates/servers.yaml config/servers.yaml
# Edit config/servers.yaml with your server details

# 3. Add to Claude Desktop config
# See Configuration section for details

# 4. Test the connection
python bin/mcp-vps-manager --config config/servers.yaml --log-level DEBUG
```

### First Commands
Ask Claude Desktop:
- "What servers do you have access to?"
- "Check the system status of my server"
- "List the files in /home"

## Installation

### Prerequisites
- Python 3.9+
- Poetry (for dependency management)
- SSH access to target VPS servers
- SSH keys configured for passwordless authentication

### Install with Poetry

```bash
# Clone the repository
git clone <repository-url>
cd mcp-vps-manager

# Install dependencies
poetry install

# Activate the virtual environment
poetry shell
```

### Install with pip

```bash
pip install mcp-vps-manager
```

## Configuration

### 1. Server Configuration

Copy the example configuration file and customize it:

```bash
cp config/servers.yaml.example config/servers.yaml
```

Edit `config/servers.yaml`:

```yaml
servers:
  - name: production-web
    host: 192.168.1.10
    port: 22
    username: admin
    ssh_key_path: ~/.ssh/id_rsa
    ssh_key_passphrase_env: SSH_KEY_PASS  # Optional
    allowed_paths:
      - /home/admin
      - /var/www
      - /etc/nginx
    blocked_commands:  # Additional patterns beyond defaults
      - shutdown
      - reboot
    max_file_size_mb: 50
    connection_timeout: 30
    command_timeout: 300

  - name: staging-db
    host: staging.example.com
    port: 2222
    username: dbadmin
    ssh_key_path: ~/.ssh/staging_key
    allowed_paths:
      - /home/dbadmin
      - /var/lib/mysql
      - /etc/mysql
    max_file_size_mb: 100
```

### 2. Environment Variables

Create a `.env` file (optional):

```bash
cp .env.example .env
```

Configure environment variables:

```bash
# SSH Key Passphrases (if needed)
SSH_KEY_PASS=your_ssh_key_passphrase_here

# Server Configuration
SERVERS_CONFIG_PATH=./config/servers.yaml

# Logging Configuration
LOG_LEVEL=INFO
LOG_DIR=./logs

# Connection Pool Settings
MAX_CONNECTIONS_PER_SERVER=3
HEALTH_CHECK_INTERVAL=30
```

### 3. Claude Desktop Integration

Add to your Claude Desktop MCP configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mcp-vps-manager": {
      "command": "python",
      "args": ["-m", "vps_manager.server", "--config", "path/to/config/servers.yaml"],
      "env": {
        "SSH_KEY_PASS": "your_passphrase_if_needed"
      }
    }
  }
}
```

## Usage

### Starting the Server

```bash
# Using Poetry
poetry run mcp-vps-manager --config config/servers.yaml

# Using Python module
python -m vps_manager.server --config config/servers.yaml --log-level DEBUG
```

### Available MCP Tools

#### 1. **exec_command**
Execute shell commands on VPS servers.

```json
{
  "command": "ls -la /var/www",
  "server": "production-web",
  "timeout": 30,
  "background": false
}
```

#### 2. **read_file**
Read file contents from VPS servers.

```json
{
  "path": "/var/www/index.html",
  "server": "production-web",
  "encoding": "utf-8"
}
```

#### 3. **write_file**
Write content to files on VPS servers.

```json
{
  "path": "/var/www/new-page.html",
  "content": "<html><body>Hello World</body></html>",
  "server": "production-web",
  "create_dirs": true,
  "backup": true
}
```

#### 4. **upload_file**
Upload files from local system to VPS.

```json
{
  "local_path": "/local/file.txt",
  "remote_path": "/var/www/file.txt",
  "server": "production-web",
  "create_dirs": false
}
```

#### 5. **download_file**
Download files from VPS to local system.

```json
{
  "remote_path": "/var/log/app.log",
  "local_path": "/local/downloads/app.log",
  "server": "production-web"
}
```

#### 6. **get_system_status**
Get comprehensive system metrics.

```json
{
  "server": "production-web",
  "detailed": true
}
```

#### 7. **service_control**
Control system services.

```json
{
  "service_name": "nginx",
  "action": "restart",
  "server": "production-web",
  "force": false
}
```

#### 8. **list_services**
List system services.

```json
{
  "server": "production-web",
  "running_only": false,
  "pattern": "nginx.*"
}
```

#### 9. **get_service_logs**
Retrieve service logs.

```json
{
  "service_name": "nginx",
  "server": "production-web",
  "lines": 100
}
```

### Example Conversations with Claude

**"Check the system status of my web server"**
```
Using get_system_status tool on production-web server...

System Status:
- CPU Usage: 15.3% (4 cores)
- Memory: 3.2GB used / 8GB total (40%)
- Disk: 45GB used / 100GB total (45%)
- Load Average: 0.8, 0.6, 0.5
- Uptime: 15 days, 6 hours
```

**"Restart nginx and check if it's running"**
```
1. Using service_control to restart nginx...
   ✓ Nginx restarted successfully

2. Using service_control to check status...
   ✓ Nginx is active and running

3. Using exec_command to verify web server response...
   ✓ Web server responding on port 80
```

## Security Best Practices

### 1. **SSH Key Management**
- Use dedicated SSH keys for MCP VPS Manager
- Store SSH key passphrases in environment variables
- Regularly rotate SSH keys
- Use Ed25519 keys when possible

### 2. **Path Restrictions**
- Limit `allowed_paths` to only necessary directories
- Avoid allowing access to system directories (`/etc`, `/boot`, `/sys`)
- Use absolute paths only

### 3. **Command Blocking**
- Review and customize `blocked_commands` for each server
- Test dangerous command blocking before production use
- Consider additional patterns specific to your environment

### 4. **Network Security**
- Use non-standard SSH ports when possible
- Implement SSH connection rate limiting
- Use VPN or private networks when available

### 5. **Audit and Monitoring**
- Enable audit logging in production
- Regularly review audit logs
- Monitor for unusual command patterns
- Set up alerts for security events

## Troubleshooting

### Common Issues

#### 1. **SSH Connection Failures**
```
Error: Failed to connect test-server-1: [Errno 111] Connection refused
```
**Solutions:**
- Verify SSH service is running: `systemctl status sshd`
- Check firewall settings: `ufw status` or `iptables -L`
- Validate SSH key path and permissions
- Test manual SSH connection: `ssh -i ~/.ssh/key user@host`

#### 2. **Permission Denied Errors**
```
Error: Command matches dangerous pattern: sudo\s+passwd
```
**Solutions:**
- Review blocked command patterns in security module
- Add exceptions to server configuration if needed
- Use `force=true` for administrative tasks (carefully)
- Check if command requires different permissions

#### 3. **Path Access Denied**
```
Error: Path not in allowed directories: /etc/passwd
```
**Solutions:**
- Add required paths to `allowed_paths` in server configuration
- Use relative paths within allowed directories
- Check for typos in path specifications
- Verify directory exists and is accessible

#### 4. **File Size Limits**
```
Error: File size 104857600 exceeds limit of 50MB
```
**Solutions:**
- Increase `max_file_size_mb` in server configuration
- Use chunked transfer for large files
- Consider compression before transfer
- Split large files into smaller parts

### Debug Mode

Run with debug logging to troubleshoot issues:

```bash
python -m vps_manager.server --config config/servers.yaml --log-level DEBUG
```

Check logs in the configured log directory:
- `debug.log`: Detailed operation logs
- `error.log`: Error messages and stack traces
- `audit.log`: Command execution audit trail

### Health Checks

Monitor connection pool health:

```bash
# The server exposes connection status via MCP resources
# Access vps://server-name resource in Claude to see connection status
```

## Development

### Setting up Development Environment

```bash
# Clone repository
git clone <repository-url>
cd mcp-vps-manager

# Install development dependencies
poetry install --with dev

# Run tests
poetry run pytest

# Run type checking
poetry run mypy src/

# Format code
poetry run black src/ tests/
poetry run isort src/ tests/

# Lint code
poetry run flake8 src/ tests/
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src/vps_manager

# Run specific test file
poetry run pytest tests/unit/test_security.py

# Run integration tests (requires test environment)
poetry run pytest tests/integration/
```

### Testing with Virtual Servers

For development and testing, you can use virtual machines or cloud instances with test configurations:

```bash
# Set up a test server with SSH access
# Create dedicated test user and SSH keys
ssh-keygen -t rsa -b 4096 -f ~/.ssh/test_key -C "test@example.com"

# Configure test server in servers.yaml
# Use appropriate port and credentials for your test environment
```

## Architecture

### Component Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Claude/LLM    │───▶│  MCP VPS Server  │───▶│  VPS Servers    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Security Layer  │
                    │  Connection Pool │
                    │  Audit Logging   │
                    └──────────────────┘
```

### Key Components

1. **MCP Server** (`server.py`): Main MCP protocol handler
2. **Connection Pool** (`connection_pool.py`): SSH connection management
3. **Security Validator** (`security.py`): Command and path validation
4. **Tools**: Individual operation handlers
   - Command execution (`tools/command.py`)
   - File operations (`tools/file_ops.py`)
   - System monitoring (`tools/monitoring.py`)
   - Service management (`tools/services.py`)

## Changelog

### v0.1.0 (Initial Release)
- MCP protocol implementation
- SSH connection pooling
- Security validation system
- File operations via SFTP
- System monitoring tools
- Service management
- Comprehensive test suite
- Documentation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- **GitHub Issues**: Report bugs and request features
- **Documentation**: This README and inline code documentation
- **Security Issues**: Report privately via email

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Support](#support)

## 🔗 Related Projects

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) - MCP Python implementation
- [Claude Desktop](https://claude.ai/desktop) - MCP client with desktop app
- [Other MCP Servers](https://github.com/modelcontextprotocol/servers) - Community MCP servers

## 📚 Additional Resources

- **[INSTALL.md](INSTALL.md)** - Detailed installation guide
- **[SECURITY.md](SECURITY.md)** - Comprehensive security guide and best practices
- **[Templates](templates/)** - Configuration templates
- **[Examples](examples/)** - Usage examples and integrations

## 🏷️ Version History

### v0.1.0 (Current)
- ✅ MCP protocol implementation
- ✅ SSH connection pooling with health checks
- ✅ Comprehensive security validation
- ✅ File operations via SFTP
- ✅ System monitoring and metrics
- ✅ Service management (systemd/sysv/upstart)
- ✅ Enhanced error handling and user feedback
- ✅ Production packaging and deployment
- ✅ Complete test suite
- ✅ Documentation and security guides

### Roadmap
- 🔄 Web UI for server management
- 🔄 Metrics dashboard
- 🔄 Multi-factor authentication support
- 🔄 Container management integration
- 🔄 Backup and restoration tools

## 🙏 Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- [AsyncSSH](https://github.com/ronf/asyncssh) for robust SSH connectivity
- [Pydantic](https://github.com/pydantic/pydantic) for configuration validation
- [Claude Desktop](https://claude.ai/desktop) for MCP client support
- The open source community for inspiration and contributions

---

**Made with ❤️ for the MCP community**

*Securely manage your VPS infrastructure with AI assistance*
