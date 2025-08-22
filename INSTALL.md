# MCP VPS Manager Installation Guide

A secure, production-ready MCP (Model Context Protocol) server for managing Virtual Private Servers via SSH. This tool allows Claude Desktop and other MCP-compatible AI assistants to safely execute commands, manage files, and monitor your VPS infrastructure.

## Prerequisites

- Python 3.8 or higher
- SSH access to your VPS(es)
- Claude Desktop or another MCP-compatible client

## Quick Installation

### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/your-org/mcp-vps-manager.git
cd mcp-vps-manager

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Your Servers

1. Copy the template configuration:
   ```bash
   cp templates/servers.yaml config/servers.yaml
   ```

2. Edit `config/servers.yaml` with your server details:
   ```yaml
   servers:
     my-server:
       host: "your-server-ip"
       username: "your-username"
       ssh_key_path: "~/.ssh/id_rsa"
   ```

### Step 3: Setup SSH Keys (Recommended)

For security, use SSH key authentication:

```bash
# Generate a new SSH key (if you don't have one)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/vps_manager_key

# Copy public key to your server
ssh-copy-id -i ~/.ssh/vps_manager_key.pub username@your-server-ip
```

### Step 4: Test the Connection

```bash
# Test the MCP server
python bin/mcp-vps-manager --config config/servers.yaml --log-level DEBUG
```

If successful, you'll see: "MCP VPS Manager server started successfully"

### Step 5: Configure Claude Desktop

1. **Find your Claude Desktop config file:**
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

2. **Add the VPS Manager configuration:**
   ```json
   {
     "mcpServers": {
       "vps-manager": {
         "command": "python",
         "args": [
           "/full/path/to/mcp-vps-manager/bin/mcp-vps-manager",
           "--config",
           "/full/path/to/mcp-vps-manager/config/servers.yaml"
         ],
         "env": {
           "PYTHONPATH": "/full/path/to/mcp-vps-manager/src"
         }
       }
     }
   }
   ```

3. **Restart Claude Desktop**

### Step 6: Verify Integration

Open Claude Desktop and try asking:
- "What servers do you have access to?"
- "Check the disk space on my server"
- "List the files in /home"

## Configuration Options

### Server Configuration

```yaml
servers:
  production-web:
    host: "web.example.com"
    port: 22                    # SSH port (default: 22)
    username: "deploy"
    ssh_key_path: "~/.ssh/web_key"
    connection_timeout: 30      # Connection timeout in seconds
    keepalive_interval: 60      # Keep-alive interval

    # Server-specific security settings
    allowed_directories:
      - "/home/deploy"
      - "/var/www"
      - "/var/log"
```

### Security Settings

```yaml
vps_manager:
  security:
    allowed_directories:        # Directories accessible for file operations
      - "/home"
      - "/var/log"
      - "/etc"
    enable_command_validation: true  # Validate commands for safety
    log_all_commands: true          # Log all executed commands
```

### Connection Pool Settings

```yaml
vps_manager:
  connection_pool:
    max_connections_per_server: 3    # Max concurrent connections
    connection_timeout: 30           # Connection timeout
    health_check_interval: 300       # Health check frequency (seconds)
    reconnect_attempts: 3            # Retry attempts for failed connections
```

## Security Best Practices

1. **Use SSH Keys**: Never use password authentication in production
2. **Limit Directories**: Only allow access to necessary directories
3. **Monitor Logs**: Review command logs regularly
4. **Separate Keys**: Use dedicated SSH keys for the VPS manager
5. **Network Security**: Use VPN or firewall rules to restrict SSH access

## Available MCP Tools

Once configured, Claude Desktop will have access to these tools:

### Core Command Execution
- **exec_command**: Execute shell commands safely with real-time streaming and queuing support
  - Real-time output streaming for long-running commands
  - Priority-based command queuing (low/normal/high/critical)
  - Rate limiting and concurrency control per server

### File Operations
- **read_file**: Read file contents from servers
- **write_file**: Write or modify files with backup support
- **upload_file**: Upload files from local to remote servers
- **download_file**: Download files from remote to local

### System Management
- **get_system_status**: Get comprehensive system metrics and resource usage
- **service_control**: Control system services (start/stop/restart/status)
- **list_services**: List and filter system services
- **get_service_logs**: Retrieve service logs

### Queue Management (New!)
- **get_queue_status**: Monitor command queue status and metrics across servers
- **cleanup_queue_results**: Clean up old command results to free memory

### Enhanced Features
- **Container Support**: Enhanced detection for Docker/Podman environments
- **Auto-Recovery**: Automatic reconnection and health monitoring
- **Security Validation**: Comprehensive command and path validation

## Troubleshooting

### Common Issues

**"SSH Authentication Failed"**
- Verify SSH key path and permissions (should be 600)
- Test manual SSH connection: `ssh -i ~/.ssh/your_key user@server`
- Ensure public key is in server's `~/.ssh/authorized_keys`

**"Module Not Found"**
- Check PYTHONPATH in Claude Desktop config
- Verify virtual environment is activated during testing

**"Permission Denied"**
- Check file permissions on SSH keys and config files
- Verify user has necessary permissions on the server

**"Connection Timeout"**
- Check firewall settings and SSH port
- Verify server is accessible from your network

### Debug Mode

Enable detailed logging:
```bash
python bin/mcp-vps-manager --config config/servers.yaml --log-level DEBUG
```

### Log Files

Monitor logs for issues:
- Application logs: `/tmp/vps-manager.log`
- SSH connection logs: Check system logs on your servers

## Support

For issues and feature requests, please visit:
- GitHub Issues: [Create an issue](https://github.com/your-org/mcp-vps-manager/issues)
- Documentation: [Full documentation](https://github.com/your-org/mcp-vps-manager/wiki)

## License

MIT License - see LICENSE file for details.
