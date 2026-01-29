"""Base class for programmer plugins.

All programmer plugins should inherit from ProgrammerBase and implement
the required class methods and instance methods.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class ProgrammerBase(ABC):
    """Abstract base class for programmer plugins.
    
    Subclasses must implement:
        - name (class attribute): Display name for the programmer
        - get_steps() (classmethod): Return available programming steps
        - get_firmware_slots() (classmethod): Return required firmware file slots
        - execute_step(): Execute a single programming step
    """
    
    name: str = "Unknown Programmer"
    
    def __init__(self, update_phase_callback, firmware_paths: Dict[str, str] = None):
        """Initialize programmer.
        
        Args:
            update_phase_callback: Function to call to update phase display
            firmware_paths: Dict mapping slot_id -> file_path
        """
        self.update_phase = update_phase_callback
        self.firmware_paths = firmware_paths or {}
    
    @classmethod
    @abstractmethod
    def get_steps(cls) -> List[Dict]:
        """Return available programming steps with metadata.
        
        Returns:
            List of step definitions, each containing:
                - id (str): Unique step identifier
                - label (str): Display label for UI
                - description (str): Tooltip/help text
                - default (bool): Whether enabled by default
                
        Example:
            [
                {'id': 'identify', 'label': 'Identify', 'description': 'Read device info', 'default': True},
                {'id': 'program', 'label': 'Program', 'description': 'Write firmware', 'default': True},
            ]
        """
        pass
    
    @classmethod
    @abstractmethod
    def get_firmware_slots(cls) -> List[Dict]:
        """Return firmware file slots required by this programmer.
        
        Returns:
            List of firmware slot definitions, each containing:
                - id (str): Unique slot identifier
                - label (str): Display label for UI
                - filter (str): File filter pattern (e.g., '*.hex')
                - required (bool): Whether this slot must be filled
                - default (str, optional): Default file path
                
        Example:
            [
                {'id': 'main', 'label': 'Firmware', 'filter': '*.hex', 'required': True},
            ]
        """
        pass
    
    @abstractmethod
    async def execute_step(self, step_id: str) -> bool:
        """Execute a single programming step.
        
        Args:
            step_id: Step identifier from get_steps()
            
        Returns:
            True if step succeeded, False otherwise
        """
        pass
    
    async def execute_sequence(self, enabled_steps: List[str]) -> bool:
        """Execute a sequence of enabled steps in order.
        
        Args:
            enabled_steps: List of step IDs to execute, in order
            
        Returns:
            True if all steps succeeded, False if any failed
        """
        # Get ordered list of all steps
        all_steps = [s['id'] for s in self.get_steps()]
        
        # Execute only enabled steps, in the order defined by get_steps()
        for step_id in all_steps:
            if step_id in enabled_steps:
                self.update_phase(f"Running: {step_id}")
                success = await self.execute_step(step_id)
                if not success:
                    return False
        return True
    
    def _run_cmd_sync(self, args: tuple) -> tuple:
        """Run subprocess synchronously in a thread.
        
        Returns:
            Tuple of (returncode, stdout, stderr)
        """
        import subprocess
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=120  # 2 minute timeout
            )
            return (result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return (1, b'', b'Timeout expired')
        except Exception as e:
            return (1, b'', str(e).encode())
    
    async def run_cmd_async(self, *args) -> int:
        """Run subprocess asynchronously and return returncode.
        
        Uses run_in_executor to run the subprocess in a thread pool,
        completely freeing the main thread for UI updates.
        
        Args:
            *args: Command and arguments
            
        Returns:
            Process return code (0 = success)
        """
        import concurrent.futures
        
        try:
            print(f"Running command: {' '.join(args)}")
            
            # Run in thread pool to completely free main thread
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                returncode, stdout, stderr = await loop.run_in_executor(
                    pool, self._run_cmd_sync, args
                )
            
            # Print output for debugging
            if stdout:
                print(f"stdout: {stdout.decode('utf-8', errors='ignore')}")
            if stderr:
                print(f"stderr: {stderr.decode('utf-8', errors='ignore')}")
            
            print(f"Command finished with returncode: {returncode}")
            return returncode
        except Exception as e:
            print(f"Error running {args[0]}: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    def get_firmware_path(self, slot_id: str) -> Optional[str]:
        """Get firmware path for a slot.
        
        Args:
            slot_id: Firmware slot identifier
            
        Returns:
            File path or None if not set
        """
        return self.firmware_paths.get(slot_id)
