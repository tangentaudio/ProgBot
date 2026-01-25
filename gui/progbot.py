#!/bin/bash
''''
SCRIPT_DIR="$(dirname "$0")"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

# Check if venv exists, if not create it
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Virtual environment not found. Creating it now..."
    if [ -f "$SCRIPT_DIR/setup_venv.sh" ]; then
        bash "$SCRIPT_DIR/setup_venv.sh" || exit 1
    else
        echo "Creating venv manually with system site packages..."
        python3 -m venv --system-site-packages "$SCRIPT_DIR/.venv" || exit 1
        "$VENV_PYTHON" -m pip install --upgrade pip
        if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
            "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" || exit 1
        fi
    fi
fi

# Run with venv python
exec "$VENV_PYTHON" "$0" "$@"
# '''
"""
ProgBot - Main entry point for the application.

This module serves as the main entry point, instantiating and running the Kivy application.
"""

import sys
import os
import asyncio

# Add the current directory to the path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kvui import AsyncApp


def main():
    """Main entry point for the ProgBot application."""
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(AsyncApp().app_func())
        loop.close()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

