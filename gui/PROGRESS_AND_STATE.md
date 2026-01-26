# ProgBot Development Session - Handoff Documentation

## Executive Summary

This session focused on **Panel Setup Dialog Overhaul** - a complete redesign of the calibration dialog into a multi-tab "Panel Setup" dialog with buffered editing semantics (Save/Cancel), proper unsaved changes confirmation, and significant UX improvements.

**Current Status**: ✅ **MILESTONE COMPLETE** - Panel Setup dialog fully functional with 5 tabs (General, Origins, Jog, Program, Vision), edit buffer system with Save/Cancel, unsaved changes confirmation dialog, and all bugs fixed.

---

## Work Completed This Session

### 1. Major Refactoring: Calibration → Panel Setup

**File Renames**:
- `calibration_dialog.py` → `panel_setup_dialog.py`
- `calibration.kv` → `panel_setup.kv`

**Nomenclature Changes**:
- All `cal_` prefixes renamed to `ps_` (panel setup)
- Widget IDs: `cal_board_x` → `ps_board_x`, etc.
- Methods: `cal_on_board_x_change()` → `ps_on_board_x_change()`, etc.
- Files affected: `panel_setup_dialog.py`, `panel_setup.kv`, `kvui.py`

### 2. Edit Buffer System Implementation

**Core Architecture**:
- `_edit_buffer` - Dict holding all pending changes
- `_original_values` - Deep copy of initial state for dirty comparison
- `_is_dirty` - Boolean flag triggering Save button enable/disable

**Buffer Methods**:
```python
_set_buffer_value(key, value)      # Set top-level value
_set_buffer_nested(key, subkey, value)  # Set nested value (e.g., programmer settings)
_get_buffer_value(key)             # Get from buffer or panel_settings
_get_buffer_nested(key, subkey)    # Get nested value
_check_dirty()                     # Compare buffer to original using JSON serialization
```

**Dirty Detection**:
- Uses JSON serialization for deep equality comparison
- Handles nested dicts (programmer settings) correctly
- Updates UI on main thread via `Clock.schedule_once()`

### 3. Save/Cancel Button Behavior

**Save Button**:
- Disabled until changes detected (`_is_dirty = True`)
- On click: Writes all buffer values to `panel_settings`, clears dirty state
- Becomes disabled again after successful save

**Cancel Button**:
- Always enabled
- On click: Discards buffer, resets `_is_dirty`, closes dialog (with safe-Z check)

### 4. Unsaved Changes Confirmation Dialog

**Trigger**: Closing dialog (X button or Cancel) when `_is_dirty = True`

**Three Options**:
- **Save & Close**: Save changes, then close dialog
- **Discard**: Discard changes, close dialog
- **Cancel**: Stay in dialog, keep editing

**Implementation Details**:
- Dialog size: 600×250 with 22sp font
- `close()` method checks dirty state, shows confirmation if needed
- `_do_close()` handles actual close with safe-Z movement

### 5. Bug Fixes

**Save Button Not Activating on TextInput Changes**:
- **Problem**: TextInputs only fired `on_text_validate` (Enter key), not on blur
- **Solution**: Added `on_focus` handlers that call change handlers when focus lost

**Button Actions Not Triggering Dirty State**:
- **Problem**: `set_board_origin()`, `capture_probe_offset()`, `vision_set_qr_offset()` wrote directly to panel_settings, bypassing buffer
- **Solution**: Changed to write to buffer via `_set_buffer_value()`

**Unsaved Changes Dialog Not Appearing**:
- **Problem**: Duplicate `close()` method at line ~1063 was overriding proper implementation
- **Solution**: Removed duplicate, merged safe-Z logic into `_do_close()`

**Vision Tab Camera Not Starting**:
- **Problem**: If Vision tab already selected from previous session, `on_state` won't fire
- **Solution**: Added `_check_vision_tab_selected()` called 0.1s after dialog opens

**Step Selector Out of Sync**:
- **Problem**: Internal `_jog_step` variable reset to default but toggle button persisted from previous session
- **Solution**: Added `_sync_step_selectors_from_ui()` to read button states on open

### 6. Origins Tab Layout Redesign

**Previous Issue**: Row-by-row layout with inconsistent button/input widths

**New Structure**:
```
┌─────────────────────────────────────────────────────────────┐
│ [GridLayout 2×4]          │ [GridLayout 2×2]                │
│                           │                                 │
│ [Go Home]  [Go Contact]   │ Origin X: [____] Origin Y: [____]│
│ [Set Origin] [Set Offset] │ Z Offset: [____]                │
│ [Probe]      [Spacer]     │                                 │
│ [Go Safe Z] [Clear Error] │                                 │
├─────────────────────────────────────────────────────────────┤
│ Position:  X: 123.4  Y: 567.8  Z: 90.1   Probe: 45.67      │
└─────────────────────────────────────────────────────────────┘
```

**Benefits**:
- Uniform button sizing via GridLayout
- Cleaner visual alignment
- Better use of horizontal space

---

## Tab Structure (5 Tabs)

### General Tab
- Panel name display
- Board dimensions (cols, rows, width, height)
- Operation mode selector
- Skip board position

### Origins Tab
- Motion control buttons (Go Home, Go Contact, Set Origin, etc.)
- Origin X/Y inputs
- Z Offset (probe plane) input
- Real-time position display
- Probe result display

### Jog Tab
- XYZ position display
- XYZ jog pads with step selector
- Step sizes: 0.1, 0.5, 1.0, 5.0 mm
- Separate step selectors for XY and Z

### Program Tab
- Programmer selection (from `programmers/` module)
- Per-programmer settings (e.g., J-Link serial, firmware paths)
- Device selection dropdown

### Vision Tab
- Live camera preview (45% width)
- QR code detection display
- Board position selector (R+/R-/C+/C-)
- XY jog controls for centering
- QR offset capture button

---

## File State Summary

### panel_setup_dialog.py (~1848 lines)
- Complete buffer infrastructure
- All `ps_` prefix naming
- 5-tab dialog with proper lifecycle management
- Camera start/stop on Vision tab selection
- Unsaved changes confirmation

### panel_setup.kv (~1040 lines)
- GridLayout structure for Origins tab
- All widget IDs use `ps_` prefix
- `on_focus` handlers on TextInputs
- TabbedPanel with 5 tabs

### kvui.py (~1619 lines)
- All `ps_on_*_change()` handlers call buffer setters
- `ps_close()` calls `panel_setup_controller.close()`
- All `ps_` prefix naming

### programmers/ (New Module)
- `__init__.py` - Programmer registry
- `base.py` - BaseProgrammer abstract class
- `nordic_nrf.py` - Nordic nRF5x programmer implementation

---

## Architecture: Edit Buffer Flow

```
User Input (TextInput, Button, etc.)
    ↓
ps_on_*_change() handler (kvui.py)
    ↓
panel_setup_controller._set_buffer_value(key, value)
    ↓
_edit_buffer[key] = value
    ↓
_check_dirty()  →  JSON compare with _original_values
    ↓
_is_dirty = True  →  Clock.schedule_once(update_save_button)
    ↓
Save button enabled

[User clicks Save]
    ↓
save_settings()
    ↓
for key, value in _edit_buffer.items():
    panel_settings.set(key, value)
    ↓
panel_settings._save_settings()  →  Write to .panel file
    ↓
_original_values = deep_copy(_edit_buffer)
_is_dirty = False
    ↓
Save button disabled
```

---

## Git Commit History (Recent)

```
89b5f33 (HEAD) milestone- reworked panel setup dialog with many tabs
2ac6e65         wip rework panel setup dialog
9d55d63         checkpoint move stats to dialog, add cycle timer
a57e83a         bunch of Sonnet-fugue with grid cell aesthetics and provision/test states
```

**Milestone Commit (89b5f33)** includes:
- File renames (calibration → panel_setup)
- Buffer system implementation
- All bug fixes
- Layout redesign
- Nomenclature cleanup (cal_ → ps_)

---

## Deployment

Files synced to Pi at `192.168.0.62:~/progbot/`:
- `panel_setup_dialog.py`
- `panel_setup.kv`
- `kvui.py`
- `progbot.kv`
- `sequence.py`
- `panel_settings.py`
- Programmer module files

```bash
# Deploy command
cd /home/steve/ProgBot/gui
python3 -m py_compile panel_setup_dialog.py && scp panel_setup_dialog.py 192.168.0.62:~/progbot/
```

**Note**: Old `calibration_dialog.cpython-312.pyc` removed from `__pycache__` to prevent stale bytecode issues.

---

## Testing Checklist

Verified behaviors after all fixes:

✅ **Save button activation**: Enables when any value changes
✅ **TextInput blur**: Triggers dirty check when focus leaves field
✅ **Button actions**: Set Origin, Probe Offset, QR Offset all trigger dirty
✅ **Unsaved changes dialog**: Appears on close when dirty
✅ **Save & Close**: Saves then closes
✅ **Discard**: Closes without saving
✅ **Cancel**: Stays in dialog
✅ **Vision tab camera**: Starts even if tab already selected
✅ **Step selector sync**: Reads toggle state on dialog open
✅ **Layout alignment**: Buttons and inputs properly aligned

---

## Previous Session Work (Preserved)

### Grid Cell Status System
- 4 status rows: Probe, Program, Provision, Test
- Color-coded states (green=success, red=failed, orange=interrupted)
- "Pending" instead of "Idle" for queued operations
- Terminology: "Commission" → "Provision"

### Cycle Interruption Logic
- Active operations → INTERRUPTED (orange)
- Pending operations → SKIPPED (red)
- Completed/Failed → Unchanged
- Boards with existing failures skipped during cancellation marking

### Vision/QR System
- Camera subprocess for GIL isolation
- Fast-path scanning when camera warm
- zxingcpp for Standard/Micro QR detection
- 2 FPS preview in Vision tab

### Settings Synchronization
- Panel-specific settings in `.panel` files
- Global settings in `settings.json`
- `panel_settings` module for panel file access
- Settings cache (`app.settings_data`) kept in sync

---

## System Architecture

### Coordinate System
```
Machine Position = Board Origin + Board Offset + QR Offset + Camera Offset

Where:
- Board Origin (board_x, board_y): First board's probe contact point
- Board Offset (col * col_width, row * row_height): Grid position
- QR Offset (qr_offset_x, qr_offset_y): QR code position relative to board origin
- Camera Offset (camera_offset_x, camera_offset_y): Tool-to-camera distance
```

### Hardware Connections
- Serial readers: 3 persistent tasks (motion, head, target)
- Camera subprocess: Stays running between cycles
- `initialize_hardware()`: Called once, idempotent

### Color Legend (Grid Cells)
```
Black [0,0,0,1]         - Hard skip (user disabled)
Orange [1,0.5,0,1]      - Interrupted (cycle stopped)
Red [1,0,0,1]           - Failed or soft skip
Dark red [0.5,0,0,1]    - QR scan failed
Purple [1,0,1,1]        - Identified (QR + device ID)
Dark green [0,0.5,0,1]  - Programmed (not yet provisioned)
Medium green [0,0.6,0,1]- Provisioned (not yet tested)
Bright green [0,0.8,0,1]- Tested (final success state)
Yellow [1,1,0,1]        - Programming/Identifying
Cyan [0,1,1,1]          - Probing or Testing
Light blue [0.5,0.5,1,1]- Scanning (vision in progress)
Mid-gray [0.5,0.5,0.5,1]- Default/enabled
```

---

## Quick Reference

### File Locations
```
Development:  /home/steve/ProgBot/gui/
Production:   steve@192.168.0.62:~/progbot/
Debug Log:    /tmp/debug.txt (on Pi)
```

### Key Widget IDs (Panel Setup)
```
ps_board_x, ps_board_y       - Origin inputs
ps_probe_plane               - Z offset input
ps_qr_offset_x, ps_qr_offset_y - QR offset inputs
ps_step_selector             - Jog step toggle group
ps_save_button               - Save button (enable/disable based on dirty)
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

# Deploy single file
scp file.py 192.168.0.62:~/progbot/

# Compile check before deploy
python3 -m py_compile panel_setup_dialog.py && scp panel_setup_dialog.py 192.168.0.62:~/progbot/

# Clear debug log before test
ssh 192.168.0.62 "echo '' > /tmp/debug.txt"
```

---

*Document updated: January 25, 2026*
*Session focus: Panel Setup Dialog overhaul with buffered editing and Save/Cancel semantics*
*Status: Milestone complete - Dialog fully functional with all bugs fixed*
