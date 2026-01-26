# ProgBot

DIY Automated Test Equipment (ATE) on the Cheap

## Overview

ProgBot is a DIY ATE system built from commonly available components: repurposed 3D printer mechanicals, Raspberry Pi with touchscreen and camera, an Arduino nano, and an off-the-shelf target microcontroller programmer. It automates In-System Programming (ISP), provisioning, and testing of circuit boards arranged in a panel.

A CNC motion system drives spring-loaded "pogo" contacts into position on each board to establish power and communication connections. An optional camera enables automatic board identification via QR codes, used to assign ID or serial numbers to each board and track them for later stages of assembly.

## Components

| Directory | Description |
|-----------|-------------|
| [gui/](gui/) | Python/Kivy touchscreen application - controls the system, displays status |
| [proghead/](proghead/) | Arduino firmware for the programmer head (contact detection, power control) |
| [smoothie/](smoothie/) | Configuration for the Smoothie motion controller |

## Hardware

- **Controller** - Raspberry Pi with touchscreen running the GUI.
- **Motion System** - 3-axis 3D printer frame with motion controller, BLTouch probe.
- **Camera** - Raspberry Pi Camera Module (native picamera2 support) or USB webcam for QR code scanning.
- **Programmer Head** - Arduino controller, pogo pin contacts, reed relays to sequence power and logic signals, electrical means of determining board contact.  Mechanically, the programmer head also includes the camera and BLTouch probe, though they are part of other systems electrically and logically.
- **Programmer** - An appropriate programmer (e.g. SWD or JTAG) for the microcontroller on the target boards.

## Quick Start

```bash
cd gui
./progbot.py
```

See [gui/README.md](gui/README.md) for detailed setup instructions.

## Development

The starting point for this project was a hand-written Python program controlling the hardware elements. The entire GUI and features such as vision-based QR scanning were developed using significant AI-assistance via GitHub Copilot and Claude Sonnet 4.5 and Claude Opus 4.5.  This project serves as a test project for the vibe-coding workflow, and as such the code quality may benefit or suffer accordingly.

## License

MIT License - see [LICENSE](LICENSE) for details.