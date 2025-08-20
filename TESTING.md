# Testing Guide for MCP VPS Manager

This guide provides comprehensive instructions for testing the MCP VPS Manager with multiple VPS providers and configurations.

## Testing Overview

The testing suite includes:

1. **Unit Tests** - Individual component testing
2. **Integration Tests** - MCP protocol and tool integration
3. **Validation Tests** - Real-world VPS provider testing
4. **Local Testing** - Local testing with virtual machines or test servers

## Quick Start Testing

### 1. Unit and Integration Tests

```bash
# Run all tests
./run_tests.sh

# Run specific test suites
./run_tests.sh unit
./run_tests.sh integration
./run_tests.sh coverage
```

### 2. Local Test Environment

```bash
# Setup local test environment
# Configure test servers or VMs with SSH access
# Update test configuration with appropriate server details

# Run validation against test servers
python validate_deployment.py --config tests/configs/test_multiple_servers.yaml
```

### 3. Real VPS Testing

```bash
# Create your test configuration
cp tests/configs/test_multiple_servers.yaml my_test_config.yaml
# Edit my_test_config.yaml with your server details

# Run validation
python validate_deployment.py --config my_test_config.yaml
```

## Detailed Testing Instructions

### Unit Tests

Unit tests validate individual components:

```bash
# Test security validation
pytest tests/unit/test_security.py -v

# Test connection pooling
pytest tests/unit/test_connection_pool.py -v

# Test configuration loading
pytest tests/unit/test_config.py -v

# Test MCP tools
pytest tests/unit/test_tools.py -v
```

### Integration Tests

Integration tests validate the complete MCP server:

```bash
# Test MCP protocol compliance
pytest tests/integration/test_mcp_server.py -v

# Test basic functionality
pytest tests/integration/test_basic_functionality.py -v
```

### VPS Provider Testing

Test with real VPS providers to ensure compatibility:

#### Supported Providers

- **DigitalOcean** (Ubuntu, Debian, CentOS)
- **AWS EC2** (Amazon Linux, Ubuntu)
- **Linode** (Ubuntu, CentOS, Debian)
- **Vultr** (Ubuntu, CentOS, Debian)
- **Hetzner** (Ubuntu, Debian)
- **Google Cloud Platform** (Ubuntu, Debian)

#### Test Configuration

1. **Create test configuration:**
   ```bash
   cp tests/configs/test_multiple_servers.yaml your_provider_test.yaml
   ```

2. **Edit configuration with your servers:**
   ```yaml
   servers:
     digitalocean-ubuntu:
       host: "your-do-server.com"
       username: "root"
       ssh_key_path: "~/.ssh/do_key"

     aws-ec2-amazon:
       host: "ec2-xx-xx-xx-xx.compute-1.amazonaws.com"
       username: "ec2-user"
       ssh_key_path: "~/.ssh/aws_key.pem"
   ```

3. **Run validation:**
   ```bash
   python validate_deployment.py --config your_provider_test.yaml --verbose
   ```

### Local Test Environment

For local testing without production VPS servers:

#### Setup

```bash
# Option 1: Use local virtual machines
# Set up VMs with SSH access and configure test users

# Option 2: Use cloud instances for testing
# Create small/cheap cloud instances for testing purposes

# Option 3: Use existing development servers
# Configure development servers with appropriate access controls
```

#### Manual Testing

```bash
# Connect to test servers to verify SSH access
ssh -i ~/.ssh/test_key testuser@test-server-ip

# Test with MCP VPS Manager
python validate_deployment.py --config tests/configs/test_multiple_servers.yaml
```

#### Cleanup

```bash
# Clean up test resources as appropriate for your environment
# Remove temporary files, reset test server state, etc.
```

## Test Categories

### 1. Connection Tests

Validates SSH connectivity and connection pooling:

- ✅ **Basic Connection** - Establish SSH connection
- ✅ **Authentication** - SSH key authentication
- ✅ **Connection Pooling** - Multiple concurrent connections
- ✅ **Health Monitoring** - Connection health checks
- ✅ **Auto-Reconnection** - Recovery from connection failures

### 2. Security Tests

Validates security mechanisms:

- ✅ **Dangerous Command Blocking** - rm -rf /, fork bombs, etc.
- ✅ **Path Restrictions** - Access control to directories
- ✅ **Input Validation** - Parameter validation and sanitization
- ✅ **Permission Checks** - File and command permission validation

### 3. Command Execution Tests

Validates command execution functionality:

- ✅ **Basic Commands** - echo, whoami, date, uname
- ✅ **Complex Commands** - Pipes, redirections, background
- ✅ **Timeout Handling** - Command timeouts and cancellation
- ✅ **Error Handling** - Non-zero exit codes and stderr

### 4. File Operation Tests

Validates file system operations:

- ✅ **Read Files** - Text and binary file reading
- ✅ **Write Files** - Creating and modifying files
- ✅ **Directory Listing** - Listing directory contents
- ✅ **File Transfer** - Upload and download operations
- ✅ **Permission Handling** - File permission management

### 5. System Monitoring Tests

Validates system monitoring capabilities:

- ✅ **CPU Metrics** - Usage percentage and core count
- ✅ **Memory Metrics** - Total, used, available memory
- ✅ **Disk Metrics** - Disk usage and filesystem information
- ✅ **Process Monitoring** - Running processes and load average
- ✅ **System Information** - Uptime, OS version, kernel info

### 6. Service Management Tests

Validates service control functionality:

- ✅ **Service Listing** - List all services
- ✅ **Service Status** - Get service status and health
- ✅ **Service Control** - Start, stop, restart services
- ✅ **Init System Detection** - systemd, upstart, sysv support
- ✅ **Service Logs** - Retrieve service log files

## Operating System Compatibility

### Tested Distributions

- **Ubuntu** 18.04, 20.04, 22.04 ✅
- **Debian** 9, 10, 11 ✅
- **CentOS** 7, 8 ✅
- **Amazon Linux** 2 ✅
- **Red Hat Enterprise Linux** 8, 9 ✅

### Architecture Support

- **x86_64** (Intel/AMD 64-bit) ✅
- **aarch64** (ARM 64-bit) ✅
- **arm** (ARM 32-bit) ⚠️ Limited testing

## VPS Provider Specific Testing

### DigitalOcean

**Recommended Test Configuration:**
```yaml
digitalocean-test:
  host: "your-droplet-ip"
  username: "root"
  ssh_key_path: "~/.ssh/do_key"
  allowed_directories:
    - "/root"
    - "/var/log"
    - "/etc/nginx"
```

**Known Issues:**
- Some droplets may have restrictive iptables rules
- Ubuntu droplets may need `sudo` for service management

### AWS EC2

**Recommended Test Configuration:**
```yaml
aws-ec2-test:
  host: "ec2-xx-xx-xx-xx.region.compute.amazonaws.com"
  username: "ec2-user"  # Amazon Linux
  # username: "ubuntu"  # Ubuntu AMI
  ssh_key_path: "~/.ssh/aws_key.pem"
  allowed_directories:
    - "/home/ec2-user"
    - "/var/log"
    - "/opt"
```

**Known Issues:**
- Security groups must allow SSH (port 22)
- IAM roles may affect some system commands
- Different AMIs use different default users

### Linode

**Recommended Test Configuration:**
```yaml
linode-test:
  host: "your-linode-ip"
  username: "root"
  ssh_key_path: "~/.ssh/linode_key"
  allowed_directories:
    - "/root"
    - "/var/log"
    - "/etc"
```

**Known Issues:**
- Firewall (ufw/iptables) may block connections
- Some distributions have SELinux enabled

### Vultr

**Recommended Test Configuration:**
```yaml
vultr-test:
  host: "your-vultr-ip"
  username: "root"
  ssh_key_path: "~/.ssh/vultr_key"
  allowed_directories:
    - "/root"
    - "/var/log"
    - "/var/www"
```

## Performance Testing

### Load Testing

Test connection pool under load:

```bash
# Run multiple concurrent validations
python validate_deployment.py --config test_config.yaml &
python validate_deployment.py --config test_config.yaml &
python validate_deployment.py --config test_config.yaml &
wait
```

### Stress Testing

Test with resource constraints:

```bash
# Limit memory and CPU for testing
systemd-run --scope -p MemoryLimit=512M -p CPUQuota=50% \
    python validate_deployment.py --config test_config.yaml
```

## Troubleshooting Tests

### Common Test Failures

#### SSH Authentication Failures
```
Error: Failed to connect test-server: [Errno 13] Permission denied
```

**Solutions:**
- Check SSH key permissions: `chmod 600 ~/.ssh/your_key`
- Verify public key on server: `~/.ssh/authorized_keys`
- Test manual connection: `ssh -i ~/.ssh/your_key user@server`

#### Connection Timeouts
```
Error: Failed to connect test-server: [Errno 110] Connection timed out
```

**Solutions:**
- Check server firewall settings
- Verify SSH service is running: `systemctl status sshd`
- Check network connectivity: `ping server-ip`

#### Permission Denied on Commands
```
Error: Command matches dangerous pattern: sudo passwd
```

**Solutions:**
- Review security configuration in `blocked_commands`
- Add exceptions for administrative tasks
- Use dedicated admin user with appropriate permissions

#### Path Access Denied
```
Error: Path not in allowed directories: /etc/shadow
```

**Solutions:**
- Add required paths to `allowed_directories`
- Use relative paths within allowed directories
- Check directory permissions on server

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
# Enable debug logging
python validate_deployment.py --config test_config.yaml --verbose

# Check debug logs
tail -f /tmp/vps-manager-test.log
```

### Health Checks

Monitor connection pool health:

```python
# Check connection status
python -c "
import asyncio
from src.vps_manager.config import load_config
from src.vps_manager.connection_pool import ConnectionManager

async def check_health():
    config = load_config('test_config.yaml')
    manager = ConnectionManager(config)
    status = manager.get_status_all()
    print(f'Connection status: {status}')

asyncio.run(check_health())
"
```

## Continuous Integration

### GitHub Actions

Add to `.github/workflows/test.yml`:

```yaml
name: Test MCP VPS Manager

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-mock pytest-cov

    - name: Run unit tests
      run: pytest tests/unit/ -v

    - name: Run integration tests
      run: pytest tests/integration/ -v

    - name: Setup test environment
      run: |
        # Configure test environment as needed
        # Note: CI/CD typically uses pre-configured test servers

    - name: Run validation tests
      run: |
        python validate_deployment.py --config tests/configs/test_multiple_servers.yaml
```

## Test Reports

### Generate Test Reports

```bash
# Generate HTML coverage report
pytest --cov=src/vps_manager --cov-report=html tests/

# Generate detailed validation report
python validate_deployment.py --config test_config.yaml \
    --output validation_report.json
```

### View Reports

- **Coverage Report:** Open `htmlcov/index.html` in browser
- **Validation Report:** View `validation_report.json`

## Contributing Tests

When adding new features, include:

1. **Unit Tests** - Test individual functions/classes
2. **Integration Tests** - Test feature in MCP context
3. **Validation Tests** - Test with real servers
4. **Documentation** - Update this testing guide

### Test Structure

```
tests/
├── unit/                 # Unit tests
│   ├── test_security.py
│   ├── test_connection_pool.py
│   └── test_tools.py
├── integration/          # Integration tests
│   ├── test_mcp_server.py
│   └── test_basic_functionality.py
├── configs/              # Test configurations
│   └── test_multiple_servers.yaml
└── keys/                 # SSH keys for testing
    ├── test_ubuntu_key
    └── test_limited_key
```

---

**Happy Testing! 🧪**

For questions or issues with testing, please open an issue in the GitHub repository.
