# Provisioning System

## Overview

Provisioning is the post-programming phase where each target board receives its unique identity and configuration via the **target serial port**. The system implements an **expect-like script engine** that:

- Sends commands with `{variable}` substitution
- Parses responses using regex patterns
- Extracts named capture groups into board data
- Filters noise/debug lines from serial output

## Architecture

```
gui/provisioning/
  __init__.py       # Package exports
  engine.py         # ProvisioningEngine - executes scripts
  models.py         # ProvisionStep, ProvisionScript, StepResult, ProvisionResult
  accumulator.py    # ResponseAccumulator - filters/accumulates serial output
  variables.py      # Variable substitution utilities
```

## Available Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `{row}` | Board position | 0-based row index |
| `{col}` | Board position | 0-based column index |
| `{serial_number}` | QR scan | Board serial from barcode |
| `{qr_raw}` | QR scan | Raw QR data |
| `{panel_name}` | Panel settings | Current panel identifier |
| `{timestamp}` | System | ISO format datetime |
| `{date}` | System | YYYY-MM-DD |
| `{time}` | System | HH:MM:SS |

Variables captured via regex become available for subsequent steps.

## Script Configuration

Scripts are stored in panel files under `provision.script`:

```json
{
  "provision": {
    "enabled": true,
    "script": {
      "default_timeout": 5.0,
      "default_retries": 1,
      "global_ignore_patterns": ["^\\[DEBUG\\]"],
      "global_strip_prompt": "> ",
      "steps": [...]
    }
  }
}
```

## Step Configuration

Each step supports:

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Human-readable step name (required) |
| `send` | string | Command to send (supports `{vars}` and `\n`, `\r`, `\t`) |
| `expect` | regex | Pattern to match in response |
| `timeout` | float | Seconds to wait (default from script) |
| `retries` | int | Retry attempts on failure |
| `retry_delay` | float | Seconds between retries |
| `on_fail` | string | `abort` (default), `skip`, or `continue` |

## Named Captures

Use `(?P<name>pattern)` in expect regex to capture values:

```
expect: "MAC=(?P<mac_address>[0-9A-Fa-f:]+)"
```

Captured values are saved to board data and available as `{mac_address}` in later steps.

## UI Editor

The Panel Setup dialog includes a Provision tab with:
- Step list with Edit/Move/Delete actions
- Default timeout and retries spinners
- Full step editor dialog with regex validation
- On-screen keyboard toggle (disabled by default)

## Execution Flow

1. Cycle calls `_provision_board()` for each board
2. `ProvisioningEngine.execute()` runs the script
3. For each step:
   - Substitute variables in send command
   - Send to target serial port
   - Accumulate response lines (filter noise)
   - Match expect pattern
   - Extract named captures
   - Handle pass/fail per `on_fail` setting
4. Return `ProvisionResult` with all captures
