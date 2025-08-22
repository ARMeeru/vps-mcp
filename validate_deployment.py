#!/usr/bin/env python3
"""
Comprehensive validation script for MCP VPS Manager.

This script validates the system works with different VPS providers and configurations.
It performs various tests to ensure compatibility and reliability.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import argparse
import tempfile
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from vps_manager.config import load_config
from vps_manager.connection_pool import ConnectionManager
from vps_manager.security import SecurityValidator
from vps_manager.tools.command import CommandTool
from vps_manager.tools.file_ops import FileOperationsTool
from vps_manager.tools.monitoring import SystemMonitoringTool
from vps_manager.tools.services import ServiceManagementTool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VPSValidationSuite:
    """Comprehensive VPS Manager validation suite."""

    def __init__(self, config_path: str):
        """Initialize the validation suite."""
        self.config_path = config_path
        self.config = None
        self.connection_manager = None
        self.results = {
            "servers": {},
            "summary": {
                "total_servers": 0,
                "successful_servers": 0,
                "failed_servers": 0,
                "total_tests": 0,
                "successful_tests": 0,
                "failed_tests": 0
            }
        }

    async def initialize(self) -> bool:
        """Initialize the validation suite."""
        try:
            logger.info(f"Loading configuration from {self.config_path}")
            self.config = load_config(self.config_path)
            self.connection_manager = ConnectionManager(self.config)

            logger.info(f"Found {len(self.config.servers)} servers to validate")
            self.results["summary"]["total_servers"] = len(self.config.servers)

            return True

        except Exception as e:
            logger.error(f"Failed to initialize validation suite: {e}")
            return False

    async def validate_all_servers(self) -> Dict[str, Any]:
        """Validate all configured servers."""
        logger.info("Starting comprehensive validation of all servers")

        for server_config in self.config.servers:
            server_name = server_config.name
            logger.info(f"\\n{'='*60}")
            logger.info(f"Validating server: {server_name}")
            logger.info(f"Host: {server_config.host}:{server_config.port}")
            logger.info(f"{'='*60}")

            server_results = await self.validate_server(server_name)
            self.results["servers"][server_name] = server_results

            # Update summary
            if server_results["overall_success"]:
                self.results["summary"]["successful_servers"] += 1
                logger.info(f"Server {server_name}: PASSED")
            else:
                self.results["summary"]["failed_servers"] += 1
                logger.error(f"❌ Server {server_name}: FAILED")

        # Calculate final statistics
        self._calculate_summary_stats()

        return self.results

    async def validate_server(self, server_name: str) -> Dict[str, Any]:
        """Validate a specific server with comprehensive tests."""
        server_results = {
            "server_name": server_name,
            "tests": {},
            "overall_success": True,
            "error_count": 0,
            "warning_count": 0
        }

        # Test categories
        test_categories = [
            ("connection", self.test_connection),
            ("security", self.test_security_validation),
            ("commands", self.test_command_execution),
            ("files", self.test_file_operations),
            ("monitoring", self.test_system_monitoring),
            ("services", self.test_service_management),
        ]

        for category_name, test_function in test_categories:
            logger.info(f"Running {category_name} tests for {server_name}")

            try:
                category_results = await test_function(server_name)
                server_results["tests"][category_name] = category_results

                if not category_results.get("success", False):
                    server_results["overall_success"] = False
                    server_results["error_count"] += category_results.get("error_count", 0)

                server_results["warning_count"] += category_results.get("warning_count", 0)

            except Exception as e:
                logger.error(f"Failed {category_name} test for {server_name}: {e}")
                server_results["tests"][category_name] = {
                    "success": False,
                    "error": str(e),
                    "error_count": 1
                }
                server_results["overall_success"] = False
                server_results["error_count"] += 1

        return server_results

    async def test_connection(self, server_name: str) -> Dict[str, Any]:
        """Test basic SSH connection capabilities."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        # Test 1: Basic connection establishment
        test_name = "connection_establishment"
        try:
            conn = await self.connection_manager.get_connection(server_name)
            if conn and conn.is_healthy():
                results["tests"].append({
                    "name": test_name,
                    "status": "PASSED",
                    "message": "Successfully established SSH connection"
                })
                await self.connection_manager.release_connection(conn)
            else:
                results["tests"].append({
                    "name": test_name,
                    "status": "FAILED",
                    "message": "Failed to establish healthy SSH connection"
                })
                results["success"] = False
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": test_name,
                "status": "FAILED",
                "message": f"Connection error: {str(e)}"
            })
            results["success"] = False
            results["error_count"] += 1

        # Test 2: Connection pool health
        test_name = "connection_pool_health"
        try:
            status = self.connection_manager.get_status_all()
            server_status = status.get(server_name, {})

            if server_status and server_status.get("healthy_connections", 0) > 0:
                results["tests"].append({
                    "name": test_name,
                    "status": "PASSED",
                    "message": f"Connection pool healthy: {server_status}"
                })
            else:
                results["tests"].append({
                    "name": test_name,
                    "status": "WARNING",
                    "message": f"Connection pool status: {server_status}"
                })
                results["warning_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": test_name,
                "status": "FAILED",
                "message": f"Pool health check error: {str(e)}"
            })
            results["error_count"] += 1

        return results

    async def test_security_validation(self, server_name: str) -> Dict[str, Any]:
        """Test security validation mechanisms."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        # Get server config for security settings
        server_config = next(s for s in self.config.servers if s.name == server_name)
        validator = SecurityValidator(
            allowed_paths=server_config.allowed_paths,
            additional_blocked_commands=server_config.blocked_commands
        )

        # Test 1: Dangerous command blocking
        dangerous_commands = [
            "rm -rf /",
            "chmod -R 777 /",
            ":(){ :|:& };:",  # Fork bomb
            "sudo passwd root",
            "killall -9 init"
        ]

        for cmd in dangerous_commands:
            test_name = f"block_dangerous_command_{cmd[:10]}"
            try:
                is_valid, reason = validator.validate_command(cmd)
                if not is_valid:
                    results["tests"].append({
                        "name": test_name,
                        "status": "PASSED",
                        "message": f"Correctly blocked dangerous command: {reason}"
                    })
                else:
                    results["tests"].append({
                        "name": test_name,
                        "status": "FAILED",
                        "message": f"Failed to block dangerous command: {cmd}"
                    })
                    results["success"] = False
                    results["error_count"] += 1
            except Exception as e:
                results["tests"].append({
                    "name": test_name,
                    "status": "FAILED",
                    "message": f"Security validation error: {str(e)}"
                })
                results["error_count"] += 1

        # Test 2: Path validation
        dangerous_paths = [
            "/etc/shadow",
            "/root/.ssh/id_rsa",
            "/boot/vmlinuz",
            "/sys/firmware"
        ]

        for path in dangerous_paths:
            test_name = f"block_dangerous_path_{path.replace('/', '_')}"
            try:
                is_valid, reason = validator.validate_path(path)
                if not is_valid:
                    results["tests"].append({
                        "name": test_name,
                        "status": "PASSED",
                        "message": f"Correctly blocked dangerous path: {reason}"
                    })
                else:
                    results["tests"].append({
                        "name": test_name,
                        "status": "WARNING",
                        "message": f"Path allowed (may be intentional): {path}"
                    })
                    results["warning_count"] += 1
            except Exception as e:
                results["tests"].append({
                    "name": test_name,
                    "status": "FAILED",
                    "message": f"Path validation error: {str(e)}"
                })
                results["error_count"] += 1

        return results

    async def test_command_execution(self, server_name: str) -> Dict[str, Any]:
        """Test command execution functionality."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        command_tool = CommandTool(self.connection_manager)

        # Test commands (safe ones)
        test_commands = [
            ("echo_test", "echo 'Hello VPS Manager'", "Hello VPS Manager"),
            ("whoami", "whoami", None),  # Should return username
            ("date", "date", None),      # Should return current date
            ("pwd", "pwd", None),        # Should return current directory
            ("uname", "uname -s", None), # Should return OS name
        ]

        for test_name, command, expected_output in test_commands:
            try:
                result = await command_tool.exec_command(
                    command=command,
                    server=server_name,
                    timeout=10
                )

                if result and result.get("returncode") == 0:
                    stdout = result.get("stdout", "").strip()
                    if expected_output and expected_output not in stdout:
                        results["tests"].append({
                            "name": test_name,
                            "status": "WARNING",
                            "message": f"Command succeeded but output unexpected: {stdout}"
                        })
                        results["warning_count"] += 1
                    else:
                        results["tests"].append({
                            "name": test_name,
                            "status": "PASSED",
                            "message": f"Command executed successfully: {stdout}"
                        })
                else:
                    results["tests"].append({
                        "name": test_name,
                        "status": "FAILED",
                        "message": f"Command failed: {result}"
                    })
                    results["error_count"] += 1

            except Exception as e:
                results["tests"].append({
                    "name": test_name,
                    "status": "FAILED",
                    "message": f"Command execution error: {str(e)}"
                })
                results["error_count"] += 1

        # If any command failed, mark overall as failed
        if results["error_count"] > 0:
            results["success"] = False

        return results

    async def test_file_operations(self, server_name: str) -> Dict[str, Any]:
        """Test file operation functionality."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        file_tool = FileOperationsTool(self.connection_manager)

        # Test file path (should be in allowed directories)
        test_file_path = "/tmp/vps_manager_test.txt"
        test_content = "This is a test file created by VPS Manager validation\\nLine 2\\nLine 3"

        # Test 1: Write file
        try:
            result = await file_tool.write_file(
                path=test_file_path,
                content=test_content,
                server=server_name
            )

            if result and result.get("success"):
                results["tests"].append({
                    "name": "write_file",
                    "status": "PASSED",
                    "message": f"Successfully wrote file: {result.get('bytes_written')} bytes"
                })
            else:
                results["tests"].append({
                    "name": "write_file",
                    "status": "FAILED",
                    "message": f"Failed to write file: {result}"
                })
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "write_file",
                "status": "FAILED",
                "message": f"Write file error: {str(e)}"
            })
            results["error_count"] += 1

        # Test 2: Read file
        try:
            result = await file_tool.read_file(
                path=test_file_path,
                server=server_name
            )

            if result and result.get("content") == test_content:
                results["tests"].append({
                    "name": "read_file",
                    "status": "PASSED",
                    "message": f"Successfully read file: {result.get('size')} bytes"
                })
            else:
                results["tests"].append({
                    "name": "read_file",
                    "status": "FAILED",
                    "message": f"File content mismatch: {result}"
                })
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "read_file",
                "status": "FAILED",
                "message": f"Read file error: {str(e)}"
            })
            results["error_count"] += 1

        # Test 3: List directory
        try:
            result = await file_tool.list_directory(
                path="/tmp",
                server=server_name
            )

            if result and result.get("success"):
                entries = result.get("entries", [])
                test_file_found = any(
                    entry.get("name") == "vps_manager_test.txt"
                    for entry in entries
                )

                if test_file_found:
                    results["tests"].append({
                        "name": "list_directory",
                        "status": "PASSED",
                        "message": f"Successfully listed directory: {len(entries)} entries"
                    })
                else:
                    results["tests"].append({
                        "name": "list_directory",
                        "status": "WARNING",
                        "message": f"Directory listed but test file not found: {len(entries)} entries"
                    })
                    results["warning_count"] += 1
            else:
                results["tests"].append({
                    "name": "list_directory",
                    "status": "FAILED",
                    "message": f"Failed to list directory: {result}"
                })
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "list_directory",
                "status": "FAILED",
                "message": f"List directory error: {str(e)}"
            })
            results["error_count"] += 1

        # Cleanup: Remove test file
        try:
            command_tool = CommandTool(self.connection_manager)
            await command_tool.exec_command(
                command=f"rm -f {test_file_path}",
                server=server_name,
                timeout=5
            )
        except:
            pass  # Ignore cleanup errors

        if results["error_count"] > 0:
            results["success"] = False

        return results

    async def test_system_monitoring(self, server_name: str) -> Dict[str, Any]:
        """Test system monitoring functionality."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        monitoring_tool = SystemMonitoringTool(self.connection_manager)

        # Test system status
        try:
            result = await monitoring_tool.get_system_status(
                server=server_name,
                detailed=True
            )

            if result:
                # Check for expected metrics
                expected_keys = ["cpu", "memory", "disk", "load_average", "uptime"]
                missing_keys = [key for key in expected_keys if key not in result]

                if not missing_keys:
                    results["tests"].append({
                        "name": "system_metrics",
                        "status": "PASSED",
                        "message": f"All system metrics available: {list(result.keys())}"
                    })
                else:
                    results["tests"].append({
                        "name": "system_metrics",
                        "status": "WARNING",
                        "message": f"Some metrics missing: {missing_keys}"
                    })
                    results["warning_count"] += 1

                # Validate metric values
                cpu_usage = result.get("cpu", {}).get("usage_percent", 0)
                memory_total = result.get("memory", {}).get("total_bytes", 0)

                if 0 <= cpu_usage <= 100 and memory_total > 0:
                    results["tests"].append({
                        "name": "metric_validity",
                        "status": "PASSED",
                        "message": f"Metrics appear valid: CPU {cpu_usage}%, Memory {memory_total} bytes"
                    })
                else:
                    results["tests"].append({
                        "name": "metric_validity",
                        "status": "WARNING",
                        "message": f"Metrics may be invalid: CPU {cpu_usage}%, Memory {memory_total} bytes"
                    })
                    results["warning_count"] += 1
            else:
                results["tests"].append({
                    "name": "system_metrics",
                    "status": "FAILED",
                    "message": "No system metrics returned"
                })
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "system_metrics",
                "status": "FAILED",
                "message": f"System monitoring error: {str(e)}"
            })
            results["error_count"] += 1

        if results["error_count"] > 0:
            results["success"] = False

        return results

    async def test_service_management(self, server_name: str) -> Dict[str, Any]:
        """Test service management functionality."""
        results = {"success": True, "tests": [], "error_count": 0, "warning_count": 0}

        service_tool = ServiceManagementTool(self.connection_manager)

        # Test 1: List services
        try:
            result = await service_tool.list_services(
                server=server_name,
                running_only=False
            )

            if result and result.get("services"):
                service_count = len(result["services"])
                results["tests"].append({
                    "name": "list_services",
                    "status": "PASSED",
                    "message": f"Found {service_count} services"
                })

                # Look for common services to test
                common_services = ["ssh", "sshd", "systemd"]
                found_services = [
                    svc["name"] for svc in result["services"]
                    if any(common in svc["name"].lower() for common in common_services)
                ]

                if found_services:
                    results["tests"].append({
                        "name": "common_services_found",
                        "status": "PASSED",
                        "message": f"Found common services: {found_services[:3]}"  # Limit output
                    })
                else:
                    results["tests"].append({
                        "name": "common_services_found",
                        "status": "WARNING",
                        "message": "No common services found (may be normal)"
                    })
                    results["warning_count"] += 1
            else:
                results["tests"].append({
                    "name": "list_services",
                    "status": "FAILED",
                    "message": f"Failed to list services: {result}"
                })
                results["error_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "list_services",
                "status": "FAILED",
                "message": f"Service listing error: {str(e)}"
            })
            results["error_count"] += 1

        # Test 2: Check SSH service status (should exist on all servers)
        try:
            # Try both common SSH service names
            ssh_services = ["ssh", "sshd", "ssh.service", "sshd.service"]
            ssh_status_found = False

            for ssh_service in ssh_services:
                try:
                    result = await service_tool.get_service_status(
                        service_name=ssh_service,
                        server=server_name
                    )

                    if result and result.get("status"):
                        results["tests"].append({
                            "name": "ssh_service_status",
                            "status": "PASSED",
                            "message": f"SSH service ({ssh_service}) status: {result['status']}"
                        })
                        ssh_status_found = True
                        break

                except Exception:
                    continue  # Try next service name

            if not ssh_status_found:
                results["tests"].append({
                    "name": "ssh_service_status",
                    "status": "WARNING",
                    "message": "Could not determine SSH service status"
                })
                results["warning_count"] += 1

        except Exception as e:
            results["tests"].append({
                "name": "ssh_service_status",
                "status": "WARNING",
                "message": f"SSH service check error: {str(e)}"
            })
            results["warning_count"] += 1

        if results["error_count"] > 0:
            results["success"] = False

        return results

    def _calculate_summary_stats(self):
        """Calculate summary statistics."""
        total_tests = 0
        successful_tests = 0
        failed_tests = 0

        for server_name, server_results in self.results["servers"].items():
            for category, category_results in server_results.get("tests", {}).items():
                if isinstance(category_results, dict) and "tests" in category_results:
                    for test in category_results["tests"]:
                        total_tests += 1
                        if test.get("status") == "PASSED":
                            successful_tests += 1
                        elif test.get("status") == "FAILED":
                            failed_tests += 1

        self.results["summary"].update({
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "failed_tests": failed_tests
        })

    def print_summary_report(self):
        """Print a summary report of all validation results."""
        print("\\n" + "="*80)
        print("VPS MANAGER VALIDATION SUMMARY REPORT")
        print("="*80)

        summary = self.results["summary"]
        print(f"Servers: {summary['successful_servers']}/{summary['total_servers']} successful")
        print(f"Tests: {summary['successful_tests']}/{summary['total_tests']} passed")
        print(f"Failed tests: {summary['failed_tests']}")

        print("\\nServer Results:")
        print("-" * 40)

        for server_name, server_results in self.results["servers"].items():
            status = "PASSED" if server_results["overall_success"] else "FAILED"
            error_count = server_results["error_count"]
            warning_count = server_results["warning_count"]

            print(f"{server_name:20} {status} (Errors: {error_count}, Warnings: {warning_count})")

        # Overall result
        overall_success = (
            summary["successful_servers"] == summary["total_servers"] and
            summary["failed_tests"] == 0
        )

        print("\\n" + "="*80)
        if overall_success:
            print("🎉 OVERALL RESULT: ALL VALIDATIONS PASSED!")
        else:
            print("OVERALL RESULT: SOME VALIDATIONS FAILED")
            print("Check the detailed logs above for specific issues.")
        print("="*80)

        return overall_success

    async def cleanup(self):
        """Cleanup resources."""
        if self.connection_manager:
            await self.connection_manager.cleanup()


async def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(
        description="Validate MCP VPS Manager with multiple server configurations"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="tests/configs/test_multiple_servers.yaml",
        help="Path to test configuration file"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to save detailed results JSON"
    )
    parser.add_argument(
        "--server",
        type=str,
        help="Test only specific server (default: test all)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check if config file exists
    if not Path(args.config).exists():
        logger.error(f"Configuration file not found: {args.config}")
        print("\\nCreate a test configuration file or use the default:")
        print("cp tests/configs/test_multiple_servers.yaml your_test_config.yaml")
        return 1

    # Initialize validation suite
    suite = VPSValidationSuite(args.config)

    if not await suite.initialize():
        logger.error("Failed to initialize validation suite")
        return 1

    try:
        # Run validations
        if args.server:
            logger.info(f"Validating single server: {args.server}")
            server_results = await suite.validate_server(args.server)
            suite.results["servers"][args.server] = server_results
            suite.results["summary"]["total_servers"] = 1
            if server_results["overall_success"]:
                suite.results["summary"]["successful_servers"] = 1
            else:
                suite.results["summary"]["failed_servers"] = 1
            suite._calculate_summary_stats()
        else:
            logger.info("Validating all configured servers")
            await suite.validate_all_servers()

        # Print summary
        overall_success = suite.print_summary_report()

        # Save detailed results if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(suite.results, f, indent=2)
            logger.info(f"Detailed results saved to: {args.output}")

        return 0 if overall_success else 1

    except KeyboardInterrupt:
        logger.info("Validation interrupted by user")
        return 1

    except Exception as e:
        logger.error(f"Validation failed with error: {e}")
        return 1

    finally:
        await suite.cleanup()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
