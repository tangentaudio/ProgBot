"""Nordic nRF programmer plugin using nrfutil.

Supports Nordic Semiconductor nRF series devices (nRF52, nRF53, etc.)
via the nrfutil command-line tool.
"""

from typing import List, Dict
from .base import ProgrammerBase


class NordicNrfProgrammer(ProgrammerBase):
    """Programmer for Nordic nRF devices using nrfutil."""
    
    name = "Nordic nRF (nrfutil)"
    
    @classmethod
    def get_steps(cls) -> List[Dict]:
        """Return available programming steps."""
        return [
            {
                'id': 'identify',
                'label': 'Identify',
                'description': 'Read device information and verify connection',
                'default': True,
            },
            {
                'id': 'recover',
                'label': 'Recover',
                'description': 'Recover locked/bricked device (erases all data)',
                'default': True,
            },
            {
                'id': 'erase',
                'label': 'Erase',
                'description': 'Erase flash memory',
                'default': True,
            },
            {
                'id': 'program',
                'label': 'Program',
                'description': 'Write firmware to device',
                'default': True,
            },
            {
                'id': 'lock',
                'label': 'Lock (APPROTECT)',
                'description': 'Enable readback protection to secure firmware',
                'default': False,
            },
        ]
    
    @classmethod
    def get_firmware_slots(cls) -> List[Dict]:
        """Return firmware file slots for nRF53 dual-core devices."""
        return [
            {
                'id': 'network_core',
                'label': 'Network Core FW',
                'filter': '*.hex',
                'required': True,
                'default': '/home/steve/fw/merged_CPUNET.hex',
            },
            {
                'id': 'main_core',
                'label': 'Main Core FW',
                'filter': '*.hex',
                'required': True,
                'default': '/home/steve/fw/merged.hex',
            },
        ]
    
    async def execute_step(self, step_id: str) -> bool:
        """Execute a programming step.
        
        Args:
            step_id: Step to execute
            
        Returns:
            True if successful, False otherwise
        """
        if step_id == 'identify':
            return await self._do_identify()
        elif step_id == 'recover':
            return await self._do_recover()
        elif step_id == 'erase':
            return await self._do_erase()
        elif step_id == 'program':
            return await self._do_program()
        elif step_id == 'lock':
            return await self._do_lock()
        else:
            print(f"Unknown step: {step_id}")
            return False
    
    async def _do_identify(self) -> bool:
        """Identify connected device."""
        self.update_phase("Identifying device...")
        res = await self.run_cmd_async("nrfutil", "device", "device-info")
        return res == 0
    
    async def _do_recover(self) -> bool:
        """Recover both cores."""
        self.update_phase("Recovering main core...")
        res = await self.run_cmd_async("nrfutil", "device", "recover")
        if res != 0:
            return False
        
        self.update_phase("Recovering network core...")
        res = await self.run_cmd_async("nrfutil", "device", "recover", "--core", "Network")
        return res == 0
    
    async def _do_erase(self) -> bool:
        """Erase both cores."""
        self.update_phase("Erasing main core...")
        res = await self.run_cmd_async("nrfutil", "device", "erase")
        if res != 0:
            return False
        
        self.update_phase("Erasing network core...")
        res = await self.run_cmd_async("nrfutil", "device", "erase", "--core", "Network")
        return res == 0
    
    async def _do_program(self) -> bool:
        """Program both cores with firmware."""
        network_fw = self.get_firmware_path('network_core')
        main_fw = self.get_firmware_path('main_core')
        
        if not network_fw:
            print("Error: Network core firmware path not set")
            return False
        if not main_fw:
            print("Error: Main core firmware path not set")
            return False
        
        self.update_phase("Programming network core...")
        res = await self.run_cmd_async(
            "nrfutil", "device", "program",
            "--firmware", network_fw,
            "--core", "Network"
        )
        if res != 0:
            return False
        
        self.update_phase("Programming main core...")
        res = await self.run_cmd_async(
            "nrfutil", "device", "program",
            "--firmware", main_fw
        )
        if res != 0:
            return False
        
        self.update_phase("Resetting device...")
        res = await self.run_cmd_async("nrfutil", "device", "reset")
        return res == 0
    
    async def _do_lock(self) -> bool:
        """Enable APPROTECT (readback protection)."""
        self.update_phase("Enabling APPROTECT...")
        # Note: This is a placeholder - actual command may vary by device
        # For nRF53, APPROTECT is typically set via UICR or during programming
        print("Warning: Lock step not fully implemented")
        # res = await self.run_cmd_async("nrfutil", "device", "...")
        return True  # Placeholder - return True for now
