#!/bin/bash
# MCP VPS Manager Runner Script

# Activate virtual environment
source venv/bin/activate

# Run the MCP server
python -m vps_manager.server --config config/servers.yaml "$@"
