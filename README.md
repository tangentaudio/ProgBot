# ProgBot
DIY ATE on the Cheap

## Project Overview

**ProgBot** is a DIY Automated Test Equipment (ATE) system for programming and testing PCB panels. It's a Python/Kivy application that controls a CNC-like system (generally built on a 3D printer platform) to automatically program multiple circuit boards arranged in a grid.

### Core Architecture

**Main Components:**

1. **progbot.py** - Entry point that launches the async Kivy application
2. **kvui.py** - Main Kivy UI application with grid visualization and controls
3. **sequence.py** - Core business logic for the programming/testing sequence
4. **settings.py** - Application-level settings management
5. **panel_settings.py** - Panel-specific configuration management

**Hardware Controllers:**

- **motion_controller.py** - Controls CNC motion (Smoothie/GCode via `/dev/ttyACM0`)
- **head_controller.py** - Controls programmer head (contact, power, logic via `/dev/ttyUSB0`)
- **programmer_controller.py** - Runs `nrfutil` for device identification and programming
- **target_controller.py** - Communicates with target devices for testing (via `/dev/ttyACM1`)
- **device_io.py** - Async serial I/O base layer

**UI/UX:**

- **progbot.kv** - Kivy UI layout with grid display, settings panel, and status
- **numpad_keyboard.py** - Custom numeric keyboard for touch screen input

### Key Features

1. **Panel Programming**: Automatically programs a grid of boards (configurable rows/columns)
2. **Probing**: Uses BLTouch probe to measure board height before contact
3. **Visual Feedback**: Grid cells show status with color coding:
   - Green = Success
   - Red = Fail
   - Yellow = In-progress
   - Purple = Identified
   - Black = Skipped
   - Cyan = Probing
4. **Operation Modes**: 
   - Identify Only
   - Program
   - Program & Test
   - Test Only
5. **Board Skipping**: Can mark specific board positions to skip
6. **Panel Configurations**: Save/load different panel layouts (.panel files)
7. **Error Handling**: Popup with Abort/Retry/Skip options on errors
8. **Log Viewer**: Captures all console output in a popup

### Technical Details

- **Framework**: Kivy (async/asyncio) for cross-platform GUI
- **Hardware**: Nordic chips (nRF) programmed via `nrfutil`
- **Motion**: GCode commands to Smoothie board
- **Architecture**: Event-driven with pynnex emitters/listeners for component communication
- **Configuration**: JSON-based settings files (settings.json, *.panel)

## Setup

### Virtual Environment Setup

Use the provided setup script to create a virtual environment and install dependencies:

```bash
./setup_venv.sh
```

Or manually:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Dependencies

- **Kivy** - Cross-platform GUI framework
- **pynnex** - Event emitter/listener system
- **pyserial-asyncio** - Async serial port communication

### External Tools

- **nrfutil** - Nordic Semiconductor's command-line tool for programming nRF devices (must be installed separately)

## Usage

### Running the Application

The `progbot.py` script includes automatic venv management - it will:
1. Check if a virtual environment exists in `./.venv`
2. If not found, automatically create the venv and install dependencies
3. Run the application using the venv Python

Simply run:

```bash
./progbot.py
```

**First run**: The script will automatically set up the virtual environment (equivalent to running `./setup_venv.sh`)

**Subsequent runs**: The script will use the existing venv immediately

This polyglot bash/Python wrapper eliminates the need to manually run setup or activate the venv before launching the application.

The application will launch in fullscreen mode and connect to the configured hardware devices.