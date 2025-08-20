# Security Note - Sensitive Data Protection

## ⚠️ IMPORTANT: This Project Contains Sensitive Data Patterns

This MCP VPS Manager project handles sensitive information including:
- **Server IP addresses and hostnames**
- **SSH private keys and certificates**
- **Usernames and authentication credentials**
- **Configuration files with real server details**
- **Log files that may contain sensitive command output**

## Protected by .gitignore

The `.gitignore` file has been configured to protect:

### 🔐 **Critical Security Items**
- `config/servers.yaml` - Contains real server IPs and credentials
- SSH keys (`*.key`, `*.pem`, `id_rsa*`, etc.)
- Environment files (`.env*`)
- Log files (`*.log`, `logs/`)
- Personal/production configurations

### 📁 **Safe to Commit**
- Template files (`templates/`)
- Example configurations (`*example*`, `*template*`)
- Test configurations with placeholder data
- Source code and documentation

## Before Committing

**Always verify sensitive data is not being committed:**

```bash
# Check what will be committed
git status
git diff --cached

# Verify no sensitive files
git ls-files | grep -E "\.(key|pem|log)$|servers\.yaml$|\.env"

# If any sensitive files appear, add them to .gitignore immediately
echo "path/to/sensitive/file" >> .gitignore
```

## If Sensitive Data Was Accidentally Committed

**Immediate actions:**

1. **DO NOT** just add to .gitignore (too late, it's in history)
2. **Remove from Git history:**
   ```bash
   git rm --cached path/to/sensitive/file
   git commit -m "Remove sensitive file"
   # For complete removal from history:
   git filter-branch --force --index-filter \
   "git rm --cached --ignore-unmatch path/to/sensitive/file" \
   --prune-empty --tag-name-filter cat -- --all
   ```
3. **Change any exposed credentials immediately**
4. **Force push** (if working alone) or coordinate with team

## Development Best Practices

### ✅ **Safe Practices**
- Use template files for examples
- Use placeholder data in templates
- Keep real configurations in `config/servers.yaml` (ignored)
- Use environment variables for secrets
- Test with development servers using placeholder data

### ❌ **Never Commit**
- Real server IPs or hostnames
- SSH private keys or certificates
- Passwords or API keys
- Production configuration files
- Log files with command output
- Personal authentication tokens

## Setup for New Developers

1. **Copy templates to create real configs:**
   ```bash
   cp templates/servers.yaml config/servers.yaml
   # Edit config/servers.yaml with your real server details
   ```

2. **Verify .gitignore is working:**
   ```bash
   git check-ignore config/servers.yaml
   # Should output: config/servers.yaml (meaning it's ignored)
   ```

3. **Never modify template files with real data**

## Emergency Response

If you discover sensitive data in the repository:

1. **Stop** - Don't commit or push anything
2. **Assess** - What sensitive data is exposed?
3. **Remove** - Use git commands above to remove from history
4. **Rotate** - Change any exposed credentials immediately
5. **Review** - Audit entire codebase for other sensitive data

## Questions?

When in doubt:
- **Assume it's sensitive** and add to .gitignore
- **Use placeholders** in examples and templates
- **Keep production configs local** and never commit them
- **Review** what you're committing carefully

---
**Remember: It's much easier to prevent exposure than to fix it after the fact.**
