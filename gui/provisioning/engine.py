"""Provisioning execution engine.

The ProvisioningEngine executes provisioning scripts against a target
device, handling command/response patterns, variable substitution,
and data capture.
"""

import asyncio
import time
import logging
from typing import Optional, TYPE_CHECKING

from .models import (
    ProvisionStep,
    ProvisionScript,
    StepResult,
    ProvisionResult,
)
from .accumulator import ResponseAccumulator
from .variables import VariableContext

if TYPE_CHECKING:
    from device_io import AsyncSerialDevice

logger = logging.getLogger(__name__)


class ProvisioningEngine:
    """Executes provisioning scripts against target devices.
    
    The engine handles:
    - Command sending with variable substitution
    - Response accumulation with noise filtering
    - Pattern matching and capture extraction
    - Timeout/retry handling
    - Result aggregation
    """
    
    def __init__(self, verbose: bool = False):
        """Initialize the engine.
        
        Args:
            verbose: If True, log detailed execution information
        """
        self.verbose = verbose
    
    async def execute(
        self,
        script: ProvisionScript,
        device: 'AsyncSerialDevice',
        context: VariableContext,
    ) -> ProvisionResult:
        """Execute a complete provisioning script.
        
        Args:
            script: The provisioning script to execute
            device: Connected AsyncSerialDevice for the target
            context: Variable context with board info
            
        Returns:
            ProvisionResult with overall outcome and per-step results
        """
        start_time = time.time()
        step_results = []
        
        logger.info(f"Starting provisioning script: {script.name}")
        if self.verbose:
            logger.info(f"Initial variables: {context.get_all()}")
        
        for i, step in enumerate(script.steps):
            # Resolve step settings with script defaults
            step_timeout = step.timeout if step.timeout else script.default_timeout
            step_retries = step.retries if step.retries else script.default_retries
            step_retry_delay = step.retry_delay if step.retry_delay else script.default_retry_delay
            step_on_fail = step.on_fail if step.on_fail else script.default_on_fail
            
            # Merge noise filtering (step overrides global)
            ignore_patterns = step.ignore_patterns
            if ignore_patterns is None:
                ignore_patterns = script.global_ignore_patterns
            
            strip_prompt = step.strip_prompt
            if strip_prompt is None:
                strip_prompt = script.global_strip_prompt
            
            # Create modified step with resolved values
            resolved_step = ProvisionStep(
                send=step.send,
                expect=step.expect,
                expect_any=step.expect_any,
                ignore_patterns=ignore_patterns,
                strip_prompt=strip_prompt,
                multiline=step.multiline,
                timeout=step_timeout,
                delay_before=step.delay_before,
                delay_after=step.delay_after,
                retries=step_retries,
                retry_delay=step_retry_delay,
                on_fail=step_on_fail,
                description=step.description,
            )
            
            desc = step.description or f"Step {i+1}"
            if self.verbose:
                print(f"\n[Step {i+1}] {desc}")
                if step.send:
                    print(f"  Command: {step.send}")
                if step.expect:
                    print(f"  Expect: {step.expect}")
            logger.info(f"Executing: {desc}")
            
            result = await self._execute_step(resolved_step, device, context, i)
            step_results.append(result)
            
            if result.success:
                # Add captures to context for subsequent steps
                if result.captures:
                    context.add_captures(result.captures)
                    if self.verbose:
                        print(f"  ✓ Matched: {result.matched_text}")
                        print(f"  Captures: {result.captures}")
                    logger.info(f"Captured: {result.captures}")
                elif self.verbose:
                    print(f"  ✓ OK")
            else:
                if self.verbose:
                    print(f"  ✗ FAILED: {result.error}")
                logger.warning(f"Step {i+1} failed: {result.error}")
                
                if step_on_fail == 'abort':
                    return ProvisionResult(
                        success=False,
                        steps_completed=i,
                        total_steps=len(script.steps),
                        captures=context.all_captures,
                        step_results=step_results,
                        error=f"Step {i+1} failed: {result.error}",
                        elapsed=time.time() - start_time,
                    )
                elif step_on_fail == 'skip':
                    logger.info(f"Skipping remaining steps due to on_fail='skip'")
                    break
                # else: 'continue' - proceed to next step
        
        elapsed = time.time() - start_time
        logger.info(
            f"Provisioning complete: {len(step_results)}/{len(script.steps)} steps, "
            f"{elapsed:.2f}s, captures: {list(context.all_captures.keys())}"
        )
        
        return ProvisionResult(
            success=True,
            steps_completed=len(step_results),
            total_steps=len(script.steps),
            captures=context.all_captures,
            step_results=step_results,
            elapsed=elapsed,
        )
    
    async def _execute_step(
        self,
        step: ProvisionStep,
        device: 'AsyncSerialDevice',
        context: VariableContext,
        step_index: int,
    ) -> StepResult:
        """Execute a single provisioning step.
        
        Args:
            step: The step to execute
            device: Connected serial device
            context: Current variable context
            step_index: Index of this step (for result)
            
        Returns:
            StepResult with outcome
        """
        start_time = time.time()
        retries_used = 0
        
        for attempt in range(step.retries):
            retries_used = attempt
            
            # Create accumulator for this attempt
            accumulator = ResponseAccumulator(
                ignore_patterns=step.ignore_patterns,
                strip_prompt=step.strip_prompt,
            )
            
            try:
                result = await self._execute_step_once(
                    step, device, context, accumulator
                )
                
                if result.success:
                    result.step_index = step_index
                    result.retries_used = retries_used
                    return result
                    
                # If we should retry
                if attempt < step.retries - 1:
                    if self.verbose:
                        print(f"  Retry {attempt+1}/{step.retries-1} after {step.retry_delay}s...")
                    logger.debug(f"Step attempt {attempt+1} failed, retrying in {step.retry_delay}s...")
                    await asyncio.sleep(step.retry_delay)
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Step execution error: {e}")
                if attempt >= step.retries - 1:
                    return StepResult(
                        success=False,
                        step_index=step_index,
                        error=str(e),
                        elapsed=time.time() - start_time,
                        retries_used=retries_used,
                    )
        
        # All retries exhausted - return last failure
        return StepResult(
            success=False,
            step_index=step_index,
            response=accumulator.get_raw_text(),
            error="Pattern not matched after all retries",
            elapsed=time.time() - start_time,
            lines_received=accumulator.line_count,
            retries_used=retries_used,
        )
    
    async def _execute_step_once(
        self,
        step: ProvisionStep,
        device: 'AsyncSerialDevice',
        context: VariableContext,
        accumulator: ResponseAccumulator,
    ) -> StepResult:
        """Execute a single attempt of a step.
        
        Args:
            step: The step to execute
            device: Connected serial device
            context: Current variable context
            accumulator: Response accumulator for this attempt
            
        Returns:
            StepResult with outcome
        """
        start_time = time.time()
        
        # Delay before sending
        if step.delay_before > 0:
            await asyncio.sleep(step.delay_before)
        
        # Send command if specified
        if step.send:
            command, missing = context.substitute(step.send)
            if missing:
                return StepResult(
                    success=False,
                    step_index=0,
                    error=f"Missing variables: {missing}",
                    elapsed=time.time() - start_time,
                )
            
            if self.verbose:
                print(f"  TX: {command}")
            logger.debug(f"Sending: {command}")
            
            # Drain any pending data first
            await self._drain_queue(device)
            
            # Send the command
            device.writer.write((command + '\n').encode())
            await device.writer.drain()
        
        # If no expect pattern, we're done (just send command)
        if not step.expect and not step.expect_any:
            if step.delay_after > 0:
                await asyncio.sleep(step.delay_after)
            return StepResult(
                success=True,
                step_index=0,
                elapsed=time.time() - start_time,
            )
        
        # Substitute variables in expect pattern(s)
        expect_pattern = None
        expect_any_patterns = None
        
        if step.expect:
            expect_pattern, missing = context.substitute(step.expect)
            if missing:
                logger.warning(f"Missing variables in expect pattern: {missing}")
        
        if step.expect_any:
            expect_any_patterns = []
            for pattern in step.expect_any:
                subst_pattern, missing = context.substitute(pattern)
                if missing:
                    logger.warning(f"Missing variables in expect_any pattern: {missing}")
                expect_any_patterns.append(subst_pattern)
        
        # Wait for expected pattern
        deadline = time.time() + step.timeout
        
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            
            try:
                line = await asyncio.wait_for(
                    device.line_queue.get(),
                    timeout=min(remaining, 0.5)  # Check pattern every 0.5s
                )
                
                accumulator.add_line(line)
                
                if self.verbose:
                    print(f"  RX: {line}")
                logger.debug(f"Received: {line}")
                
                # Try to match pattern(s)
                if expect_any_patterns:
                    matched, text, captures, idx = accumulator.search_any(expect_any_patterns)
                elif expect_pattern:
                    matched, text, captures = accumulator.search(expect_pattern)
                else:
                    matched = False
                
                if matched:
                    if step.delay_after > 0:
                        await asyncio.sleep(step.delay_after)
                    
                    return StepResult(
                        success=True,
                        step_index=0,
                        response=accumulator.get_raw_text(),
                        matched_text=text,
                        captures=captures,
                        elapsed=time.time() - start_time,
                        lines_received=accumulator.line_count,
                    )
                    
            except asyncio.TimeoutError:
                # No data received in this interval, loop continues
                pass
        
        # Timeout - pattern not matched
        return StepResult(
            success=False,
            step_index=0,
            response=accumulator.get_raw_text(),
            error=f"Timeout waiting for pattern (received {accumulator.line_count} lines)",
            elapsed=time.time() - start_time,
            lines_received=accumulator.line_count,
        )
    
    async def _drain_queue(self, device: 'AsyncSerialDevice') -> int:
        """Drain any pending lines from the device queue.
        
        Args:
            device: The serial device
            
        Returns:
            Number of lines drained
        """
        count = 0
        while not device.line_queue.empty():
            try:
                device.line_queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        
        if count > 0:
            logger.debug(f"Drained {count} pending lines from queue")
        
        return count
