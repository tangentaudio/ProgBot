# Performance Debug Log

## Problem Description
After running a cycle (fully or stopped midway), the system becomes very unresponsive:
- UI freezes or becomes sluggish
- Cannot cleanly exit the application
- Ctrl-C from shell takes many attempts
- Problem has returned and is worse than before

## Previous Investigation Areas
1. Camera init/deinit
2. Async serial I/O
3. Motion system response delays

## Debug Session - January 26, 2026

### Step 1: Identify Resource Leaks and Blocking Operations

#### Current Hypothesis
After a cycle ends or is stopped, there may be:
- Background tasks/threads not properly cancelled
- Serial port read loops blocking
- Camera processes not fully terminated
- Asyncio event loop congestion

### Areas to Investigate

#### 1. Serial Port Handling
- Check for blocking reads in serial controllers
- Look for threads that may not be properly stopped
- Examine timeout settings

#### 2. Camera/Vision Controller
- Check process termination
- Look for zombie processes
- Examine cleanup sequence

#### 3. Asyncio Task Management
- Check for uncancelled tasks
- Look for tasks waiting on I/O that never completes
- Examine task cleanup on stop

#### 4. Motion Controller
- Check for blocking waits
- Examine queue management
- Look for response timeouts

---

## Investigation Progress

### [16:15] Starting Investigation

**Examined stop() handling in kvui.py:**
- stop() calls bot.cancel() which raises CancelledError in full_cycle
- CancelledError handler in sequence.py handles cleanup

### [16:20] Key Findings

#### Finding 1: gc.collect() in CancelledError handler
In [sequence.py](sequence.py#L1428), there's a `gc.collect()` call inside the CancelledError handler.

The vision_controller.py already has a comment about this problem:
```python
# Skip garbage collection - it causes stop-the-world pause that breaks serial connections!
# gc.collect() pauses ALL threads including serial reader, making motion controller
# think connection is dead and reconnect (causing slow first read)
```

**PROBLEM**: The gc.collect() at line 1428 in sequence.py is called when the cycle is cancelled, and this can cause:
- UI freeze while GC runs
- Serial readers to be starved, causing timeouts
- Motion controller reconnects

#### Finding 2: Serial reader task lifecycle
In device_io.py, the `_run_reader()` task runs continuously with `while True`.
The task properly handles connection close (breaks on empty readline() or exception).
This looks OK.

#### Finding 3: Camera cleanup looks OK
VisionController.disconnect() has proper timeouts and force-kill handling.
CameraProcess.stop() has escalating termination (event → join → terminate → kill).

### [16:25] Proposed Fix

Remove the gc.collect() call from the CancelledError handler in sequence.py line 1428.
This should prevent the freeze when stopping a cycle.

### [16:30] Additional Investigation

Check if there are any other blocking sync operations or long-running tasks that
might be causing issues.

### [16:35] Applied Fixes

**Fix 1: Removed gc.collect() from sequence.py line 1428:**
- This was causing stop-the-world pauses when cancelling cycles
- Python's automatic GC will handle cleanup without blocking the event loop
- Also removed unused `import gc`

**Fix 2: Wrapped blocking process.join() in executor in vision_controller.py:**
- The force-kill path had a synchronous `process.join(timeout=0.3)` call
- This could block the event loop for up to 300ms
- Now wrapped in `run_in_executor` to keep the event loop responsive
### [17:00] Additional Fix - Orphaned Asyncio Tasks

**Root Cause Found:**
The pynnex signal system was emitting to dead receivers (receiver alive: False), creating
orphaned asyncio tasks that pile up. The `stats_updated` signal was being emitted frequently
during cycles, and when the cycle ended, the receiver (AsyncApp) could be partially garbage
collected while emissions were still queued.

**Fix 3: Added `_cycle_active` flag and `_safe_emit_stats()` helper:**

In sequence.py:
- Added `self._cycle_active = False` flag in __init__
- Added `_safe_emit_stats()` method that only emits if `_cycle_active` is True
- Set `_cycle_active = True` at start of `full_cycle()`
- Set `_cycle_active = False` in all exit paths (success, cancel, exception)
- Replaced all `self.stats_updated.emit()` calls with `self._safe_emit_stats()`

In kvui.py:
- Added signal disconnect in `_on_task_complete()` to disconnect `stats_updated`
- Added signal reconnect in `_do_start()` before starting new cycle
- This ensures proper signal lifecycle management between cycles

### [17:30] Additional Fix - Pynnex Debug Logging Overhead

**Root Cause:**
Kivy's logging configuration was causing pynnex's trace loggers to have effective level 0 
(NOTSET), meaning ALL debug and trace messages were being processed and printed. This 
includes detailed emit traces with timing information, creating significant overhead.

**Fix 4: Suppress pynnex debug logging:**

In kvui.py, added early logger configuration before importing pynnex:
```python
logging.getLogger('pynnex').setLevel(logging.WARNING)
logging.getLogger('pynnex.emitter').setLevel(logging.WARNING)
logging.getLogger('pynnex.listener').setLevel(logging.WARNING)
logging.getLogger('pynnex.emitter.trace').setLevel(logging.WARNING)
logging.getLogger('pynnex.listener.trace').setLevel(logging.WARNING)
```

**Fix 5: Guard all frequent signal emissions:**

Extended `_cycle_active` guard to:
- `_emit_status()` - guards `board_status_changed` signal
- `update_phase()` - guards `phase_changed` signal

This prevents any signal emissions after the cycle ends, avoiding orphaned asyncio tasks.

### [18:00] Additional Fixes - UI Logging Overhead

**Root Cause Found:**
Every print() statement goes through OutputCapture → LogViewer → TextInput, which:
1. Appends text to TextInput.text (triggers layout recalculation)
2. Schedules Clock.schedule_once for scroll_to_bottom
3. TextInput grows unbounded, getting slower to render over time

**Fix 6: Remove print statements from high-frequency listeners:**

Removed print() from:
- `on_board_status_change()` - called for every cell status update
- `on_phase_change()` - called frequently during cycle  
- `on_panel_change()` - not frequent but noisy
- `on_cell_color_change()` - called for every cell color update
- `on_qr_scan_started()` / `on_qr_scan_ended()`

**Fix 7: Limit log text size and debounce scrolling:**

In LogViewer.write():
- Added MAX_LINES = 500 limit to prevent unbounded text growth
- Debounced scroll_to_bottom() calls to 100ms to reduce Clock events
- Fixed potential infinite recursion if print() fails

**Added Diagnostics:**
- `dump_diagnostics()` function logs asyncio task count and Kivy Clock events
- Called in `_on_task_complete()` to help debug what's accumulating
### [16:40] Additional Findings

1. **vision_controller._gc_collect()** - Dead code, never called (cleanup candidate)
2. **sequence.check_device()** - Dead code with blocking subprocess.run, never called
3. **stop() doesn't await task completion** - cancel() is called but not awaited
   - Could cause issues if cleanup takes time
   - The start() handler has logic to wait for previous task, but stop() returns immediately

### [16:45] Recommended Testing

1. Deploy the fix to the Pi
2. Run a full cycle and let it complete normally
3. Run a cycle and stop it midway
4. Check if UI remains responsive after both scenarios
5. Check if Ctrl-C works cleanly to exit

### Next Steps (if problem persists)

1. Add instrumentation to measure time spent in each cleanup phase
2. Check for zombie camera processes: `ps aux | grep camera`
3. Check for stuck asyncio tasks with debugging tools
4. Look at serial port reconnect behavior after gc.collect removal

---

## Summary of Changes (January 26, 2026)

### Root Causes Identified:

1. **gc.collect() Stop-the-World Pause**
   - `gc.collect()` in the CancelledError handler caused all threads to freeze
   - Serial reader threads starved, causing connection timeouts and reconnects
   - UI completely unresponsive during GC pause

2. **Blocking process.join() in Camera Cleanup**
   - Synchronous `process.join(timeout=0.3)` blocked the asyncio event loop
   - Up to 300ms freeze during camera cleanup

3. **Orphaned Asyncio Tasks from Pynnex Signals**
   - `stats_updated` signal emitted to dead receivers after cycle ended
   - Created orphaned tasks that accumulated over multiple cycles

4. **Pynnex Debug Logging Overhead**
   - Kivy's logging configuration left pynnex loggers at NOTSET (level 0)
   - ALL trace messages processed, creating significant overhead

5. **TextInput._refresh_text() Cumulative Slowdown**
   - Every `print()` → OutputCapture → LogViewer → TextInput.text append
   - TextInput grew unbounded, layout recalculation got progressively slower
   - Each cycle added ~1000+ lines, making the 5th+ cycle noticeably sluggish

### Files Modified:

1. **logger.py** (NEW)
   - Centralized Python logging configuration
   - `RotatingFileHandler` → `/tmp/progbot.log` (5MB max, 3 backups)
   - Format: `[HH:MM:SS.mmm] [LEVEL] [module] message`
   - `setup_logging()` called once at startup
   - `get_logger(__name__)` for per-module loggers
   - Suppresses noisy Kivy/pynnex/PIL loggers to WARNING

2. **kvui.py**
   - `OutputCapture` class routes `print()` → `log.info()` (not TextInput)
   - `LogViewer` tails `/tmp/progbot.log` with level filtering
   - Log filter toggle buttons: DEBUG / INFO / WARNING / ERROR
   - Removed pynnex debug logging before imports
   - Removed all 35+ direct `print()` statements → `log.*()` calls
   - Signal disconnect/reconnect lifecycle in `_on_task_complete()`/`start()`

3. **sequence.py**
   - Removed `import gc` and `gc.collect()` call
   - Added `_cycle_active` flag to guard signal emissions
   - Added `_safe_emit_stats()` helper method
   - Converted all `print()`/`debug_log()` → `log.*()` calls

4. **vision_controller.py**
   - Wrapped `process.join()` in `run_in_executor` (non-blocking)
   - Converted all `print()` statements → `log.*()` calls

5. **device_io.py, motion_controller.py, head_controller.py, target_controller.py, camera_preview.py**
   - All converted to use `from logger import get_logger`
   - Replaced `print()`/`debug_log()` with `log.*()` calls

6. **qr_debug_dialog.py**
   - Replaced `from device_io import debug_log` → `from logger import get_logger`
   - Converted `debug_log()` → `log.debug()` calls

### Logging Architecture:

```
┌─────────────────────────────────────────────────────────┐
│                     Application Code                     │
│  log.debug(), log.info(), log.warning(), log.error()   │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    Python logging                        │
│              (RotatingFileHandler)                       │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              /tmp/progbot.log                            │
│       (5MB max, 3 backups, rotated automatically)        │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    LogViewer Widget                      │
│      (tails file, filters by level, updates on timer)   │
└─────────────────────────────────────────────────────────┘
```

### Key Design Decisions:

1. **File-based logging instead of TextInput**
   - Decouples logging from UI rendering
   - No cumulative slowdown from TextInput._refresh_text()
   - Logs persist across app restarts for debugging
   - LogViewer reads on demand, not on every write

2. **Level filtering in UI**
   - Toggle buttons filter what's displayed (not what's logged)
   - All levels always written to file
   - Users can switch between DEBUG/INFO/WARNING/ERROR views

3. **OutputCapture still captures print()**
   - Existing print() calls still work (routed to log.info)
   - Third-party library prints captured
   - Graceful migration path

### Testing Checklist:

- [x] Run a full cycle and let it complete normally
- [x] Run a cycle and stop it midway with Stop button
- [x] Check UI responsiveness after both scenarios
- [x] Verify Ctrl-C cleanly exits the application
- [x] Check for zombie camera processes after stopping
- [x] Run 5+ consecutive cycles without slowdown
- [x] Log viewer filters work correctly
- [x] Log file rotates at 5MB

### Future Improvements:

1. Consider adding log level to settings (persistent preference)
2. Add "Export Log" button to save log file for support
3. Add timestamp-based filtering (last hour, today, etc.)
4. Consider structured logging (JSON) for machine parsing

