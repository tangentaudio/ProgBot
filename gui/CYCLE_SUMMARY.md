# Cycle Summary & Data Export

## Overview

ProgBot focuses on:
1. **Gather cycle data** - Collect results and captured variables during each run
2. **Display summary** - Show pass/fail counts and failed board list after cycle
3. **Simple exports** - CSV/JSON export for downstream use
4. **Clean hooks** - Interface for future integration with external systems

**Out of scope:** ProgBot does NOT own the board registry database. That's a separate system we'll integrate with later.

---

## Implementation Status

### ✅ PHASE 1: COMPLETE

- **cycle_summary.py** - Data classes and popup widget
  - `BoardResult` dataclass with serial, position, result, failure info, captured data
  - `CycleSummary` dataclass with counts, yield calculation, CSV/JSON export methods
  - `CycleResultHandler` ABC for integration hooks
  - `NullHandler` and `FileExportHandler` implementations
  - `CycleSummaryPopup` Kivy widget with stats display
  - `build_cycle_summary()` helper to convert board_statuses to CycleSummary

- **kvui.py integration**
  - Summary popup shows automatically when cycle completes (not when cancelled)
  - "Re-run Failed" button enables only failed cells and starts new cycle
  - "Export CSV" button exports to `gui/exports/` directory

### Remaining Work

- Real-time `on_board_complete` hook (called as each board finishes)
- JSON export option in popup
- Toast/notification for export success
- External system integration examples

---

## Decisions Made

- **QR serial** is the primary key for tracking boards through assembly
- **Captured variables** don't need to be searchable - just stored and exported
- **Database ownership** belongs to a separate system; ProgBot is a data source
- **Integration** will be via hooks/callbacks, filled in when external system is defined

---

## Immediate Implementation

### 1. CycleSummary Data Class

Collect all results at cycle end:

```python
@dataclass
class CycleSummary:
    """Results from a completed programming cycle."""
    
    timestamp: datetime
    panel_name: str
    duration_seconds: float
    
    # Counts
    total_boards: int
    passed_count: int
    failed_count: int
    skipped_count: int
    
    # Per-board results
    boards: List[BoardResult]
    
    @property
    def yield_percent(self) -> float:
        if self.total_boards == 0:
            return 0.0
        return (self.passed_count / self.total_boards) * 100

@dataclass  
class BoardResult:
    """Result for a single board."""
    serial: str                      # QR serial (primary identifier)
    position: tuple                  # (col, row)
    result: str                      # "PASSED", "FAILED", "SKIPPED"
    failure_reason: Optional[str]    # If failed
    failure_phase: Optional[str]     # Which phase failed
    captured_data: dict              # All captured variables (mac, bt_addr, etc.)
    phase_times: dict                # Timing per phase
```

### 2. Summary Popup (UI)

Show after cycle completes:

```
┌─────────────────────────────────────────────────┐
│  CYCLE COMPLETE                         [Close] │
├─────────────────────────────────────────────────┤
│                                                 │
│   ✓ 12 Passed    ✗ 2 Failed    ○ 1 Skipped    │
│                                                 │
│   Duration: 4m 32s    Yield: 85.7%             │
│                                                 │
├─────────────────────────────────────────────────┤
│  FAILED BOARDS:                                 │
│                                                 │
│  Board 3 [0,2] - SN-00123                      │
│    Vision: No QR code detected                  │
│                                                 │
│  Board 6 [1,1] - SN-00456                      │
│    Program: Device not responding               │
│                                                 │
├─────────────────────────────────────────────────┤
│  [Re-run Failed]  [Export CSV]  [Done]         │
└─────────────────────────────────────────────────┘
```

### 3. Export Formats

**CSV** - One row per board:
```csv
serial,position,result,failure_phase,failure_reason,mac,bt_addr,firmware
SN-00001,"0,0",PASSED,,,AA:BB:CC:DD:EE:FF,12:34:56:78:90:AB,v1.2.3
SN-00002,"0,1",FAILED,Program,Device not responding,,,
```

**JSON** - Full cycle data:
```json
{
  "timestamp": "2026-01-29T14:30:00",
  "panel": "MyPanel",
  "duration": 272.5,
  "summary": {"total": 15, "passed": 12, "failed": 2, "skipped": 1},
  "boards": [
    {"serial": "SN-00001", "result": "PASSED", "captured": {"mac": "AA:BB:..."}}
  ]
}
```

### 4. Integration Hooks

Abstract interface for future external system integration:

```python
class CycleResultHandler(ABC):
    """Base class for handling cycle results.
    
    Subclass this to integrate with external systems:
    - HTTP API
    - Database
    - Message queue
    - etc.
    """
    
    @abstractmethod
    async def on_cycle_complete(self, summary: CycleSummary) -> None:
        """Called when a cycle finishes."""
        pass
    
    @abstractmethod
    async def on_board_complete(self, result: BoardResult) -> None:
        """Called when each board finishes (for real-time updates)."""
        pass


class NullHandler(CycleResultHandler):
    """Default no-op handler."""
    async def on_cycle_complete(self, summary): pass
    async def on_board_complete(self, result): pass


class FileExportHandler(CycleResultHandler):
    """Export to CSV/JSON files."""
    
    def __init__(self, export_dir: str, format: str = 'csv'):
        self.export_dir = export_dir
        self.format = format
    
    async def on_cycle_complete(self, summary: CycleSummary):
        filename = f"{summary.timestamp:%Y%m%d_%H%M%S}_cycle.{self.format}"
        path = os.path.join(self.export_dir, filename)
        if self.format == 'csv':
            self._write_csv(path, summary)
        else:
            self._write_json(path, summary)
    
    async def on_board_complete(self, result): 
        pass  # Only export at end


# Future: implement when external system is defined
class ApiHandler(CycleResultHandler):
    """POST results to HTTP API."""
    
    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key
    
    async def on_cycle_complete(self, summary):
        # POST summary to API
        pass
    
    async def on_board_complete(self, result):
        # Optional: real-time updates per board
        pass
```

---

## Implementation Tasks

### Phase 1: Data & Summary (Now)
- [ ] Create `cycle_summary.py` with data classes
- [ ] Build `CycleSummaryPopup` widget
- [ ] Wire up summary generation at cycle end
- [ ] Auto-show popup when cycle completes

### Phase 2: Export
- [ ] Implement CSV export
- [ ] Implement JSON export  
- [ ] Export button in summary popup
- [ ] Configurable export directory

### Phase 3: Hooks (Future-ready)
- [ ] Define `CycleResultHandler` ABC
- [ ] Add handler registration to sequence.py
- [ ] Call handlers at appropriate points
- [ ] Ship with `NullHandler` and `FileExportHandler`

---

## Configuration

In panel settings or app config:
```yaml
export:
  enabled: true
  directory: ~/progbot/exports
  format: csv  # csv, json, both
  auto_export: false  # Export automatically on cycle end

# Future: when external system is defined
integration:
  handler: null  # null, file, api
  api_endpoint: ""
  api_key_env: ""
```
