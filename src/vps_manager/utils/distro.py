"""Linux distribution detection utilities."""

import re
from enum import Enum
from typing import Optional, Tuple

from asyncssh import SSHClientConnection


class InitSystem(Enum):
    """Supported init systems."""

    SYSTEMD = "systemd"
    UPSTART = "upstart"
    SYSVINIT = "sysvinit"
    UNKNOWN = "unknown"


class DistroFamily(Enum):
    """Linux distribution families."""

    DEBIAN = "debian"
    REDHAT = "redhat"
    ARCH = "arch"
    SUSE = "suse"
    UNKNOWN = "unknown"


class DistroDetector:
    """Detects Linux distribution and init system."""

    # Distribution detection patterns
    DISTRO_PATTERNS = {
        DistroFamily.DEBIAN: [
            r"ubuntu",
            r"debian",
            r"mint",
            r"elementary",
            r"pop",
            r"kali",
            r"parrot",
            r"mxlinux",
        ],
        DistroFamily.REDHAT: [
            r"rhel",
            r"red hat",
            r"centos",
            r"fedora",
            r"amazon linux",
            r"oracle linux",
            r"rocky",
            r"alma",
        ],
        DistroFamily.ARCH: [r"arch", r"manjaro", r"antergos", r"endeavour"],
        DistroFamily.SUSE: [r"opensuse", r"suse", r"sles"],
    }

    @staticmethod
    async def detect_init_system(connection: SSHClientConnection) -> InitSystem:
        """Detect the init system running on the server with container-aware detection.

        Args:
            connection: SSH connection object

        Returns:
            Detected init system
        """
        # Method 1: Check for systemd via /run/systemd/system (most reliable,
        # container-aware)
        try:
            result = await connection.run("test -d /run/systemd/system", check=True)
            if result.returncode == 0:
                return InitSystem.SYSTEMD
        except Exception:
            pass

        # Method 2: Check systemctl availability and version
        try:
            result = await connection.run("systemctl --version 2>/dev/null", check=True)
            if result.returncode == 0 and "systemd" in result.stdout.lower():
                return InitSystem.SYSTEMD
        except Exception:
            pass

        # Method 3: Check what's running as PID 1 (may fail in containers)
        try:
            result = await connection.run(
                "ps -p 1 -o comm= 2>/dev/null || ps -p 1 -o args= | head -1",
                check=True,
            )
            pid1_command = result.stdout.strip().lower()

            if "systemd" in pid1_command:
                return InitSystem.SYSTEMD
            elif "init" in pid1_command and "upstart" in pid1_command:
                return InitSystem.UPSTART
            elif "/sbin/init" in pid1_command or "init" in pid1_command:
                # PID 1 is init, but could still be systemd in some setups
                # Check if systemctl works
                try:
                    await connection.run(
                        (
                            "systemctl list-units --type=service --state=running "
                            "--no-pager --no-legend | head -1"
                        ),
                        check=True,
                    )
                    return InitSystem.SYSTEMD
                except BaseException:
                    pass

                # Check if initctl is available (upstart)
                try:
                    result = await connection.run(
                        "initctl version 2>/dev/null", check=True
                    )
                    if result.returncode == 0:
                        return InitSystem.UPSTART
                except BaseException:
                    pass

                return InitSystem.SYSVINIT

        except Exception:
            pass

        # Method 4: Check for upstart specifically
        try:
            result = await connection.run("initctl version 2>/dev/null", check=True)
            if result.returncode == 0 and "upstart" in result.stdout.lower():
                return InitSystem.UPSTART
        except Exception:
            pass

        # Method 5: Check for SysV init (fallback)
        try:
            # Check if /etc/init.d exists and has executable scripts
            result = await connection.run(
                "test -d /etc/init.d && ls /etc/init.d/ | head -1", check=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return InitSystem.SYSVINIT
        except Exception:
            pass

        # Method 6: Container environment detection
        try:
            # Check if we're in a container that might have systemd
            result = await connection.run(
                "test -f /.dockerenv -o -f /run/.containerenv", check=False
            )
            if result.returncode == 0:
                # In a container, check for systemd again with different
                # approach
                try:
                    result = await connection.run(
                        "systemctl is-system-running 2>/dev/null", check=False
                    )
                    if result.returncode in [
                        0,
                        1,
                    ]:  # 0 = running, 1 = degraded (both valid for systemd)
                        return InitSystem.SYSTEMD
                except BaseException:
                    pass
        except Exception:
            pass

        return InitSystem.UNKNOWN

    @staticmethod
    async def detect_distro_family(
        connection: SSHClientConnection,
    ) -> Tuple[DistroFamily, str]:
        """Detect the Linux distribution family and name.

        Args:
            connection: SSH connection object

        Returns:
            Tuple of (distro_family, distro_name)
        """
        distro_name = "Unknown"
        distro_family = DistroFamily.UNKNOWN

        # Try various detection methods
        detection_methods = [
            DistroDetector._detect_from_os_release,
            DistroDetector._detect_from_lsb_release,
            DistroDetector._detect_from_etc_files,
            DistroDetector._detect_from_uname,
        ]

        for method in detection_methods:
            try:
                family, name = await method(connection)
                if family != DistroFamily.UNKNOWN:
                    distro_family = family
                    distro_name = name
                    break
            except Exception:
                continue

        return distro_family, distro_name

    @staticmethod
    async def _detect_from_os_release(
        connection: SSHClientConnection,
    ) -> Tuple[DistroFamily, str]:
        """Detect from /etc/os-release file."""
        result = await connection.run("cat /etc/os-release", check=True)

        os_info = {}
        for line in result.stdout.split("\n"):
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os_info[key.strip()] = value.strip().strip('"')

        distro_id = os_info.get("ID", "").lower()
        distro_name = os_info.get("PRETTY_NAME", os_info.get("NAME", distro_id))

        # Map to family
        for family, patterns in DistroDetector.DISTRO_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, distro_id) or re.search(
                    pattern, distro_name.lower()
                ):
                    return family, distro_name

        return DistroFamily.UNKNOWN, distro_name

    @staticmethod
    async def _detect_from_lsb_release(
        connection: SSHClientConnection,
    ) -> Tuple[DistroFamily, str]:
        """Detect from lsb_release command."""
        result = await connection.run("lsb_release -a 2>/dev/null", check=True)

        lines = result.stdout.strip().split("\n")
        distro_name = "Unknown"

        for line in lines:
            if line.startswith("Description:"):
                distro_name = line.split(":", 1)[1].strip()
                break

        # Map to family
        distro_lower = distro_name.lower()
        for family, patterns in DistroDetector.DISTRO_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, distro_lower):
                    return family, distro_name

        return DistroFamily.UNKNOWN, distro_name

    @staticmethod
    async def _detect_from_etc_files(
        connection: SSHClientConnection,
    ) -> Tuple[DistroFamily, str]:
        """Detect from /etc/*-release files."""
        release_files = [
            ("/etc/redhat-release", DistroFamily.REDHAT),
            ("/etc/debian_version", DistroFamily.DEBIAN),
            ("/etc/arch-release", DistroFamily.ARCH),
            ("/etc/SuSE-release", DistroFamily.SUSE),
            ("/etc/suse-release", DistroFamily.SUSE),
        ]

        for file_path, family in release_files:
            try:
                result = await connection.run(f"cat {file_path}", check=True)
                content = result.stdout.strip()
                if content:
                    return family, content.split("\n")[0]
            except BaseException:
                continue

        return DistroFamily.UNKNOWN, "Unknown"

    @staticmethod
    async def _detect_from_uname(
        connection: SSHClientConnection,
    ) -> Tuple[DistroFamily, str]:
        """Fallback detection from uname."""
        try:
            result = await connection.run("uname -a", check=True)
            uname_output = result.stdout.lower()

            for family, patterns in DistroDetector.DISTRO_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, uname_output):
                        return family, f"Unknown {family.value.title()}"

        except BaseException:
            pass

        return DistroFamily.UNKNOWN, "Unknown"


class ServiceCommandMapper:
    """Maps service operations to appropriate commands based on init system."""

    COMMAND_MAPS = {
        InitSystem.SYSTEMD: {
            "start": "systemctl start {service}",
            "stop": "systemctl stop {service}",
            "restart": "systemctl restart {service}",
            "reload": "systemctl reload {service}",
            "status": "systemctl status {service}",
            "enable": "systemctl enable {service}",
            "disable": "systemctl disable {service}",
            "is-enabled": "systemctl is-enabled {service}",
            "is-active": "systemctl is-active {service}",
        },
        InitSystem.UPSTART: {
            "start": "start {service}",
            "stop": "stop {service}",
            "restart": "restart {service}",
            "reload": "reload {service}",
            "status": "status {service}",
            "enable": "echo 'manual' > /etc/init/{service}.override",
            "disable": "echo 'start on never' > /etc/init/{service}.override",
        },
        InitSystem.SYSVINIT: {
            "start": "/etc/init.d/{service} start",
            "stop": "/etc/init.d/{service} stop",
            "restart": "/etc/init.d/{service} restart",
            "reload": "/etc/init.d/{service} reload",
            "status": "/etc/init.d/{service} status",
            "enable": "update-rc.d {service} enable",  # Debian
            "disable": "update-rc.d {service} disable",
        },
    }

    REDHAT_SYSV_COMMANDS = {
        "enable": "chkconfig {service} on",
        "disable": "chkconfig {service} off",
        "status": "chkconfig --list {service}",
    }

    @staticmethod
    def get_command(
        init_system: InitSystem,
        action: str,
        service: str,
        distro_family: DistroFamily = DistroFamily.UNKNOWN,
    ) -> Optional[str]:
        """Get the appropriate command for a service action.

        Args:
            init_system: Detected init system
            action: Service action (start, stop, etc.)
            service: Service name
            distro_family: Distribution family for SysV variations

        Returns:
            Command string or None if not supported
        """
        if init_system not in ServiceCommandMapper.COMMAND_MAPS:
            return None

        commands = ServiceCommandMapper.COMMAND_MAPS[init_system]

        # Handle SysV variations for RedHat family
        if (
            init_system == InitSystem.SYSVINIT
            and distro_family == DistroFamily.REDHAT
            and action in ServiceCommandMapper.REDHAT_SYSV_COMMANDS
        ):
            command_template = ServiceCommandMapper.REDHAT_SYSV_COMMANDS[action]
        else:
            command_template: Optional[str] = commands.get(action)

        if command_template:
            return command_template.format(service=service)

        return None

    @staticmethod
    def normalize_service_name(service: str, init_system: InitSystem) -> str:
        """Normalize service name for the init system.

        Args:
            service: Raw service name
            init_system: Target init system

        Returns:
            Normalized service name
        """
        # Remove common suffixes/prefixes
        service = service.strip()

        if init_system == InitSystem.SYSTEMD:
            # For systemd, ensure .service suffix if not present and not a
            # target/socket
            if not any(
                service.endswith(ext)
                for ext in [
                    ".service",
                    ".target",
                    ".socket",
                    ".timer",
                    ".mount",
                ]
            ):
                service = f"{service}.service"
        else:
            # For other init systems, remove .service suffix
            if service.endswith(".service"):
                service = service[:-8]

        return service
