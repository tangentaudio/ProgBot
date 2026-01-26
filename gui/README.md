# ProgBot GUI

DIY ATE on the Cheap

## Project Overview

**ProgBot** is a DIY Automated Test Equipment (ATE) system for programming and testing PCB panels. It's a Python/Kivy application that controls a CNC-like system (typically built on a 3D printer platform) to automatically program multiple circuit boards arranged in a grid pattern.

The system includes **computer vision** capabilities for automatic board identification using QR codes, enabling fully automated panel programming without manual intervention.

## Key Features

### Panel Programming
- Automatically programs a grid of boards (configurable rows/columns)
- BLTouch probe measures board height before contact
- Multiple operation modes:
  - **Identify Only** - Detect devices without programming
  - **Program** - Program firmware
  - **Program & Test** - Program and validate
  - **Test Only** - Test previously programmed devices

### Visual Feedback
Grid cells display real-time status with color coding:
- 🟢 Green = Completed successfully
- 🔴 Red = Failed
- 🟡 Yellow = In-progress
- 🟣 Purple = Identified
- ⬛ Black = Skipped/Disabled
- 🔵 Cyan = Probing

### Computer Vision
- **QR Code Scanning** - Automatic board identification via camera
- **Live Camera Preview** - Real-time camera feed during scanning
- **Crosshair Overlay** - Visual alignment aid for calibration

### Board Management
- Toggle individual board positions on/off
- Save skip patterns per panel configuration
- Enable/disable all boards with single button

### Panel Setup Dialog
- Configure board origin position
- Set grid dimensions (rows, columns)
- Adjust spacing (X pitch, Y pitch)
- **Vision Tab** - Camera-based QR code offset calibration with jogging controls

### Config Settings Dialog
- **General Tab** - Machine and motion settings
- **Probe Tab** - BLTouch probe configuration
- **Camera Tab** - Camera offset calibration with:
  - XY jogging controls (0.1mm, 1mm, 10mm steps)
  - Live camera preview with crosshair
  - Capture/Reset offset functionality
  - Position display relative to board origin

### Smart Device Discovery
- Automatically identifies serial devices by unique ID (serial number, VID:PID:Location)
- GUI-based port selection on first run
- Persistent device mapping across reboots (even if /dev/ttyXXX names change)

### User Interface
- **Dropdown Menu** - Access Load Panel, Panel Setup, Config Settings
- **Touch Screen Support** - Custom numpad keyboard for text input
- **Log Viewer** - Captures all console output in scrollable popup
- **Statistics Popup** - Programming statistics and timing
- **Error Handling** - Popup dialogs with Abort/Retry/Skip options

## Architecture

### Main Components

| File | Description |
|------|-------------|
| `progbot.py` | Entry point with automatic venv management (polyglot bash/Python) |
| `kvui.py` | Main Kivy UI application with grid visualization and controls |
| `progbot.kv` | Main UI layout definition |
| `sequence.py` | Core business logic for the programming/testing sequence |
| `settings.py` | Application-level settings management (JSON-based) |
| `panel_settings.py` | Panel-specific configuration management (.panel files) |

### Hardware Controllers

| File | Description |
|------|-------------|
| `motion_controller.py` | Controls CNC motion (Smoothie/GCode) via serial |
| `head_controller.py` | Controls programmer head (contact detection, power, logic) |
| `programmer_controller.py` | Runs `nrfutil` for device programming (Nordic nRF chips) |
| `target_controller.py` | Communicates with target devices for testing |
| `vision_controller.py` | Camera-based QR code scanning and board identification |
| `device_io.py` | Async serial I/O base layer (asyncio-based) |

### Vision System

| File | Description |
|------|-------------|
| `camera_preview.py` | Camera preview widget for Kivy UI |
| `camera_preview_base.py` | Mixin for crosshair drawing in camera previews |
| `camera_process.py` | Multiprocessing camera capture for performance |
| `vision_controller.py` | QR code detection and board identification |

### Dialog Controllers

| File | Description |
|------|-------------|
| `panel_setup_dialog.py` | Panel setup dialog with vision calibration |
| `panel_setup.kv` | Panel setup dialog layout |
| `config_settings_dialog.py` | Config settings dialog with camera calibration |
| `config_settings.kv` | Config settings dialog layout |
| `jogging_mixin.py` | Reusable XY jogging control mixin |

### Device Discovery

| File | Description |
|------|-------------|
| `device_discovery.py` | Serial device detection and unique identification |
| `serial_port_selector.py` | GUI-based serial port selection dialog |

### Utilities

| File | Description |
|------|-------------|
| `numpad_keyboard.py` | Custom numeric keyboard for touch screen input |
| `panel_file_manager.py` | Panel file load/save management |
| `settings_handlers.py` | Settings UI event handlers mixin |

## Installation

### Prerequisites

- **Python 3.8+** (tested with Python 3.10+)
- **Linux** (designed for Linux systems with /dev/ttyXXX serial ports)
- **nrfutil** - Nordic Semiconductor's command-line tool (for nRF programming)
- **USB Camera** (optional, for vision features)

### Quick Start

The application includes automatic virtual environment management. Simply run:

```bash
cd gui
./progbot.py
```

**First run**: The script will automatically:
1. Create a virtual environment in `./.venv`
2. Install all dependencies from `requirements.txt`
3. Launch the application

**Subsequent runs**: Uses the existing venv immediately (no activation needed).

### Manual Setup

If you prefer manual setup:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python progbot.py
```

Or use the setup script:

```bash
./setup_venv.sh
source .venv/bin/activate
python progbot.py
```

### Dependencies

Core Python packages (see [requirements.txt](requirements.txt)):

- **kivy[base]>=2.0.0** - Cross-platform GUI framework with async support
- **pynnex** - Event emitter/listener system for component communication
- **pyserial-asyncio** - Async serial port communication
- **pyserial** - Serial port enumeration and management
- **opencv-python** - Computer vision (camera capture, image processing)
- **pyzbar** - QR code detection and decoding

### Serial Port Configuration

ProgBot uses **unique identifiers** (USB VID:PID:Location or serial numbers) to identify hardware devices, not device names like `/dev/ttyACM0`. This ensures correct device mapping even when ports enumerate in different orders.

**First Run:** When no port configuration exists, ProgBot will:
1. Display a GUI dialog listing all available serial ports
2. Prompt you to select the correct port for each device:
   - **Motion Controller** (Smoothie CNC board)
   - **Head Controller** (Programmer head/proghead Arduino)
   - **Target Device** (Target UART for testing)
3. Save the unique identifier for each selected port

**Settings Storage:** Device port IDs are stored in `settings.json` as:
- `motion_port_id` - Motion controller unique ID
- `head_port_id` - Head controller unique ID
- `target_port_id` - Target device unique ID

## Usage

### Main Interface

The main screen displays:
- **Left Panel**: Interactive grid showing all board positions
- **Right Panel**: Controls and camera preview

**Top Bar:**
- Panel filename (left)
- Menu button (right) - opens dropdown with:
  - Load Panel
  - Panel Setup
  - Config Settings

**Control Buttons:**
- **HOME** - Home all axes
- **START** - Begin programming sequence
- **STOP** - Stop current operation
- **PAUSE** - Pause/resume sequence

**Bottom Buttons:**
- **All/None** - Enable or disable all boards
- **Log** - Open log viewer popup
- **Stats** - Open statistics popup

**Status Bar:**
- Current phase/status (left)
- Cycle timer (right)

### Panel Setup

Access via Menu → Panel Setup

**Setup Tab:**
- Board Origin X/Y - First board position
- Rows/Columns - Grid dimensions
- X Pitch/Y Pitch - Board spacing
- Probe/No Probe toggle

**Vision Tab:**
- Live camera preview with crosshair
- QR code offset X/Y adjustment
- Jogging controls for precise positioning
- "Capture QR Offset" to save camera-to-probe offset

### Config Settings

Access via Menu → Config Settings

**General Tab:**
- Machine configuration
- Motion parameters

**Probe Tab:**
- BLTouch probe settings
- Z offsets and speeds

**Camera Tab:**
- Live camera preview with crosshair
- Camera offset relative to board origin
- XY jogging controls (0.1/1/10mm steps)
- Capture Offset / Reset Offset buttons
- Instruction text for alignment

### Workflow

1. **Initial Setup** (first run):
   - Select serial ports for Motion, Head, and Target controllers
   - Configure panel settings in Panel Setup dialog
   - Calibrate camera offset in Config Settings → Camera tab

2. **Panel Configuration**:
   - Open Panel Setup dialog
   - Set board origin and grid layout
   - If using vision: calibrate QR offset in Vision tab
   - Save panel configuration

3. **Programming Cycle**:
   - Load appropriate panel file
   - Toggle off any board positions to skip
   - Click START to begin automated sequence
   - Monitor progress via grid colors and status bar

4. **Error Handling**:
   - If an error occurs, popup appears with options:
     - **Abort** - Stop entire sequence
     - **Retry** - Retry current board
     - **Skip** - Skip current board and continue

## Hardware Requirements

### CNC Platform

- **Motion Controller**: Smoothie board or compatible GCode controller
- **BLTouch Probe**: Auto bed leveling probe for board height detection
- **CNC Frame**: Typically based on 3D printer (e.g., Ender 3) modified for PCB programming

### Programmer Head

- **proghead**: Custom Arduino-based programmer head (see [../proghead/](../proghead/))
  - Contact detection
  - Power switching (target power on/off)
  - Logic level translation
- Connects via serial USB

### Camera (Optional)

- USB webcam for vision features
- Mounted to view board surface
- Used for QR code scanning and alignment

### Target Boards

- **Nordic nRF chips** (nRF52, nRF53, etc.)
- Must support programming via SWD/nrfutil
- Optional: UART connection for testing

## Configuration Files

### settings.json

Application-level settings (auto-generated):
- Serial port IDs for all controllers
- Last used panel file
- Camera offset values
- Default firmware paths

### *.panel Files

Panel-specific configurations:
- Grid dimensions (rows, columns)
- Board spacing (X, Y offsets, row/column pitch)
- Operation mode
- Skip board positions
- QR code offset values
- Firmware paths

## Troubleshooting

### Serial Port Issues

- **Device not found**: Check USB connections, verify device is powered
- **Wrong port mapping**: Delete `settings.json` and reselect ports
- **Permission denied**: Add user to dialout group:
  ```bash
  sudo usermod -a -G dialout $USER
  ```
  (Log out and back in for changes to take effect)

### Programming Failures

- **nrfutil not found**: Install nrfutil and ensure it's in PATH
- **Contact failure**: Check programmer head alignment, clean contacts
- **Probe failures**: Check BLTouch connections, adjust probe Z-offset

### Camera Issues

- **Camera not detected**: Check USB connection, verify camera works with other apps
- **Poor QR detection**: Improve lighting, adjust camera focus
- **Wrong camera**: If multiple cameras, may need to adjust camera index

### UI Issues

- **Fullscreen problems**: Edit `kvui.py` to disable fullscreen mode
- **Touch issues**: Ensure Kivy touch drivers are configured
- **Keyboard not working**: Check numpad_keyboard.py configuration

## Development

### Technical Details

- **Framework**: Kivy (async/asyncio) for cross-platform GUI
- **Hardware**: Nordic nRF chips programmed via `nrfutil` CLI
- **Motion**: GCode commands to Smoothie-based CNC controller
- **Vision**: OpenCV + pyzbar for camera capture and QR detection
- **Architecture**: Event-driven with pynnex emitters/listeners

### Code Style

- Python 3 with type hints where appropriate
- Async/await for all I/O operations
- Mixin classes for reusable functionality
- Docstrings for all classes and public methods

### Adding New Features

1. **Hardware control**: Add methods to appropriate controller class
2. **UI elements**: Edit `.kv` files for layout, Python files for logic
3. **Sequence logic**: Modify `sequence.py` for programming flow
4. **Settings**: Update `settings.py` or `panel_settings.py` for persistence
5. **Dialogs**: Create new `*_dialog.py` and `*.kv` file pair

## Related Projects

- **[proghead](../proghead/)** - Arduino firmware for programmer head
- **[smoothie](../smoothie/)** - Smoothie board configuration

## License

DIY project - use and modify as needed.
