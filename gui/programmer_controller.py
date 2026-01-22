"""Device programmer controller for firmware identification and programming."""
import asyncio


class ProgrammerController:
    """Handles device programming and identification via nrfutil."""
    
    def __init__(self, update_phase_callback, network_core_firmware='/home/steve/fw/merged_CPUNET.hex', main_core_firmware='/home/steve/fw/merged.hex'):
        """Initialize programmer controller.
        
        Args:
            update_phase_callback: Function to call to update phase display
            network_core_firmware: Path to network core firmware hex file
            main_core_firmware: Path to main core firmware hex file
        """
        self.update_phase = update_phase_callback
        self.network_core_firmware = network_core_firmware
        self.main_core_firmware = main_core_firmware

    async def run_cmd_async(self, *args):
        """Run subprocess asynchronously and return returncode."""
        try:
            print(f"Running command: {' '.join(args)}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            # Print output for debugging
            if stdout:
                print(f"stdout: {stdout.decode('utf-8', errors='ignore')}")
            if stderr:
                print(f"stderr: {stderr.decode('utf-8', errors='ignore')}")
            
            print(f"Command finished with returncode: {proc.returncode}")
            return proc.returncode
        except Exception as e:
            print(f"Error running {args[0]}: {e}")
            import traceback
            traceback.print_exc()
            return 1

    async def identify(self):
        """Identify the connected device."""
        self.update_phase("Identify")
        res = await self.run_cmd_async("nrfutil", "device", "device-info")
        if res != 0:
            return False
        return True

    async def program(self):
        """Program the connected device with firmware."""
        self.update_phase("Recover main core")
        res = await self.run_cmd_async("nrfutil", "device", "recover")
        if res != 0:
            return False
        
        self.update_phase("Recover network core")
        res = await self.run_cmd_async("nrfutil", "device", "recover", "--core", "Network")
        if res != 0:
            return False
        
        self.update_phase("Erase main core")
        res = await self.run_cmd_async("nrfutil", "device", "erase")
        if res != 0:
            return False
        
        self.update_phase("Erase network core")
        res = await self.run_cmd_async("nrfutil", "device", "erase", "--core", "Network")
        if res != 0:
            return False
        
        self.update_phase("Flash network core image")
        res = await self.run_cmd_async("nrfutil", "device", "program", "--firmware", self.network_core_firmware, "--core", "Network")
        if res != 0:
            return False
        
        self.update_phase("Flash main image")
        res = await self.run_cmd_async("nrfutil", "device", "program", "--firmware", self.main_core_firmware)
        if res != 0:
            return False
        
        self.update_phase("Reset target")
        res = await self.run_cmd_async("nrfutil", "device", "reset")
        if res != 0:
            return False
        
        return True
