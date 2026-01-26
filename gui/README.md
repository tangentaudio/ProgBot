# ProgBot GUI

A Python/Kivy application for automated PCB panel programming and testing.

## Overview

ProgBot controls a CNC-like system to automatically program multiple circuit boards arranged in a grid pattern. It uses a BLTouch probe for height sensing, supports camera-based QR code scanning for board identification, and communicates with Nordic nRF devices via nrfutil.

## Requirements

- **Linux** (designed for Raspberry Pi or similar)
- **Python 3.8+**
- **nrfutil** - Nordic's programming tool (install separately)
- **USB Camera** (optional, for QR scanning)

## Installation

### Quick Start

The application manages its own virtual environment. Simply run:

```bash
./progbot.py
```

On first run, this will:
1. Create a virtual environment in `.venv/`
2. Install dependencies from `requirements.txt`
3. Launch the application

### Manual Setup

```bash
./setup_venv.sh
source .venv/bin/activate
python progbot.py
```

### Dependencies

See [requirements.txt](requirements.txt) for the full list. Key packages:
- kivy - GUI framework
- pyserial-asyncio - Serial communication
- opencv-python - Camera capture
- zxing-cpp - QR/barcode detection

## Hardware

- **Motion Controller** - Smoothie or GCode-compatible CNC board
- **Programmer Head** - Custom Arduino (see [../proghead/](../proghead/))
- **BLTouch Probe** - For board height detection
- **USB Camera** - For QR code scanning (optional)

## Usage

1. Run `./progbot.py`
2. On first run, select serial ports for your hardware
3. Load or configure a panel file
4. Use START to begin the programming sequence

## Troubleshooting

**Permission denied on serial ports:**
```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in.

**Reset port configuration:**
Delete `settings.json` and restart to re-select ports.

## Related

- [proghead](../proghead/) - Programmer head Arduino firmware
- [smoothie](../smoothie/) - Motion controller configuration
