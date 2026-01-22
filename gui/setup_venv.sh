#!/bin/bash
# Setup script for ProgBot virtual environment

set -e  # Exit on error

echo "=== ProgBot Virtual Environment Setup ==="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python version: $PYTHON_VERSION"

# Create virtual environment
if [ -d ".venv" ]; then
    echo ""
    read -p "Virtual environment already exists. Recreate it? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing venv..."
        rm -rf .venv
    else
        echo "Using existing venv..."
    fi
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo ""
echo "Installing dependencies..."
echo "  - Kivy (GUI framework)"
pip install kivy[base]

echo "  - pynnex (event system)"
pip install pynnex

echo "  - pyserial-asyncio (async serial communication)"
pip install pyserial-asyncio

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
echo "To run ProgBot:"
echo "  source .venv/bin/activate"
echo "  ./progbot.py"
echo ""
echo "To deactivate the virtual environment:"
echo "  deactivate"
