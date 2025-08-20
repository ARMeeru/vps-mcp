"""Unit tests for configuration module."""

import pytest
import tempfile
import os
from pathlib import Path
import yaml

from src.vps_manager.config import (
    ServerConfig,
    VPSManagerConfig,
    load_config,
    get_ssh_key_passphrase
)


class TestServerConfig:
    """Test server configuration validation."""
    
    def test_valid_server_config(self):
        """Test valid server configuration."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        try:
            config_data = {
                "name": "test-server",
                "host": "192.168.1.100",
                "port": 22,
                "username": "testuser",
                "ssh_key_path": key_path,
                "allowed_paths": ["/home/testuser", "/var/www"],
                "max_file_size_mb": 100
            }
            
            config = ServerConfig(**config_data)
            assert config.name == "test-server"
            assert config.host == "192.168.1.100"
            assert config.port == 22
            assert len(config.allowed_paths) == 2
        finally:
            os.unlink(key_path)
    
    def test_server_config_ssh_key_validation(self):
        """Test SSH key path validation."""
        config_data = {
            "name": "test-server",
            "host": "192.168.1.100",
            "username": "testuser",
            "ssh_key_path": "/nonexistent/path/to/key",
            "allowed_paths": ["/home/testuser"]
        }
        
        with pytest.raises(ValueError, match="SSH key file not found"):
            ServerConfig(**config_data)
    
    def test_server_config_allowed_paths_validation(self):
        """Test allowed paths validation."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        try:
            config_data = {
                "name": "test-server",
                "host": "192.168.1.100",
                "username": "testuser",
                "ssh_key_path": key_path,
                "allowed_paths": ["relative/path"]  # Invalid: not absolute
            }
            
            with pytest.raises(ValueError, match="must be absolute"):
                ServerConfig(**config_data)
        finally:
            os.unlink(key_path)
    
    def test_server_config_port_validation(self):
        """Test port number validation."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        try:
            config_data = {
                "name": "test-server",
                "host": "192.168.1.100",
                "username": "testuser",
                "ssh_key_path": key_path,
                "allowed_paths": ["/home/testuser"],
                "port": 70000  # Invalid: out of range
            }
            
            with pytest.raises(ValueError, match="Port must be between"):
                ServerConfig(**config_data)
        finally:
            os.unlink(key_path)


class TestVPSManagerConfig:
    """Test main configuration validation."""
    
    def test_valid_vps_manager_config(self):
        """Test valid VPS manager configuration."""
        # Create temporary SSH key files
        key_files = []
        try:
            server_configs = []
            for i in range(2):
                key_file = tempfile.NamedTemporaryFile(delete=False)
                key_file.write(b"fake ssh key content")
                key_file.close()
                key_files.append(key_file.name)
                
                server_configs.append({
                    "name": f"server-{i}",
                    "host": f"192.168.1.{100 + i}",
                    "username": f"user{i}",
                    "ssh_key_path": key_file.name,
                    "allowed_paths": [f"/home/user{i}"]
                })
            
            config_data = {
                "servers": server_configs,
                "max_connections_per_server": 5,
                "log_level": "DEBUG"
            }
            
            config = VPSManagerConfig(**config_data)
            assert len(config.servers) == 2
            assert config.max_connections_per_server == 5
            assert config.log_level == "DEBUG"
        finally:
            for key_file in key_files:
                os.unlink(key_file)
    
    def test_unique_server_names_validation(self):
        """Test validation of unique server names."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        try:
            config_data = {
                "servers": [
                    {
                        "name": "duplicate-name",
                        "host": "192.168.1.100",
                        "username": "user1",
                        "ssh_key_path": key_path,
                        "allowed_paths": ["/home/user1"]
                    },
                    {
                        "name": "duplicate-name",  # Duplicate name
                        "host": "192.168.1.101",
                        "username": "user2",
                        "ssh_key_path": key_path,
                        "allowed_paths": ["/home/user2"]
                    }
                ]
            }
            
            with pytest.raises(ValueError, match="Server names must be unique"):
                VPSManagerConfig(**config_data)
        finally:
            os.unlink(key_path)
    
    def test_log_level_validation(self):
        """Test log level validation."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        try:
            config_data = {
                "servers": [{
                    "name": "test-server",
                    "host": "192.168.1.100",
                    "username": "testuser",
                    "ssh_key_path": key_path,
                    "allowed_paths": ["/home/testuser"]
                }],
                "log_level": "INVALID_LEVEL"
            }
            
            with pytest.raises(ValueError, match="Log level must be one of"):
                VPSManagerConfig(**config_data)
        finally:
            os.unlink(key_path)


class TestConfigLoader:
    """Test configuration loading functionality."""
    
    def test_load_config_from_file(self):
        """Test loading configuration from YAML file."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_file:
            config_data = {
                "servers": [{
                    "name": "test-server",
                    "host": "192.168.1.100",
                    "username": "testuser",
                    "ssh_key_path": key_path,
                    "allowed_paths": ["/home/testuser"],
                    "port": 2222
                }],
                "max_connections_per_server": 2,
                "log_level": "WARNING"
            }
            yaml.dump(config_data, config_file)
            config_path = config_file.name
        
        try:
            config = load_config(config_path)
            assert len(config.servers) == 1
            assert config.servers[0].name == "test-server"
            assert config.servers[0].port == 2222
            assert config.max_connections_per_server == 2
            assert config.log_level == "WARNING"
        finally:
            os.unlink(key_path)
            os.unlink(config_path)
    
    def test_load_config_file_not_found(self):
        """Test handling of missing configuration file."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")
    
    def test_load_config_environment_overrides(self):
        """Test environment variable overrides."""
        # Create temporary SSH key file
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(b"fake ssh key content")
            key_path = key_file.name
        
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_file:
            config_data = {
                "servers": [{
                    "name": "test-server",
                    "host": "192.168.1.100",
                    "username": "testuser",
                    "ssh_key_path": key_path,
                    "allowed_paths": ["/home/testuser"]
                }],
                "max_connections_per_server": 3,
                "log_level": "INFO"
            }
            yaml.dump(config_data, config_file)
            config_path = config_file.name
        
        # Set environment variables
        original_env = {}
        env_overrides = {
            "MAX_CONNECTIONS_PER_SERVER": "5",
            "LOG_LEVEL": "ERROR",
            "AUDIT_LOG_ENABLED": "false"
        }
        
        try:
            # Save original environment
            for key in env_overrides:
                original_env[key] = os.environ.get(key)
                os.environ[key] = env_overrides[key]
            
            config = load_config(config_path)
            assert config.max_connections_per_server == 5
            assert config.log_level == "ERROR"
            assert config.audit_log_enabled is False
        finally:
            # Restore original environment
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            
            os.unlink(key_path)
            os.unlink(config_path)


class TestSSHKeyPassphrase:
    """Test SSH key passphrase handling."""
    
    def test_get_ssh_key_passphrase_success(self):
        """Test successful passphrase retrieval."""
        env_var = "TEST_SSH_PASSPHRASE"
        expected_passphrase = "secret123"
        
        original_value = os.environ.get(env_var)
        try:
            os.environ[env_var] = expected_passphrase
            passphrase = get_ssh_key_passphrase(env_var)
            assert passphrase == expected_passphrase
        finally:
            if original_value is None:
                os.environ.pop(env_var, None)
            else:
                os.environ[env_var] = original_value
    
    def test_get_ssh_key_passphrase_not_found(self):
        """Test handling of missing passphrase environment variable."""
        env_var = "NONEXISTENT_SSH_PASSPHRASE"
        
        # Ensure variable doesn't exist
        os.environ.pop(env_var, None)
        
        with pytest.raises(ValueError, match="not found"):
            get_ssh_key_passphrase(env_var)
    
    def test_get_ssh_key_passphrase_none(self):
        """Test handling of None env_var_name."""
        passphrase = get_ssh_key_passphrase(None)
        assert passphrase is None


if __name__ == "__main__":
    pytest.main([__file__])