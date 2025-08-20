#!/bin/bash
export PATH="/Users/asifurrahaman/Development/tired-of-ideas/mcp-vps-manager/venv/bin:$PATH"
export PYTHONPATH="/Users/asifurrahaman/Development/tired-of-ideas/mcp-vps-manager/src"
cd "/Users/asifurrahaman/Development/tired-of-ideas/mcp-vps-manager"
python -m vps_manager.server --config config/servers.yaml --log-level INFO 2>/dev/null
