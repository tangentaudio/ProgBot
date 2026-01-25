# ProgBot Development Session - Handoff Documentation

## Executive Summary

This session focused on **Grid Cell Status Display & Terminology** and **Cycle Interruption Logic**. The core achievements were renaming "Commission" to "Provision" throughout the system, fixing cycle interruption behavior to properly distinguish between actively processing vs pending boards, and improving status terminology from "Idle" to "Pending" for better clarity.

**Current Status**: ✅ **MILESTONE COMPLETE** - Grid cell UI layout optimized (20/80 split), provision/test status infrastructure in place, interruption logic properly handles all edge cases.

---

## Work Completed This Session

### 1. Terminology Standardization: "Commission" → "Provision"

**Motivation**: "Commission/Commissioned/Commissioning" was too long for grid cell UI with 12sp font in 15px height rows.

**Changes Applied**:
- Renamed `CommissionStatus` enum to `ProvisionStatus`
- Updated enum values:
  - `COMMISSIONING` → `PROVISIONING`
  - `Commissioned` → `Provisioned`
  - `Commission Failed` → `Provision Failed`
- Renamed field: `commission_status` → `provision_status`
- Renamed method: `_mark_commission()` → `_mark_provision()`
- Updated UI label in `progbot.kv`: `Commission:` → `Provision:`
- Updated default text: `not commissioned` → `not provisioned`
- Updated all related comments and logic throughout codebase

**Files Modified**: `sequence.py`, `kvui.py`, `progbot.kv`

### 2. Grid Cell Layout Optimization (20/80 Split)

**Previous Issue**: With 4 status rows (Probe, Program, Provision, Test) plus Board ID, layout space was exceeded.

**Solution**: Rearranged grid cell layout:
- **Left Column (20% width)**:
  - Board number (24sp, centered)
  - Board ID (11sp, yellow, centered)
    - Shows QR scanned serial number
    - Shows "FAIL" for vision failures
    - Blank when not scanned
    
- **Right Column (80% width)**:
  - 4 status rows (15px height each, 12sp font):
    - Probe status
    - Program status
    - Provision status
    - Test status
  - Each row: Static label (65px, right-aligned, gray) + Value (left-aligned, white)
  - Default text with 50% alpha: "not probed", "not programmed", "not provisioned", "not tested"

**Files Modified**: `progbot.kv`

### 3. Cycle Interruption Logic - Complete Overhaul

**Problem #1**: When stopping a cycle, ALL grid cells turned orange (INTERRUPTED status), including completed boards.

**Root Cause**: Logic was marking IDLE states as INTERRUPTED, and IDLE includes operations that never started on completed boards.

**Problem #2**: Then NONE of the cells were marked as interrupted after excluding IDLE.

**Root Cause**: Logic only marked actively processing operations (PROBING, PROGRAMMING, etc.) as INTERRUPTED, but didn't mark pending operations.

**Problem #3**: Boards with vision failures were being modified during cancellation.

**Root Cause**: Missing check to skip boards that already encountered failures.

**Final Solution** (iterative refinement through 4 deployments):

When cycle is cancelled (CancelledError):
1. Skip disabled boards entirely
2. **Skip boards with any existing failures** (vision, probe, program, provision, or test)
3. For remaining boards, check each operation:
   - **Active states** (PROBING, PROGRAMMING, IDENTIFYING, PROVISIONING, TESTING) → Mark as INTERRUPTED
   - **Terminal states** (FAILED, COMPLETED, SKIPPED) → Leave unchanged
   - **IDLE states** (pending, never started) → Mark as SKIPPED

**Visual Result**:
- Orange cells: Boards actively being processed when stop was pressed
- Red cells: Boards that were pending (had QR scanned but cycle didn't reach them)
- Red cells (unchanged): Boards that already failed at any stage
- Green cells (unchanged): Boards that completed successfully
- Black cells (unchanged): Boards user disabled (hard skip)

**Files Modified**: `sequence.py` (lines 1223-1270 in cancellation handler)

### 4. Vision Failure Status Propagation

**Problem**: When QR scan failed (no QR detected or scan error), only `probe_status` and `program_status` were marked as SKIPPED. The newly added `provision_status` and `test_status` remained in IDLE state.

**Fix**: Added provision and test status to SKIPPED in both failure cases:
- No QR code detected (line ~1124)
- QR scan error/exception (line ~1136)

**Files Modified**: `sequence.py`

### 5. Status Terminology: "Idle" → "Pending"

**Problem**: After QR scan but before a board's turn in the cycle, all operation statuses showed "Idle". This implied nothing was happening, when in reality boards were queued and waiting.

**Solution**: Changed IDLE enum values from "Idle" to "Pending" across all status types:
- `ProgramStatus.IDLE = "Pending"`
- `ProbeStatus.IDLE = "Pending"`
- `VisionStatus.IDLE = "Pending"`
- `ProvisionStatus.IDLE = "Pending"`
- `TestStatus.IDLE = "Pending"`
- Updated `status_text` property defaults from "Idle" to "Pending"

**Result**: Boards waiting their turn now show "Pending" for all operations, clearly indicating they're queued for processing.

**Files Modified**: `sequence.py`

---

## System State & Color Legend

### Grid Cell Color System (12+ Distinct States)

```
┌─────────────────────────────────────────────────────────┐
│ Black [0,0,0,1]         │ Hard skip (user disabled)     │
│ Orange [1,0.5,0,1]      │ Interrupted (cycle stopped)   │
│ Red [1,0,0,1]           │ Failed or soft skip           │
│ Dark red [0.5,0,0,1]    │ QR scan failed                │
│ Purple [1,0,1,1]        │ Identified (QR + device ID)   │
│ Dark green [0,0.5,0,1]  │ Programmed (not yet provisioned) │
│ Medium green [0,0.6,0,1]│ Provisioned (not yet tested)  │
│ Bright green [0,0.8,0,1]│ Tested (final success state)  │
│ Yellow [1,1,0,1]        │ Programming/Identifying       │
│ Light green [0.5,1,0.5,1]│ Provisioning                 │
│ Cyan [0,1,1,1]          │ Probing or Testing            │
│ Light blue [0.5,0.5,1,1]│ Scanning (vision in progress) │
│ Teal [0,0.7,0.7,1]      │ QR Detected                   │
│ Mid-gray [0.5,0.5,0.5,1]│ Default/enabled               │
└─────────────────────────────────────────────────────────┘
```

### Status Progression Through Workflow

```
Initial State: Pending/Pending/Pending/Pending

After QR Scan:
  SUCCESS → QR Detected (teal) → Pending/Pending/Pending/Pending
  FAILURE → No QR (dark red) → Skipped/Skipped/Skipped/Skipped

During Cycle:
  Scanning → Light blue
  Probing → Cyan → Probed/Pending/Pending/Pending
  Programming → Yellow → Probed/Programmed/Pending/Pending (dark green)
  Provisioning → Light green → Probed/Programmed/Provisioned/Pending (medium green)
  Testing → Cyan → Probed/Programmed/Provisioned/Tested (bright green)

If Stopped Mid-Cycle:
  Active operation → INTERRUPTED (orange)
  Pending operations → SKIPPED (red)
  Completed operations → Unchanged (green)
  Failed operations → Unchanged (red/dark red)
```

### Skip States

**Hard Skip** (Black):
- User toggled cell off before cycle
- `enabled = False` in BoardStatus
- Never included in cycle processing

**Soft Skip** (Red):
- Earlier step failed (probe, program, vision)
- Remaining operations marked as SKIPPED
- Allows cycle to continue to other boards

**Interrupted** (Orange):
- Operation was actively running when cycle was stopped
- Shows which board was mid-process
- Only applies to active states (PROBING, PROGRAMMING, IDENTIFYING, PROVISIONING, TESTING)

---

## Architecture: Board Status State Machine

### Status Enums (5 types)

Each board tracks 5 independent status types:

```python
VisionStatus: IDLE/IN_PROGRESS/PASSED/FAILED/INTERRUPTED
ProbeStatus: IDLE/PROBING/COMPLETED/FAILED/SKIPPED/INTERRUPTED  
ProgramStatus: IDLE/IDENTIFYING/IDENTIFIED/PROGRAMMING/COMPLETED/FAILED/SKIPPED/INTERRUPTED
ProvisionStatus: IDLE/PROVISIONING/COMPLETED/FAILED/SKIPPED/INTERRUPTED
TestStatus: IDLE/TESTING/COMPLETED/FAILED/SKIPPED/INTERRUPTED
```

**Note**: IDLE displays as "Pending" to users but remains IDLE internally for state logic.

### BoardStatus Class

```python
class BoardStatus:
    position: (col, row)
    enabled: bool  # False = hard skip (user disabled)
    vision_status: VisionStatus
    probe_status: ProbeStatus
    program_status: ProgramStatus
    provision_status: ProvisionStatus
    test_status: TestStatus
    board_info: BoardInfo  # Contains serial_number from QR
    failure_reason: str  # Why the board failed
    
    @property
    def status_text(self) -> (str, str, str, str):
        # Returns (probe_text, program_text, provision_text, test_text)
        # Includes failure_reason in parentheses for FAILED states
```

### State Transitions

```
VisionStatus Flow:
  IDLE → IN_PROGRESS → PASSED → (continue to probe)
                    ↘ FAILED → mark all operations SKIPPED

ProbeStatus Flow:
  IDLE → PROBING → COMPLETED → (continue to program)
                ↘ FAILED → mark remaining operations SKIPPED

ProgramStatus Flow:
  IDLE → IDENTIFYING → IDENTIFIED → PROGRAMMING → COMPLETED → (continue to provision)
                                                 ↘ FAILED → mark remaining SKIPPED

ProvisionStatus Flow:
  IDLE → PROVISIONING → COMPLETED → (continue to test)
                     ↘ FAILED → mark test SKIPPED

TestStatus Flow:
  IDLE → TESTING → COMPLETED (final state, bright green)
                ↘ FAILED (red)
```

---

## Key Files Modified This Session

### sequence.py
**Lines 173-220**: Status enum definitions
- Changed all `.IDLE` values from "Idle" to "Pending"
- `ProvisionStatus` enum (renamed from `CommissionStatus`)

**Lines 304-350**: BoardStatus class
- Field `provision_status` (renamed from `commission_status`)
- `status_text` property returns 4-tuple for display
- Defaults changed from "Idle" to "Pending"

**Lines 770-780**: Status marking methods
- `_mark_provision()` (renamed from `_mark_commission()`)

**Lines 1118-1140**: QR scan failure handling
- Now marks provision_status and test_status as SKIPPED
- Two cases: No QR detected + QR scan error

**Lines 1223-1270**: Cycle cancellation handler
- Skip boards with any existing failures
- Active operations → INTERRUPTED
- Idle operations → SKIPPED  
- Terminal states → Unchanged

### kvui.py
**Lines 105-108**: GridCell properties
- Comment updated: "provision status" (was "commission status")

**Lines 172-178**: update_status() docstring
- Updated to mention "provision" instead of "commission"

**Lines 190-230**: Color logic
- All references to `commission_status` changed to `provision_status`
- Color priority: disabled > interrupted > test > provision > program > failures > skipped > active > default
- Comments updated with "provisioning" and "provisioned"

### progbot.kv
**Lines 135-157**: Provision status row (was Commission row)
- Label text: `'Provision:'` (was `'Commission:'`)
- Default text: `'not provisioned'` (was `'not commissioned'`)

---

## Testing Checklist

Verified behaviors after all fixes:

✅ **Cycle interruption**: Only actively processing board turns orange
✅ **Pending boards**: Boards with scanned QRs but not yet reached turn red (SKIPPED)
✅ **Failed boards**: Boards that failed vision remain unchanged (dark red)
✅ **Completed boards**: Successfully programmed boards stay green
✅ **Vision failures**: All 4 operations (probe/program/provision/test) marked SKIPPED
✅ **Status display**: Operations show "Pending" when queued, not "Idle"
✅ **Terminology**: "Provision" displays correctly in UI

---

## Deployment

Files synced to Pi at `192.168.0.62:~/progbot/`:
- `sequence.py` (7 deployments during iterative fixes)
- `kvui.py` (1 deployment)
- `progbot.kv` (2 deployments)

```bash
# Final deployment command
cd /home/steve/ProgBot/gui
scp sequence.py kvui.py progbot.kv 192.168.0.62:~/progbot/
```

---

## Previous Session Summary (Vision Calibration)

---

## Previous Session Summary (Vision Calibration)

### 1. Vision Tab in Calibration Dialog

Added a new "Vision" tab to the calibration dialog with:

- **Live Camera Preview** (45% of tab width)
  - 2 FPS frame rate (reduced from 4 to minimize lag)
  - Real-time QR code detection overlay
  - Camera starts when Vision tab is selected, stops when switching away

- **QR Code Detection Display**
  - Shows decoded data when QR detected
  - Displays code type (Standard QR / Micro QR)
  - "No code detected" when nothing found

- **Board Position Selector** (cross-shaped: R+/R-/C+/C-)
  - Navigate between boards in the panel grid
  - Moves camera to QR position for selected board
  - Shows current row/col position

- **XY Jog Controls**
  - Fine position adjustment for centering QR code
  - Step sizes: 0.1, 0.5, 1.0, 5.0 mm
  - Includes camera offset in position calculations

- **Calibration Actions**
  - "Go to QR" - Move to currently configured QR offset
  - "Set QR Offset" - Capture current position as new QR offset

### 2. Settings Synchronization Fix

**The Problem**: Three different settings sources were getting out of sync:
1. **Panel file** (`.panel`) - Source of truth for panel-specific settings
2. **`app.settings_data`** - Cached copy used by Panel tab widgets
3. **`bot.config`** - Runtime configuration used during cycles

Panel tab showed different XYZ origin values than calibration dialog because they read from different sources.

**Root Causes Identified**:
1. Calibration dialog was reading/writing from global `settings.json` instead of panel file
2. Panel-specific values stored as floats in `.panel` but not converted to strings for TextInput widgets
3. `app.settings_data` was a stale cached copy that wasn't updated when calibration dialog saved changes
4. `_config_from_settings()` used stale cache instead of fresh panel data

**Fixes Applied**:

- **calibration_dialog.py**: Changed all reads/writes for panel-specific values (`board_x`, `board_y`, `probe_plane`, `qr_offset_x`, `qr_offset_y`) to use `panel_settings.get()`/`panel_settings.set()` instead of global `settings.get_settings()`

- **calibration_dialog.py**: Now updates `app.settings_data` cache when saving values, keeping it in sync

- **kvui.py**: `_config_from_settings()` now always reads fresh from `panel_settings.get_all()` instead of potentially stale `settings_data` cache

- **kvui.py**: Added explicit `str()` conversion for all TextInput widget assignments to handle float values from panel files

### 3. Fast-Path QR Scanning Optimization

**The Problem**: QR scanning in full cycle took much longer than in Vision tab preview.

**Root Cause**: Vision tab scans frames as they arrive (camera already warm), but full cycle was doing cold scans with delays.

**Fix Applied** (`vision_controller.py`):
- Added `_last_capture_time` tracking
- If camera captured recently (<2s ago), try immediate scan first
- Only fall back to retry logic with delays if immediate scan fails
- Reduced retry delay from 0.3s to 0.2s

### 4. Code Cleanup

- Removed verbose debug logging from `_config_from_settings()` 
- Removed verbose debug logging from `_apply_settings_to_widgets()`
- Removed verbose print statements from `panel_settings.py`
- Kept meaningful debug_log statements for calibration operations and errors

---

## System Architecture Understanding

### Settings Storage (Two Files)

**Global Settings** (`settings.json`) - Machine-specific, same for all panels:
- `motion_port_id`, `head_port_id`, `target_port_id`
- `camera_offset_x`, `camera_offset_y` (tool-to-camera distance)
- `qr_scan_timeout`, `qr_search_offset`
- `contact_adjust_step`
- `last_panel_file` (remembers which panel was loaded)
- `camera_preview_rotation`

**Panel Settings** (`.panel` files) - Panel-specific:
- `board_x`, `board_y` (board origin)
- `probe_plane` (Z offset from probe to board surface)
- `board_cols`, `board_rows`, `col_width`, `row_height`
- `qr_offset_x`, `qr_offset_y` (QR position relative to board origin)
- `operation_mode`, `skip_board_pos`
- `network_core_firmware`, `main_core_firmware`

### Data Flow for Settings

```
Panel File (.panel)
    ↓
PanelSettings.get_all() ──→ settings_data (cached copy)
    ↓                              ↓
panel_settings.get()         TextInput widgets
    ↓                              ↓
Calibration Dialog        Panel Tab Display
    ↓                              ↓
panel_settings.set() ──────→ updates settings_data
    ↓                              ↓
bot.config update          Widget text update
    ↓
_config_from_settings() ──→ Fresh read from panel_settings
    ↓
Full Cycle Execution
```

### Coordinate System

```
Machine Position = Board Origin + Board Offset + QR Offset + Camera Offset

Where:
- Board Origin (board_x, board_y): First board's probe contact point
- Board Offset (col * col_width, row * row_height): Grid position
- QR Offset (qr_offset_x, qr_offset_y): QR code position relative to board origin
- Camera Offset (camera_offset_x, camera_offset_y): Tool-to-camera distance
```

### Camera System

- Runs in separate subprocess for GIL isolation
- 640x480 resolution, 2 FPS preview in calibration
- Supports Standard QR and Micro QR codes via zxingcpp
- Preview frames include detection overlay when QR found

---

## Key Files Modified

### calibration_dialog.py
- Changed all panel-specific reads from `get_settings()` to `panel_settings.get()`
- Changed all panel-specific writes to use `panel_settings.set()` (not attribute assignment)
- Added `app.settings_data` cache updates when saving
- Vision tab movement functions include camera offset

### calibration.kv
- Added Vision tab with camera preview (45%) and controls (55%)
- Board selector cross (R+/R-/C+/C-)
- QR detection display with code type
- XY jog pad anchored right

### kvui.py  
- `_config_from_settings()`: Always reads fresh from `panel_settings`
- `_apply_settings_to_widgets()`: Explicit `str()` conversion for all TextInput values
- Removed verbose debug logging

### panel_settings.py
- Removed verbose print statements from `set()` and `_save_settings()`
- Kept error logging

### vision_controller.py
- Added fast-path scan optimization with `_last_capture_time`
- Added `_preprocess_frame()` for consistent preprocessing

---

## Testing Checklist

After deploying changes, verify:

1. **Settings Sync**: Panel tab and calibration dialog show same XYZ values
2. **Panel Loading**: Loading a different `.panel` file updates all values
3. **Calibration Save**: Setting board origin in calibration updates Panel tab
4. **Full Cycle**: Runtime uses correct values from panel file
5. **Vision Preview**: Camera starts when Vision tab selected
6. **QR Detection**: Codes detected and displayed with type
7. **Board Navigation**: R+/R-/C+/C- buttons move to correct positions

---

## Deployment

Files synced to Pi at `192.168.0.62:~/progbot/`:
- `kvui.py`
- `calibration_dialog.py`
- `calibration.kv`
- `panel_settings.py`
- `vision_controller.py`
- `sequence.py`

```bash
# Deploy command
scp /home/steve/ProgBot/gui/<file> 192.168.0.62:~/progbot/
```

---

## Known State

### Working
- Vision tab with live camera preview
- QR code detection with type display
- Board position selector
- Settings synchronized across Panel tab, calibration, and full cycle
- Fast-path QR scanning
- Panel file loading/saving

### Hardware Configuration (Current Panel: wedge.panel)
```
Board Origin: (109.5, 121.0)
Probe Plane: 4.0 mm
QR Offset: (16.0, 10.0)
Camera Offset: (-50.0, 0.0)
Grid: 2 cols × 5 rows
```

### Performance
- Camera preview: 2 FPS (intentionally limited)
- QR scan: Usually immediate when camera warm
- Serial reads: 1-3s with GUI (known Kivy limitation)

---

## Persistent Connection Architecture (From Previous Session)

**Critical**: Hardware connections persist for app lifetime. Do NOT disconnect between cycles.

- Serial readers: 3 tasks (motion, head, target) - stable count
- Camera subprocess: Stays running between cycles
- `initialize_hardware()`: Called once, idempotent

This architecture was established in previous session and remains unchanged.

---

## Quick Reference

### File Locations
```
Development:  /home/steve/ProgBot/gui/
Production:   steve@192.168.0.62:~/progbot/
Debug Log:    /tmp/debug.txt (on Pi)
```

### Panel-Specific vs Global Settings
```
Panel-specific (in .panel file):
  board_x, board_y, probe_plane
  qr_offset_x, qr_offset_y
  board_cols, board_rows, col_width, row_height
  
Global (in settings.json):
  camera_offset_x, camera_offset_y
  port IDs, baud rates
  qr_scan_timeout, qr_search_offset
```

### Common SSH Commands
```bash
# View debug log
ssh 192.168.0.62 "tail -f /tmp/debug.txt"

# Check panel file
ssh 192.168.0.62 "cat ~/progbot/wedge.panel"

# Sync single file
scp file.py 192.168.0.62:~/progbot/
```

---

*Document updated: January 25, 2026*
*Session focus: Grid cell status display, provision terminology, cycle interruption logic*
*Status: Milestone complete - 4-stage workflow UI foundation ready for provision/test implementation*
