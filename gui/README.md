# ProgBot GUI
DIY ATE on the Cheap

## Project Overview

**ProgBot** is a DIY Automated Test Equipment (ATE) system for programming and testing PCB panels. It's a Python/Kivy application that controls a CNC-like system (typically built on a 3D printer platform) to automatically program multiple circuit boards arranged in a grid pattern.

### Core Architecture

**Main Components:**

1. **progbot.py** - Entry point with automatic venv management (polyglot bash/Python)
2. **kvui.py** - Main Kivy UI application with grid visualization and controls (~1365 lines)
3. **sequence.py** - Core business logic for the programming/testing sequence (~659 lines)
4. **settings.py** - Application-level settings management (JSON-based)
5. **panel_settings.py** - Panel-specific configuration management (.panel files)

**Hardware Controllers:**

- **motion_controller.py** - Controls CNC motion (Smoothie/GCode) via serial
- **head_controller.py** - Controls programmer head (contact detection, power, logic)
- **programmer_controller.py** - Runs `nrfutil` for device identification and programming (Nordic nRF chips)
- **target_controller.py** - Communicates with target devices for testing
- **device_io.py** - Async serial I/O base layer (asyncio-based)

**Device Discovery:**

- **device_discovery.py** - Serial device detection and unique identification
- **serial_port_selector.py** - GUI-based serial port selection dialog

**UI/UX:**

- **progbot.kv** - Kivy UI layout with grid display, settings panel, and status
- **numpad_keyboard.py** - Custom numeric keyboard for touch screen input

### Key Features

1. **Panel Programming**: Automatically programs a grid of boards (configurable rows/columns)
2. **Probing**: Uses BLTouch probe to measure board height before contact
3. **Visual Feedback**: Grid cells display real-time status with color coding:
   - Green = Completed successfully
   - Red = Failed
   - Yellow = In-progress
   - Purple = Identified
   - Black = Skipped/Disabled
   - Cyan = Probing
4. **Operation Modes**: 
   - Identify Only - Detect devices without programming
   - Program - Program firmware
   - Program & Test - Program and validate
   - Test Only - Test previously programmed devices
5. **Board Management**: 
   - Toggle individual board positions on/off
   - Save skip patterns per panel configuration
6. **Panel Configurations**: 
   - Save/load different panel layouts (.panel files)
   - Store grid dimensions, spacing, operation mode, and skip patterns
7. **Smart Device Discovery**: 
   - Automatically identifies serial devices by unique ID (serial number, VID:PID:Location)
   - GUI-based port selection on first run
   - Persistent device mapping across reboots (even if /dev/ttyXXX names change)
8. **Error Handling**: Popup dialogs with Abort/Retry/Skip options on errors
9. **Log Viewer**: Captures all console output in a scrollable popup window
10. **Touch Screen Support**: Custom numpad keyboard for text input on touch displays

### Technical Details

- **Framework**: Kivy (async/asyncio) for cross-platform GUI with fullscreen mode
- **Hardware**: Nordic nRF chips programmed via `nrfutil` command-line tool
- **Motion**: GCode commands to Smoothie-based CNC controller
- **Architecture**: Event-driven with pynnex emitters/listeners for component communication
- **Configuration**: 
  - JSON-based settings files (settings.json for app, *.panel for panel configs)
  - Unique device identification using serial numbers or USB port locations
- **Serial Communication**: 
  - AsyncSerialDevice base class (device_io.py)
  - Auto-reconnection and command retry logic
  - DevicePortManager for persistent device mapping

### File Structure

```
gui/
├── progbot.py                 # Main entry point (polyglot bash/Python)
├── kvui.py                    # Kivy UI application (~1365 lines)
├── progbot.kv                 # UI layout definition
├── sequence.py                # Programming sequence logic (~659 lines)
├── settings.py                # Application settings
├── panel_settings.py          # Panel configuration management
│
├── device_io.py               # Async serial I/O base class
├── device_discovery.py        # Serial device detection (~175 lines)
├── serial_port_selector.py    # GUI port selection dialog (~156 lines)
│
├── motion_controller.py       # CNC motion control (~101 lines)
├── head_controller.py         # Programmer head control (~60 lines)
├── programmer_controller.py   # nrfutil programming (~91 lines)
├── target_controller.py       # Target device testing (~55 lines)
│
├── numpad_keyboard.py         # Touch screen keyboard
├── requirements.txt           # Python dependencies
├── setup_venv.sh             # Virtual environment setup script
├── settings.json             # Application settings (auto-generated)
├── default.panel             # Default panel configuration
└── README.md                 # This file
```

## Setup

### Prerequisites

- **Python 3** (tested with 3.x)
- **nrfutil** - Nordic Semiconductor's command-line tool for programming nRF devices (must be installed separately)
- **Linux** (designed for Linux systems with /dev/ttyXXX serial ports)

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

Core Python packages (see [requirements.txt](requirements.txt)):

- **kivy[base]>=2.0.0** - Cross-platform GUI framework with async support
- **pynnex** - Event emitter/listener system for component communication
- **pyserial-asyncio** - Async serial port communication
- **pyserial** - Serial port enumeration and management

### Serial Port Configuration

ProgBot uses **unique identifiers** (USB VID:PID:Location or serial numbers) to identify hardware devices, not device names like `/dev/ttyACM0`. This ensures correct device mapping even when ports enumerate in different orders.

**First Run:** When no port configuration exists, ProgBot will:
1. Display a GUI dialog listing all available serial ports with their details
2. Prompt you to select the correct port for each device:
   - **Motion Controller** (Smoothie CNC board)
   - **Head Controller** (Programmer head/proghead Arduino)
   - **Target Device** (Target UART for testing)
3. Save the unique identifier (e.g., `USB:2341:0043:1-1.4` or `SN:ABC123`) for each selected port

**Subsequent Runs:** ProgBot will automatically find the correct devices by their saved unique identifiers, even if the `/dev/ttyXXX` names change after a reboot.

**Manual Port Selection:** If a configured device isn't found (e.g., unplugged or changed), you'll be prompted to select it again from the available ports.

**Settings Storage:** Device port IDs are stored in `settings.json` as:
- `motion_port_id` - Motion controller unique ID
- `head_port_id` - Head controller unique ID  
- `target_port_id` - Target device unique ID

## Usage

### Running the Application

The [progbot.py](progbot.py) script includes **automatic venv management** - it's a polyglot bash/Python script that:
1. Checks if a virtual environment exists in `./.venv`
2. If not found, automatically creates the venv and installs dependencies (runs `setup_venv.sh`)
3. Runs the application using the venv Python interpreter

Simply run:

```bash
./progbot.py
```

**First run**: The script will automatically set up the virtual environment and install all dependencies

**Subsequent runs**: The script will use the existing venv immediately (no activation needed)

This eliminates the need to manually run setup or activate the venv before launching the application.

### Application Workflow

1. **Initial Setup** (first run only):
   - Select serial ports for Motion Controller, Head Controller, and Target Device
   - Configure panel settings (grid dimensions, spacing, firmware paths)

2. **Panel Configuration**:
   - Adjust grid layout (rows, columns, spacing)
   - Set operation mode (Identify Only, Program, Program & Test, Test Only)
   - Toggle individual board positions on/off as needed
   - Save configuration to a .panel file for reuse

3. **Programming Cycle**:
   - Click "Start" to begin the automated programming sequence
   - The system will:
     - Home the CNC axes (if configured)
     - Probe each board position to determine height
     - Contact each board and perform the selected operation
     - Display real-time status in the grid view
   - Monitor progress via the color-coded grid and log viewer

4. **Error Handling**:
   - If an error occurs, a popup will appear with options:
     - **Abort**: Stop the entire sequence
     - **Retry**: Retry the current board
     - **Skip**: Skip the current board and continue

### UI Controls

- **Start/Stop/Pause**: Control the programming sequence
- **Load/Save Panel**: Manage panel configurations
- **Settings Panel**: Configure grid layout, operation mode, firmware paths
- **Log Viewer**: View captured console output
- **Grid View**: Interactive grid showing board status (click cells to toggle on/off)

### Configuration Files

- **settings.json**: Application-level settings (auto-generated)
  - Serial port IDs
  - Last used panel file
  - Default firmware paths

- **\*.panel**: Panel-specific configurations
  - Grid dimensions (rows, columns)
  - Board spacing (X, Y offsets, row/column pitch)
  - Operation mode
  - Skip board positions
  - Firmware paths

The application will launch in fullscreen mode and connect to the configured hardware devices.

## Architecture Details

### Event System

ProgBot uses **pynnex** for event-driven communication between components:
- Controllers emit events (e.g., status updates, errors)
- UI components listen for events and update displays
- Decouples hardware control from UI logic

### Async/Await Pattern

All hardware operations use Python's asyncio:
- **AsyncSerialDevice** (device_io.py): Base class for async serial communication
- **Controllers**: All controller methods are async (await-able)
- **Sequence**: Main programming loop runs as an async task
- **Kivy**: Uses `AsyncApp` for integration with asyncio event loop

### Device Classes

Each hardware component has a dedicated controller class:

1. **MotionController** - GCode-based motion control
   - Methods: `init()`, `home()`, `move_to()`, `probe()`, `retract_probe()`
   - Sends GCode commands, waits for 'ok' responses

2. **HeadController** - Programmer head operations
   - Methods: `check_contact()`, `set_power()`, `set_logic()`
   - Controls contact detection, power switching, logic level shifting

3. **ProgrammerController** - Firmware operations via nrfutil
   - Methods: `identify()`, `program_network_core()`, `program_main_core()`
   - Runs nrfutil as subprocess, captures output

4. **TargetController** - Target device testing
   - Methods: `test()`, `create_monitor_task()`
   - Sends test commands, monitors UART output

### State Management

- **BoardStatus**: Tracks individual board state (ProbeStatus, ProgramStatus)
- **Config**: Dataclass holding all configuration parameters
- **Settings/PanelSettings**: JSON-based persistent storage

### UI Components

- **GridCell**: Custom Kivy widget for interactive board grid
- **OutputCapture**: Redirects stdout/stderr to log viewer
- **SerialPortSelector**: Modal dialog for port selection
- **NumpadKeyboard**: Custom keyboard for touch screen

## Hardware Requirements

### CNC Platform

- **Motion Controller**: Smoothie board or compatible GCode controller
- **BLTouch Probe**: Auto bed leveling probe for board height detection
- **CNC Frame**: Typically based on 3D printer (e.g., Ender 3) modified for PCB programming

### Programmer Head

- **proghead**: Custom Arduino-based programmer head (see ../proghead/)
  - Contact detection
  - Power switching (target power on/off)
  - Logic level translation
- Connects via serial (typically /dev/ttyUSB0)

### Target Boards

- **Nordic nRF chips** (nRF52, nRF53, etc.)
- Must support programming via SWD/nrfutil
- Optional: UART connection for testing

## Troubleshooting

### Serial Port Issues

- **Device not found**: Check USB connections, verify device is powered
- **Wrong port mapping**: Delete `settings.json` and reselect ports
- **Permission denied**: Add user to dialout group: `sudo usermod -a -G dialout $USER`

### Programming Failures

- **nrfutil not found**: Install nrfutil and ensure it's in PATH
- **Contact failure**: Check programmer head alignment, clean contacts
- **Probe failures**: Check BLTouch connections, adjust probe Z-offset

### UI Issues

- **Fullscreen problems**: Edit kvui.py to disable fullscreen mode
- **Keyboard not working**: Try switching keyboard layout with settings button
- **Log viewer empty**: Check OutputCapture initialization in kvui.py

## Development

### Code Style

- Python 3 with type hints where appropriate
- Async/await for all I/O operations
- Docstrings for all classes and public methods

### Testing

- Manual testing with hardware setup required
- Test panel configurations in `*.panel` files
- Monitor console output via Log Viewer

### Adding New Features

1. Hardware control: Add methods to appropriate controller class
2. UI elements: Edit `progbot.kv` for layout, `kvui.py` for logic
3. Sequence logic: Modify `sequence.py` for programming flow
4. Settings: Update `settings.py` or `panel_settings.py` for persistence

## License

DIY project - use and modify as needed.

## Related Projects

- **proghead** (../proghead/): Arduino firmware for programmer head
- **smoothie** (../smoothie/): Smoothie board configuration