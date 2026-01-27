#!/usr/bin/env python3
"""Standalone test harness for provisioning scripts.

This tool allows testing provisioning scripts against a real serial device
without running the full ProgBot GUI. Useful for:
- Developing and debugging provisioning scripts
- Testing against a test target board
- Validating script syntax and patterns

Usage:
    python test_provisioning.py --port /dev/ttyUSB0 --panel myboard.panel
    python test_provisioning.py --port /dev/ttyUSB0 --script script.json
    python test_provisioning.py --port /dev/ttyUSB0 --interactive

Options:
    --port PORT         Serial port to connect to (required)
    --baud BAUD         Baud rate (default: 115200)
    --panel FILE        Load provisioning script from panel file
    --script FILE       Load provisioning script from JSON file
    --interactive       Interactive mode: enter commands manually
    --serial SN         Mock serial number for testing
    --row ROW           Mock row position (default: 0)
    --col COL           Mock column position (default: 0)
    --verbose           Enable verbose logging
    --dry-run           Parse and validate script without executing
"""

import argparse
import asyncio
import json
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from provisioning import (
    ProvisioningEngine,
    ProvisionScript,
    VariableContext,
    ResponseAccumulator,
)
from device_io import AsyncSerialDevice


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_script_from_panel(panel_file: str) -> tuple[ProvisionScript, dict]:
    """Load provisioning script from a panel file.
    
    Args:
        panel_file: Path to .panel file
        
    Returns:
        Tuple of (ProvisionScript, custom_variables dict)
    """
    with open(panel_file, 'r') as f:
        data = json.load(f)
    
    provision_config = data.get('provision', {})
    script_data = provision_config.get('script', {})
    custom_vars = provision_config.get('custom_variables', {})
    
    if not script_data.get('steps'):
        raise ValueError(f"No provisioning steps found in {panel_file}")
    
    return ProvisionScript.from_dict(script_data), custom_vars


def load_script_from_json(script_file: str) -> tuple[ProvisionScript, dict]:
    """Load provisioning script from a standalone JSON file.
    
    Args:
        script_file: Path to JSON script file
        
    Returns:
        Tuple of (ProvisionScript, custom_variables dict)
    """
    with open(script_file, 'r') as f:
        data = json.load(f)
    
    # Support both bare script format and wrapped format
    if 'steps' in data:
        script_data = data
        custom_vars = {}
    else:
        script_data = data.get('script', data)
        custom_vars = data.get('custom_variables', {})
    
    return ProvisionScript.from_dict(script_data), custom_vars


def validate_script(script: ProvisionScript) -> list[str]:
    """Validate a provisioning script for common errors.
    
    Args:
        script: The script to validate
        
    Returns:
        List of warning/error messages
    """
    import re
    warnings = []
    
    for i, step in enumerate(script.steps):
        step_desc = step.description or f"Step {i+1}"
        
        # Check expect patterns compile
        if step.expect:
            try:
                re.compile(step.expect)
            except re.error as e:
                warnings.append(f"{step_desc}: Invalid expect pattern: {e}")
        
        if step.expect_any:
            for j, pattern in enumerate(step.expect_any):
                try:
                    re.compile(pattern)
                except re.error as e:
                    warnings.append(f"{step_desc}: Invalid expect_any[{j}] pattern: {e}")
        
        # Check ignore patterns compile
        if step.ignore_patterns:
            for j, pattern in enumerate(step.ignore_patterns):
                try:
                    re.compile(pattern)
                except re.error as e:
                    warnings.append(f"{step_desc}: Invalid ignore_patterns[{j}]: {e}")
        
        # Warn about steps with no expect (fire-and-forget)
        if step.send and not step.expect and not step.expect_any:
            warnings.append(f"{step_desc}: Sends command but has no expect pattern")
        
        # Warn about steps with neither send nor expect
        if not step.send and not step.expect and not step.expect_any:
            warnings.append(f"{step_desc}: Has neither send nor expect")
    
    # Check global ignore patterns
    if script.global_ignore_patterns:
        for j, pattern in enumerate(script.global_ignore_patterns):
            try:
                re.compile(pattern)
            except re.error as e:
                warnings.append(f"global_ignore_patterns[{j}]: Invalid pattern: {e}")
    
    return warnings


def print_script_summary(script: ProvisionScript, custom_vars: dict):
    """Print a summary of the script."""
    print(f"\n{'='*60}")
    print(f"Script: {script.name}")
    print(f"Steps: {len(script.steps)}")
    print(f"Default timeout: {script.default_timeout}s")
    print(f"Default retries: {script.default_retries}")
    print(f"Default on_fail: {script.default_on_fail}")
    
    if script.global_ignore_patterns:
        print(f"Global ignore patterns: {script.global_ignore_patterns}")
    if script.global_strip_prompt:
        print(f"Global strip prompt: {repr(script.global_strip_prompt)}")
    if custom_vars:
        print(f"Custom variables: {custom_vars}")
    
    print(f"\nSteps:")
    for i, step in enumerate(script.steps):
        desc = step.description or f"Step {i+1}"
        send = step.send[:40] + "..." if step.send and len(step.send) > 40 else step.send
        expect = step.expect[:40] + "..." if step.expect and len(step.expect) > 40 else step.expect
        print(f"  {i+1}. {desc}")
        if send:
            print(f"      send: {repr(send)}")
        if expect:
            print(f"      expect: {repr(expect)}")
        if step.expect_any:
            print(f"      expect_any: {len(step.expect_any)} patterns")
    print(f"{'='*60}\n")


async def run_interactive(device: AsyncSerialDevice, context: VariableContext):
    """Run interactive mode for manual command/response testing."""
    from provisioning.variables import substitute_variables
    
    print("\nInteractive mode. Commands:")
    print("  send <text>     - Send text to device (with variable substitution)")
    print("  wait <pattern>  - Wait for pattern match")
    print("  drain           - Drain and display pending input")
    print("  vars            - Show current variables")
    print("  quit            - Exit")
    print()
    
    accumulator = ResponseAccumulator()
    
    # Start a background task to collect incoming lines
    incoming_lines = []
    
    async def collect_lines():
        while True:
            try:
                line = await asyncio.wait_for(device.line_queue.get(), timeout=0.1)
                incoming_lines.append(line)
                print(f"  <- {line}")
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
    
    collector = asyncio.create_task(collect_lines())
    
    try:
        while True:
            try:
                cmd = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(">> ")
                )
            except EOFError:
                break
            
            cmd = cmd.strip()
            if not cmd:
                continue
            
            if cmd == 'quit':
                break
            elif cmd == 'vars':
                print(f"Variables: {context.get_all()}")
            elif cmd == 'drain':
                count = 0
                while not device.line_queue.empty():
                    try:
                        line = device.line_queue.get_nowait()
                        print(f"  (drained) {line}")
                        count += 1
                    except:
                        break
                print(f"Drained {count} lines")
            elif cmd.startswith('send '):
                text = cmd[5:]
                text, missing = substitute_variables(text, context.get_all())
                if missing:
                    print(f"Warning: missing variables: {missing}")
                device.writer.write((text + '\n').encode())
                await device.writer.drain()
                print(f"  -> {text}")
            elif cmd.startswith('wait '):
                pattern = cmd[5:]
                accumulator.clear()
                print(f"Waiting for pattern: {pattern}")
                deadline = asyncio.get_event_loop().time() + 5.0
                while asyncio.get_event_loop().time() < deadline:
                    if incoming_lines:
                        line = incoming_lines.pop(0)
                        accumulator.add_line(line)
                        matched, text, captures = accumulator.search(pattern)
                        if matched:
                            print(f"  MATCHED: {text}")
                            if captures:
                                print(f"  Captures: {captures}")
                                context.add_captures(captures)
                            break
                    await asyncio.sleep(0.05)
                else:
                    print("  TIMEOUT")
            else:
                print(f"Unknown command: {cmd}")
    finally:
        collector.cancel()
        try:
            await collector
        except asyncio.CancelledError:
            pass


async def run_script(
    device: AsyncSerialDevice,
    script: ProvisionScript,
    context: VariableContext,
    verbose: bool = False
) -> bool:
    """Run a provisioning script and display results.
    
    Returns:
        True if script succeeded
    """
    engine = ProvisioningEngine(verbose=verbose)
    
    print(f"\nExecuting script: {script.name}")
    print(f"Initial variables: {context.get_all()}")
    print("-" * 40)
    
    result = await engine.execute(script, device, context)
    
    print("-" * 40)
    print(f"\nResult: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"Steps completed: {result.steps_completed}/{result.total_steps}")
    print(f"Elapsed: {result.elapsed:.2f}s")
    
    if result.captures:
        print(f"\nCaptured data:")
        for key, value in result.captures.items():
            print(f"  {key}: {value}")
    
    if result.error:
        print(f"\nError: {result.error}")
    
    # Show per-step results
    print(f"\nStep details:")
    for i, step_result in enumerate(result.step_results):
        status = "✓" if step_result.success else "✗"
        print(f"  {status} Step {i+1}: ", end="")
        if step_result.success:
            if step_result.captures:
                print(f"captured {list(step_result.captures.keys())}")
            else:
                print("OK")
        else:
            print(f"FAILED - {step_result.error}")
        
        if step_result.retries_used > 0:
            print(f"      (used {step_result.retries_used} retries)")
    
    return result.success


async def main():
    parser = argparse.ArgumentParser(
        description='Test provisioning scripts against a serial device',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--port', required=True, help='Serial port')
    parser.add_argument('--baud', type=int, default=115200, help='Baud rate')
    parser.add_argument('--panel', help='Panel file to load script from')
    parser.add_argument('--script', help='JSON script file to load')
    parser.add_argument('--interactive', action='store_true', help='Interactive mode')
    parser.add_argument('--serial', default='TEST123', help='Mock serial number')
    parser.add_argument('--row', type=int, default=0, help='Mock row position')
    parser.add_argument('--col', type=int, default=0, help='Mock column position')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--dry-run', action='store_true', help='Validate only')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load script
    script = None
    custom_vars = {}
    
    if args.panel:
        logger.info(f"Loading script from panel: {args.panel}")
        script, custom_vars = load_script_from_panel(args.panel)
    elif args.script:
        logger.info(f"Loading script from file: {args.script}")
        script, custom_vars = load_script_from_json(args.script)
    
    if script:
        print_script_summary(script, custom_vars)
        
        # Validate
        warnings = validate_script(script)
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"  ⚠ {w}")
            print()
        
        if args.dry_run:
            print("Dry run complete - script validated")
            return 0
    
    if not args.interactive and not script:
        parser.error("Must specify --panel, --script, or --interactive")
    
    # Build variable context
    vision_vars = {'serial_number': args.serial, 'qr_raw': args.serial}
    context = VariableContext(
        row=args.row,
        col=args.col,
        panel_name='test_harness',
        vision_vars=vision_vars,
        custom_vars=custom_vars,
    )
    
    # Connect to device
    logger.info(f"Connecting to {args.port} at {args.baud} baud...")
    device = AsyncSerialDevice(args.port, args.baud)
    
    try:
        await device.connect()
        logger.info("Connected")
        
        # Give device a moment to settle
        await asyncio.sleep(0.5)
        
        # Drain any pending data
        drained = 0
        while not device.line_queue.empty():
            try:
                line = device.line_queue.get_nowait()
                logger.debug(f"Drained: {line}")
                drained += 1
            except:
                break
        if drained:
            logger.info(f"Drained {drained} pending lines")
        
        if args.interactive:
            await run_interactive(device, context)
            return 0
        else:
            success = await run_script(device, script, context, args.verbose)
            return 0 if success else 1
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await device.disconnect_async()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
