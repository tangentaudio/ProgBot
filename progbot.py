#!/usr/bin/env python3
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

