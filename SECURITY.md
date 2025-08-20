# Security Guide for MCP VPS Manager

This document outlines security considerations, best practices, and validation mechanisms built into the MCP VPS Manager.

## Table of Contents

1. [Security Architecture](#security-architecture)
2. [Command Validation](#command-validation)
3. [File System Security](#file-system-security)
4. [SSH Security](#ssh-security)
5. [Network Security](#network-security)
6. [Audit and Logging](#audit-and-logging)
7. [Best Practices](#best-practices)
8. [Security Configuration](#security-configuration)
9. [Threat Model](#threat-model)
10. [Incident Response](#incident-response)

## Security Architecture

The MCP VPS Manager implements a multi-layered security approach:

```
┌─────────────────┐
│   MCP Client    │ (Claude Desktop)
│   (Untrusted)   │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ Security Layer  │ ← Command/Path Validation
│   (Trusted)     │ ← Rate Limiting
└─────────────────┘ ← Audit Logging
         │
         ▼
┌─────────────────┐
│ Connection Pool │ ← SSH Key Auth
│   (Trusted)     │ ← Connection Limits
└─────────────────┘
         │
         ▼
┌─────────────────┐
│   VPS Server    │ ← Server-side Security
│  (External)     │ ← Firewall Rules
└─────────────────┘
```

## Command Validation

### Dangerous Command Patterns

The system blocks commands matching these patterns:

#### Destructive Operations
```regex
rm\s+-rf\s+/              # Recursive delete from root
rm\s+-rf\s+\*             # Recursive delete all
dd\s+if=.*of=/dev/        # Disk overwrite
mkfs\.*                   # Format filesystem
fdisk.*                   # Disk partitioning
```

#### System Manipulation
```regex
chmod\s+-R\s+777\s+/      # Recursive world permissions
chown\s+-R\s+.*\s+/       # Recursive ownership change
usermod.*root             # Modify root user
passwd.*root              # Change root password
```

#### Network Security
```regex
iptables\s+-F             # Flush firewall rules
ufw\s+disable             # Disable firewall
nc.*-l.*-p                # Netcat listener
ncat.*-l.*-p              # Ncat listener
```

#### Process Control
```regex
killall.*                # Kill all processes
pkill.*-9.*               # Force kill processes
kill.*-9.*1$              # Kill init process
```

#### Privilege Escalation
```regex
sudo\s+su\s+-             # Switch to root
su\s+-.*root              # Switch to root user
sudo\s+chmod.*4755        # Set SUID bit
```

#### Malicious Code
```regex
:(){ :|:& };:             # Fork bomb
perl.*-e.*exec            # Perl code execution
python.*-c.*exec          # Python code execution
bash.*-c.*curl            # Download and execute
wget.*\|.*sh              # Download and execute
```

### Custom Validation Rules

You can add custom dangerous patterns per server:

```yaml
servers:
  production-web:
    host: "web.example.com"
    blocked_commands:
      - "service.*stop"        # Prevent stopping services
      - "systemctl.*disable"   # Prevent disabling services
      - "crontab.*-r"         # Prevent crontab deletion
```

### Command Whitelisting

For high-security environments, consider command whitelisting:

```yaml
vps_manager:
  security:
    command_whitelist_mode: true
    allowed_commands:
      - "ls"
      - "cat"
      - "grep"
      - "tail"
      - "head"
      - "ps"
      - "top"
      - "df"
      - "free"
      - "uptime"
```

## File System Security

### Path Validation

All file operations are restricted to allowed directories:

#### Default Allowed Paths
- `/home/` - User home directories
- `/var/log/` - Log files
- `/tmp/` - Temporary files
- `/opt/` - Optional software

#### Blocked Paths (Always)
- `/etc/shadow` - Password hashes
- `/etc/sudoers` - Sudo configuration
- `/root/.ssh/` - Root SSH keys
- `/boot/` - Boot configuration
- `/sys/` - System files
- `/proc/` - Process information

### File Size Limits

Maximum file sizes are enforced:

```yaml
vps_manager:
  security:
    max_file_size_mb: 100      # Maximum file size for operations
    max_directory_entries: 10000  # Maximum entries in directory listing
```

### File Type Restrictions

Certain file types are restricted:

```yaml
servers:
  production-web:
    blocked_file_extensions:
      - ".key"          # Private keys
      - ".pem"          # Certificates
      - ".p12"          # PKCS#12 files
      - ".jks"          # Java keystores
```

## SSH Security

### Key-Based Authentication

**NEVER use password authentication in production:**

```yaml
# ❌ WRONG - Password authentication
servers:
  web-server:
    host: "web.example.com"
    username: "deploy"
    password: "insecure-password"

# ✅ CORRECT - SSH key authentication
servers:
  web-server:
    host: "web.example.com"
    username: "deploy"
    ssh_key_path: "~/.ssh/web_deploy_key"
```

### SSH Key Management

1. **Generate dedicated keys for VPS Manager:**
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/vps_manager_key -C "vps-manager@$(hostname)"
   ```

2. **Use unencrypted keys** (store securely):
   ```bash
   # Don't set a passphrase when prompted
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/vps_manager_key
   ```

3. **Set proper permissions:**
   ```bash
   chmod 600 ~/.ssh/vps_manager_key
   chmod 644 ~/.ssh/vps_manager_key.pub
   ```

4. **Deploy public keys securely:**
   ```bash
   ssh-copy-id -i ~/.ssh/vps_manager_key.pub user@server
   ```

### Connection Security

```yaml
vps_manager:
  connection_pool:
    connection_timeout: 30        # Prevent hanging connections
    max_connections_per_server: 3 # Limit concurrent connections
    health_check_interval: 300    # Regular health checks
```

## Network Security

### Firewall Configuration

Configure server firewalls to restrict SSH access:

```bash
# Allow SSH only from specific IPs
ufw allow from YOUR_IP_ADDRESS to any port 22

# Or allow from specific subnet
ufw allow from 192.168.1.0/24 to any port 22

# Block all other SSH access
ufw deny 22
```

### SSH Configuration

Harden SSH server configuration (`/etc/ssh/sshd_config`):

```
# Disable root login
PermitRootLogin no

# Disable password authentication
PasswordAuthentication no
PubkeyAuthentication yes

# Limit login attempts
MaxAuthTries 3
MaxStartups 3

# Disable X11 forwarding
X11Forwarding no

# Use strong ciphers
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
```

### VPN Access

For additional security, access servers through VPN:

```yaml
servers:
  internal-server:
    host: "10.0.1.100"  # Internal VPN IP
    port: 22
    username: "admin"
    ssh_key_path: "~/.ssh/internal_key"
```

## Audit and Logging

### Command Logging

All commands are logged with details:

```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "server": "web-production",
  "user": "deploy",
  "command": "systemctl status nginx",
  "working_directory": "/home/deploy",
  "exit_code": 0,
  "duration_ms": 1250,
  "client_session": "claude-desktop-abc123"
}
```

### Security Events

Security-related events are logged:

```json
{
  "timestamp": "2024-01-01T12:05:00Z",
  "event_type": "command_blocked",
  "server": "web-production",
  "command": "rm -rf /",
  "reason": "Dangerous command pattern detected",
  "client_session": "claude-desktop-abc123"
}
```

### Log Rotation

Configure log rotation to prevent disk filling:

```yaml
vps_manager:
  logging:
    max_size: "50MB"
    backup_count: 10
    compression: true
```

## Best Practices

### 1. Principle of Least Privilege

- Create dedicated users for VPS Manager with minimal permissions
- Use sudo sparingly and with specific command restrictions
- Regularly audit user permissions

```bash
# Create dedicated user
sudo useradd -m -s /bin/bash vps-manager

# Add to specific groups only
sudo usermod -a -G www-data vps-manager

# Configure sudoers for specific commands only
echo "vps-manager ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *, /usr/bin/systemctl restart *" | sudo tee /etc/sudoers.d/vps-manager
```

### 2. Network Segmentation

- Isolate VPS Manager servers in separate network segments
- Use bastion hosts for indirect access
- Implement network-level monitoring

### 3. Regular Security Updates

- Keep SSH server updated
- Update VPS Manager regularly
- Monitor security advisories

### 4. Access Control

- Use IP allowlists for SSH access
- Implement MFA where possible
- Regular access reviews

### 5. Monitoring and Alerting

- Monitor for suspicious command patterns
- Alert on security events
- Track failed authentication attempts

```yaml
vps_manager:
  monitoring:
    alert_on_blocked_commands: true
    alert_on_failed_auth: true
    alert_on_unusual_activity: true
```

## Security Configuration

### High-Security Configuration

For production environments:

```yaml
vps_manager:
  security:
    # Strict command validation
    enable_command_validation: true
    command_whitelist_mode: true
    allowed_commands:
      - "ls"
      - "cat"
      - "grep"
      - "tail"
      - "head"
      - "ps"
      - "systemctl status *"

    # Restrictive file access
    allowed_directories:
      - "/home/app"
      - "/var/log/app"
      - "/opt/app"

    max_file_size_mb: 10

    # Enhanced logging
    log_all_commands: true
    log_level: "DEBUG"

  # Connection limits
  connection_pool:
    max_connections_per_server: 2
    connection_timeout: 15
    health_check_interval: 60

servers:
  production:
    host: "prod.internal"
    username: "app-manager"
    ssh_key_path: "~/.ssh/prod_key"

    # Server-specific restrictions
    allowed_directories:
      - "/home/app"
      - "/var/log/app"

    blocked_commands:
      - ".*sudo.*"
      - "service.*stop"
      - "systemctl.*disable"
```

### Development Configuration

For development environments:

```yaml
vps_manager:
  security:
    enable_command_validation: true
    command_whitelist_mode: false

    allowed_directories:
      - "/home"
      - "/var/log"
      - "/tmp"
      - "/opt"
      - "/var/www"

    max_file_size_mb: 100

  logging:
    log_level: "INFO"

servers:
  dev:
    host: "dev.internal"
    username: "developer"
    ssh_key_path: "~/.ssh/dev_key"
```

## Threat Model

### Potential Threats

1. **Malicious MCP Client**
   - Mitigation: Command validation, path restrictions, logging

2. **Compromised SSH Keys**
   - Mitigation: Key rotation, access monitoring, network restrictions

3. **Network Eavesdropping**
   - Mitigation: SSH encryption, VPN access, certificate pinning

4. **Privilege Escalation**
   - Mitigation: Dedicated users, sudo restrictions, command validation

5. **Data Exfiltration**
   - Mitigation: File size limits, path restrictions, audit logging

6. **Service Disruption**
   - Mitigation: Command filtering, connection limits, monitoring

### Attack Scenarios

#### Scenario 1: Malicious Command Injection
- **Attack**: Client sends `rm -rf /`
- **Defense**: Command pattern matching blocks execution
- **Response**: Log security event, notify administrators

#### Scenario 2: Unauthorized File Access
- **Attack**: Client tries to read `/etc/shadow`
- **Defense**: Path validation rejects request
- **Response**: Access denied, security event logged

#### Scenario 3: SSH Key Compromise
- **Attack**: Attacker uses stolen SSH key
- **Defense**: Network restrictions, monitoring unusual activity
- **Response**: Key rotation, access audit, network investigation

## Incident Response

### Security Event Response

1. **Immediate Actions**
   - Block suspicious connections
   - Preserve logs for analysis
   - Notify security team

2. **Investigation**
   - Analyze command logs
   - Check server integrity
   - Review access patterns

3. **Remediation**
   - Rotate compromised keys
   - Update security rules
   - Patch vulnerabilities

4. **Recovery**
   - Restore services if needed
   - Update monitoring rules
   - Document lessons learned

### Emergency Procedures

#### Command to Disable VPS Manager Access
```bash
# Block all connections immediately
sudo iptables -I INPUT -p tcp --dport 22 -s MANAGER_IP -j DROP

# Or disable SSH key
mv ~/.ssh/authorized_keys ~/.ssh/authorized_keys.disabled
```

#### Log Analysis Commands
```bash
# Find security events
grep "command_blocked" /var/log/vps-manager.log

# Find failed authentications
grep "auth failed" /var/log/auth.log

# Check unusual commands
grep -E "(rm -rf|chmod 777|killall)" /var/log/vps-manager.log
```

## Security Checklist

### Deployment Security
- [ ] SSH keys generated with strong entropy
- [ ] Password authentication disabled
- [ ] Firewall rules configured
- [ ] Security patterns updated
- [ ] Logging configured
- [ ] Monitoring enabled
- [ ] Access controls tested

### Operational Security
- [ ] Regular security updates applied
- [ ] Logs monitored daily
- [ ] Access patterns reviewed
- [ ] Keys rotated quarterly
- [ ] Security events investigated
- [ ] Configurations audited

### Emergency Preparedness
- [ ] Incident response plan documented
- [ ] Emergency contacts defined
- [ ] Backup access methods available
- [ ] Recovery procedures tested
- [ ] Communication plan established

## Compliance Considerations

### Data Protection
- Ensure compliance with GDPR, CCPA, etc.
- Document data processing activities
- Implement data retention policies

### Industry Standards
- Follow CIS benchmarks for SSH hardening
- Comply with SOC 2 requirements if applicable
- Adhere to PCI DSS for payment processing environments

### Audit Requirements
- Maintain comprehensive audit logs
- Regular security assessments
- Vulnerability scanning
- Penetration testing

---

**Remember: Security is an ongoing process, not a one-time configuration. Regularly review and update your security posture based on new threats and requirements.**
