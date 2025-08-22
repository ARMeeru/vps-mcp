"""Configuration management with Pydantic validation."""

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, validator


class ServerConfig(BaseModel):
    """Configuration for a single VPS server."""

    name: str = Field(..., description="Unique server identifier")
    host: str = Field(..., description="Server hostname or IP address")
    port: int = Field(default=22, description="SSH port")
    username: str = Field(..., description="SSH username")
    ssh_key_path: str = Field(..., description="Path to SSH private key")
    ssh_key_passphrase_env: Optional[str] = Field(
        default=None,
        description="Environment variable name for SSH key passphrase",
    )
    allowed_paths: List[str] = Field(
        default_factory=list, description="List of allowed file system paths"
    )
    blocked_commands: List[str] = Field(
        default_factory=list, description="Additional blocked command patterns"
    )
    max_file_size_mb: int = Field(default=50, description="Maximum file size in MB")
    connection_timeout: int = Field(default=30, description="SSH connection timeout")
    command_timeout: int = Field(default=300, description="Default command timeout")

    @validator("ssh_key_path")
    def validate_ssh_key_path(cls, v: str) -> str:
        """Validate SSH key path exists."""
        expanded_path = Path(v).expanduser()
        if not expanded_path.exists():
            raise ValueError(f"SSH key file not found: {expanded_path}")
        return str(expanded_path)

    @validator("allowed_paths")
    def validate_allowed_paths(cls, v: List[str]) -> List[str]:
        """Ensure allowed paths are absolute."""
        validated_paths = []
        for path in v:
            expanded = Path(path).expanduser()
            if not expanded.is_absolute():
                raise ValueError(f"Allowed path must be absolute: {path}")
            validated_paths.append(str(expanded))
        return validated_paths

    @validator("port")
    def validate_port(cls, v: int) -> int:
        """Validate port range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class VPSManagerConfig(BaseModel):
    """Main configuration for VPS Manager."""

    servers: List[ServerConfig] = Field(..., description="List of VPS servers")

    # Global settings
    max_connections_per_server: int = Field(
        default=3, description="Maximum SSH connections per server"
    )
    health_check_interval: int = Field(
        default=30, description="Health check interval in seconds"
    )
    connection_retry_max_delay: int = Field(
        default=30, description="Maximum retry delay in seconds"
    )
    log_level: str = Field(default="INFO", description="Logging level")
    log_dir: str = Field(default="./logs", description="Log directory")
    audit_log_enabled: bool = Field(default=True, description="Enable audit logging")

    @validator("servers")
    def validate_unique_server_names(cls, v: List[ServerConfig]) -> List[ServerConfig]:
        """Ensure server names are unique."""
        names = [server.name for server in v]
        if len(names) != len(set(names)):
            raise ValueError("Server names must be unique")
        return v

    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


def load_config(config_path: Optional[str] = None) -> VPSManagerConfig:
    """Load configuration from YAML file with environment variable overrides."""

    # Determine config file path
    if config_path is None:
        config_path = os.getenv("SERVERS_CONFIG_PATH", "./config/servers.yaml")

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    # Load YAML configuration
    with open(config_file, "r") as f:
        yaml_data = yaml.safe_load(f)

    # Override with environment variables if present
    env_overrides = {
        "max_connections_per_server": os.getenv("MAX_CONNECTIONS_PER_SERVER"),
        "health_check_interval": os.getenv("HEALTH_CHECK_INTERVAL"),
        "connection_retry_max_delay": os.getenv("CONNECTION_RETRY_MAX_DELAY"),
        "log_level": os.getenv("LOG_LEVEL"),
        "log_dir": os.getenv("LOG_DIR"),
        "audit_log_enabled": os.getenv("AUDIT_LOG_ENABLED"),
    }

    # Apply non-None environment overrides
    for key, value in env_overrides.items():
        if value is not None:
            # Convert string values to appropriate types
            if key in [
                "max_connections_per_server",
                "health_check_interval",
                "connection_retry_max_delay",
            ]:
                yaml_data[key] = int(value)
            elif key == "audit_log_enabled":
                yaml_data[key] = value.lower() in ("true", "1", "yes", "on")
            else:
                yaml_data[key] = value

    return VPSManagerConfig(**yaml_data)


def get_ssh_key_passphrase(env_var_name: Optional[str]) -> Optional[str]:
    """Get SSH key passphrase from environment variable if specified."""
    if env_var_name is None:
        return None

    passphrase = os.getenv(env_var_name)
    if passphrase is None:
        raise ValueError(
            f"SSH key passphrase environment variable not found: {env_var_name}"
        )

    return passphrase
