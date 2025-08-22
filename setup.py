#!/usr/bin/env python
"""
Setup script for MCP VPS Manager

This provides setuptools compatibility for systems that prefer setup.py
over pyproject.toml. The primary configuration is still in pyproject.toml.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = []
with open('requirements.txt', 'r', encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="mcp-vps-manager",
    version="0.2.0",
    description="A secure, production-ready MCP server for managing Virtual Private Servers via SSH",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Meeru",
    author_email="asifur.rahaman@meeru.dev",
    maintainer="Meeru",
    maintainer_email="asifur.rahaman@meeru.dev",
    url="https://github.com/your-org/mcp-vps-manager",
    project_urls={
        "Homepage": "https://github.com/your-org/mcp-vps-manager",
        "Repository": "https://github.com/your-org/mcp-vps-manager",
        "Documentation": "https://github.com/your-org/mcp-vps-manager/wiki",
        "Bug Tracker": "https://github.com/your-org/mcp-vps-manager/issues",
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "": ["*.yaml", "*.json", "*.md"],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-mock>=3.10.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "mcp-vps-manager=vps_manager.server:main",
        ],
    },
    scripts=[
        "bin/mcp-vps-manager",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Environment :: Console",
    ],
    keywords="mcp vps ssh server management claude ai",
    zip_safe=False,
)
