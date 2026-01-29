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
- ✅ Header with board number, serial, overall status badge
- ✅ Captured variables from provisioning (middle of header)
- ✅ Failure reason box (red background when error present)
- ✅ Two-column layout:
  - Left (45%): Clickable phase cards with dot + name + timing
  - Right (55%): Detail panel for selected phase
- ✅ All phases shown (enabled phases clickable, disabled phases dimmed)
- ✅ Phase timing displayed next to each phase name
- ✅ Real-time updates (0.25s interval) while popup is open
- ✅ Action buttons: Clear Status, Re-run, Close
- ✅ Buttons disabled during active cycle
- ✅ QR image thumbnail shown in Vision detail view

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
- ✅ **Split BoardDetailPopup into separate file** - board_detail_popup.py (~750 lines)
- ✅ **Extract GridCell to separate module** - gridcell.py + gridcell.kv
- ✅ kvui.py reduced from ~3200 lines to ~2066 lines

---

### ⏳ Remaining / Future Enhancements

#### Code Cleanup / Refactoring (Optional)
- [ ] **Create board_detail_popup.kv** - Move popup layout from Python to KV file for cleaner separation
- [x] **Consolidate status update logic** - Created `board_status.py` as single source of truth for status enums, data classes, and utility functions (status_to_dot, get_phase_color, get_status_bg_color, has_failure, is_processing, etc.)

#### Detail Popup Enhancements
- [x] **Raw Logs** - Collapsible section with detailed output from each phase (BoardInfo now stores phase logs)
- [x] **Captured Variables in Provisioning Detail** - Show captures when Provisioning phase selected
- [x] **Program Phase Detail** - Show device info, firmware version, programmer output
- [x] **Test Phase Detail** - Show test results, pass/fail counts

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

### GridCell Properties (kvui.py)
```python
cell_label = StringProperty("")           # "B1", "B2", etc.
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

### BoardInfo (sequence.py)
```python
class BoardInfo:
    serial_number: Optional[str]      # From QR scan
    qr_image: Optional[bytes]         # PNG bytes of cropped QR
    test_data: dict                   # Provisioning captures
    position: Optional[tuple]         # (col, row)
    timestamp_qr_scan: Optional[str]
    timestamp_probe: Optional[str]
    timestamp_program: Optional[str]
    probe_result: Optional[bool]
    program_result: Optional[bool]
    notes: str
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
- `board_detail_popup.py` - BoardDetailPopup class
- `sequence.py` - BoardStatus, BoardInfo, CycleStats, status signals
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
