# Provisioning Infrastructure TODO

## Completed ✓

### Phase 1: Core Infrastructure

#### `provisioning/` Package Structure
- [x] `provisioning/__init__.py` - Package exports
- [x] `provisioning/accumulator.py` - ResponseAccumulator class
  - [x] Noise filtering with regex patterns
  - [x] Prompt stripping
  - [x] Pattern matching across accumulated lines
- [x] `provisioning/models.py` - Data classes
  - [x] `ProvisionStep` dataclass
  - [x] `ProvisionScript` dataclass with from_dict() loader
  - [x] `StepResult` dataclass
  - [x] `ProvisionResult` dataclass
- [x] `provisioning/variables.py` - Variable handling
  - [x] `substitute_variables()` - replace {vars} in templates
  - [x] `get_system_variables()` - row, col, timestamp, panel_name, etc.
- [x] `provisioning/engine.py` - ProvisioningEngine class
  - [x] `execute()` - run full script with verbose mode
  - [x] `execute_step()` - run single step with retry logic
  - [x] Named capture group extraction
  - [x] Timeout handling
  - [x] on_fail behavior (abort/skip/continue)

#### Integration
- [x] `sequence.py` - Updated `_provision_board()` to use ProvisioningEngine
- [x] `panel_settings.py` - Added provision config section to defaults
- [x] Panel file storage of provisioning scripts
- [x] Tested end-to-end with real hardware

### Phase 2: UI Editor

#### Provision Tab in Panel Setup Dialog
- [x] Simplified list view showing steps (# | Description | Actions)
- [x] Edit/Move Up/Move Down/Delete buttons per step
- [x] Add Step button
- [x] Default Timeout spinner (1.0-10.0s)
- [x] Default Retries spinner (0-5)
- [x] Script settings stored in panel file

#### Step Editor Dialog (`provision_step_editor.kv`, `provision_step_editor.py`)
- [x] Full step editor popup with fields:
  - [x] Description (required)
  - [x] Send command (with escape sequence display: \n, \r, \t)
  - [x] Expect pattern (regex with live validation)
  - [x] Timeout spinner (default, 1.0-10.0s)
  - [x] Retries spinner (default, 0-5)
  - [x] Retry Delay spinner (default, 0.5-5.0s)
  - [x] On Fail dropdown (default, abort, skip, continue)
- [x] Regex validation with named capture display
- [x] Available variables help panel
- [x] On-screen keyboard toggle (disabled by default in editor)
- [x] Font fixes for Unicode symbols (✓, ↑, ↓, ✕)

---

## Remaining Work

### Testing Infrastructure
- [ ] `test_provisioning.py` - Interactive test tool (partially done)
  - [ ] Script validation mode
  - [ ] Dry-run with sample data
- [ ] Unit tests for accumulator, variables, engine

### UI Enhancements
- [ ] Visual feedback when provisioning runs (progress indicator)
- [ ] Provision log/transcript viewer per board
- [ ] Regex pattern helper/builder

### Advanced Features
- [ ] Global ignore patterns UI (currently JSON-only)
- [ ] Global strip prompt UI (currently JSON-only)
- [ ] Custom variables UI (currently JSON-only)
- [ ] expect_any support in UI (currently JSON-only)
- [ ] Import/export provisioning scripts

### Data Export
- [ ] CSV export of cycle results with captured data
- [ ] JSON export option
- [ ] Webhook/API integration for MES systems

### Documentation
- [ ] User guide for creating provisioning scripts
- [ ] Regex pattern examples for common use cases
- [ ] Troubleshooting guide

---

## Example Script JSON

```json
{
  "provision": {
    "enabled": true,
    "script": {
      "name": "board_provisioning",
      "default_timeout": 5.0,
      "default_retries": 1,
      "global_ignore_patterns": ["^\\[DEBUG\\]", "^\\[INFO\\]"],
      "global_strip_prompt": "> ",
      "steps": [
        {
          "description": "Wait for boot prompt",
          "send": "\\n\\r",
          "expect": "ready|>",
          "timeout": 3.0
        },
        {
          "description": "Read device info",
          "send": "dump info",
          "expect": "MAC=(?P<mac_address>[0-9A-Fa-f:]+)",
          "timeout": 5.0
        },
        {
          "description": "Set serial number",
          "send": "set sn {serial_number}",
          "expect": "OK|SN_SET",
          "timeout": 3.0,
          "retries": 2
        }
      ]
    }
  }
}
```

---

## Data Flow

```
Panel Setup → provision.script.steps[] → JSON storage
                    ↓
Cycle runs → _provision_board() called per board
                    ↓
ProvisioningEngine.execute(script, board_info, target_controller)
                    ↓
For each step:
  1. Substitute variables in send command
  2. Send to target serial port
  3. Accumulate response (filter noise)
  4. Match expect pattern
  5. Extract named captures → board_info
  6. Handle success/failure per on_fail setting
                    ↓
Return ProvisionResult with all captures
```
