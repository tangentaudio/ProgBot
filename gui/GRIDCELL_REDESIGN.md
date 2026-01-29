# Grid Cell Redesign Spec

## Implementation Status

### ✅ Completed Features

#### Grid Cell Layout
- ✅ Board number (large, top-left)
- ✅ Result icon (✔/✘) next to board number for pass/fail
- ✅ Serial number from QR scan (bottom-left)
- ✅ 5 status dots (V/C/P/S/T) in bottom-right for Vision, Contact, Program, Setup, Test
- ✅ Failure reason text below serial when applicable

#### Status Dots
- ✅ Unicode checkbox indicators: ☑ (pass), ☒ (fail), ☐ (pending)
- ✅ Braille spinner animation for in-progress phases (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏)
- ✅ Disabled phases show as dim dot (·)
- ✅ Font: DejaVuSans for proper Unicode glyph rendering

#### Cell Background Colors
- ✅ Dark gray for pending/idle
- ✅ Green for all phases passed
- ✅ Red for any phase failed
- ✅ Black for skipped boards
- ✅ Pulsing animation when board is actively processing

#### Interaction Model
- ✅ Tap: Opens detail popup
- ✅ Long-press (0.5s): Toggle skip/enable

#### Board Detail Popup
- ✅ Header with "Board N [col,row]", serial, overall status badge
- ✅ Captured variables from provisioning (middle of header)
- ✅ Failure reason box (red background when error present)
- ✅ Two-column layout:
  - Left (45%): Clickable phase cards with dot + name + timing
  - Right (55%): Detail panel for selected phase (scrollable)
- ✅ All phases shown (enabled phases clickable, disabled phases dimmed)
- ✅ Phase timing displayed next to each phase name
- ✅ Real-time updates (0.25s interval) while popup is open
- ✅ Action buttons: Clear Status, Re-run, Close
- ✅ Buttons disabled during active cycle
- ✅ QR image thumbnail shown in Vision detail view (dynamically added/removed)

#### Detail Panel Content
- ✅ **Vision**: QR data, serial, model, scan log, QR thumbnail image
- ✅ **Contact**: Probe test result, probe log
- ✅ **Program**: Device ID, firmware version, programmer output log
- ✅ **Provisioning**: Status, captured variables, provisioning log with step descriptions
- ✅ **Test**: Test results, test log
- ✅ **Color-coded text**: Headers (blue), keys (gold), values (gray), success (green), failure (red)
- ✅ **Monospace font** for log entries and captured values (DejaVuSansMono.ttf)

#### Data Flow
- ✅ sequence.py emits board_status_changed signal with status updates
- ✅ kvui.py handles signal to update grid cells
- ✅ Spinner animations run via Clock.schedule_interval
- ✅ ThreadPoolExecutor for non-blocking subprocess calls (smoother animations)
- ✅ Unified _reset_cell_status() helper for consistent clearing

#### Timing & Stats
- ✅ Per-board timing recorded for: qr_scan, probe, program, provision
- ✅ Timing accessible via bot.stats.board_times[(col, row)]
- ✅ Timing displayed in popup phase cards and detail panel

#### QR Image Capture
- ✅ scan_qr_code returns (data, cropped_png_bytes) tuple
- ✅ BoardInfo.qr_image stores cropped QR thumbnail (max 128px)
- ✅ Image displayed in Vision detail view

#### Code Cleanup / Refactoring
- ✅ **Split BoardDetailPopup into separate file** - board_detail_popup.py (~1000 lines)
- ✅ **Extract GridCell to separate module** - gridcell.py + gridcell.kv
- ✅ **Created board_status.py** - Central module for status enums (VisionStatus, ProbeStatus, ProgramStatus, ProvisionStatus, TestStatus), BoardInfo class with phase logs, BoardStatus class
- ✅ kvui.py reduced from ~3200 lines to ~2066 lines

#### Bug Fixes This Session
- ✅ Fixed duplicate serial number handling in device_discovery (include location in unique_id)
- ✅ Fixed phase card click handling (on_release vs on_press for ButtonBehavior)
- ✅ Fixed ScrollView text wrapping (bind width only, not full size)
- ✅ Fixed image layout (dynamic add/remove instead of hidden widget taking space)
- ✅ Fixed monospace font path for Kivy markup (requires full path, not family name)

---

### ⏳ Remaining / Future Enhancements

#### Code Cleanup / Refactoring (Optional)
- [ ] **Create board_detail_popup.kv** - Move popup layout from Python to KV file for cleaner separation

#### Visual Polish
- [ ] Consider color-coding dots (currently shape-only, monochrome)
- [ ] In-progress dot could be half-filled (◐) instead of spinner for less visual noise

#### Export Features
- [ ] Export board results to CSV with all captured data
- [ ] Generate QR stickers/labels with pass/fail status

#### Multi-board Operations
- [ ] Batch re-run for failed boards only
- [ ] Select multiple boards for batch operations

---

## Technical Reference

### GridCell Properties (gridcell.py)
```python
cell_label = StringProperty("")           # "0", "1", etc.
serial_number = StringProperty("")        # QR scan result
result_icon = StringProperty("")          # "✔" or "✘"
failure_reason = StringProperty("")       # Error message

# Status dots
vision_dot = StringProperty("·")          # ☑☒☐· or spinner
contact_dot = StringProperty("·")
program_dot = StringProperty("·")
provision_dot = StringProperty("·")
test_dot = StringProperty("·")

# Phase enabled flags
vision_enabled = BooleanProperty(True)
contact_enabled = BooleanProperty(True)
program_enabled = BooleanProperty(True)
provision_enabled = BooleanProperty(True)
test_enabled = BooleanProperty(True)
```

### BoardInfo (board_status.py)
```python
class BoardInfo:
    serial_number: Optional[str]      # From QR scan
    serial: Optional[str]             # Alias
    model: Optional[str]              # Board model
    qr_image: Optional[bytes]         # PNG bytes of cropped QR
    test_data: dict                   # Provisioning captures
    position: Optional[tuple]         # (col, row)
    
    # Phase logs for detail display
    vision_log: List[str]
    probe_log: List[str]
    program_log: List[str]
    provision_log: List[str]
    test_log: List[str]
    
    # Device info
    device_id: Optional[str]
    firmware_version: Optional[str]
```

### Status Enums (board_status.py)
```python
class VisionStatus(Enum):
    IDLE, SCANNING, SCANNED, NO_QR, FAILED

class ProbeStatus(Enum):
    IDLE, TESTING, PASSED, FAILED, SKIPPED

class ProgramStatus(Enum):
    IDLE, PROGRAMMING, COMPLETED, IDENTIFIED, FAILED, SKIPPED

class ProvisionStatus(Enum):
    IDLE, RUNNING, COMPLETED, FAILED, SKIPPED

class TestStatus(Enum):
    IDLE, RUNNING, PASSED, FAILED, SKIPPED
```

### CycleStats Timing (sequence.py)
```python
# Per-board timing
stats.board_times[(col, row)] = {
    'qr_scan': float,    # Vision phase duration
    'probe': float,      # Contact/probe phase duration
    'program': float,    # Programming phase duration
    'provision': float,  # Provisioning phase duration
}

# Aggregate stats
stats.qr_scan_stats  # (min, avg, max)
stats.probe_stats
stats.program_stats
```

### Key Files
- `kvui.py` - Main UI module (imports GridCell and BoardDetailPopup)
- `gridcell.py` - GridCell widget class
- `gridcell.kv` - GridCell KV layout
- `board_detail_popup.py` - BoardDetailPopup class with phase detail builders
- `board_status.py` - Status enums, BoardInfo, BoardStatus data classes
- `sequence.py` - Provisioning sequence with status signals and log capture
- `device_discovery.py` - Serial port enumeration with duplicate handling
- `progbot.kv` - Main app KV layout
- `vision_controller.py` - QR scanning with image capture

---

## Design Decisions Made

1. **Status dots use shapes, not colors** - Cell background already indicates overall status
2. **Long-press for skip toggle** - Avoids accidental skips, keeps tap for details
3. **Real-time popup updates** - User can watch status change during cycle
4. **Disabled phases visible but dimmed** - User aware of what's not running
5. **QR image captured at scan time** - Available for review/debugging later
6. **Two-column detail layout** - Phase list left, context-sensitive detail right
7. **Dynamic image widget** - Add/remove instead of hiding to avoid layout issues
8. **Monospace for data values** - Technical values (MAC, serial, logs) in fixed-width font for clarity
9. **Color-coded markup** - Visual hierarchy with headers, keys, values, success/failure colors
