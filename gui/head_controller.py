"""Programmer head (proghead) device controller."""
import asyncio
from device_io import AsyncSerialDevice


class HeadController:
    """Handles programmer head device contact/power/logic operations."""
    
    def __init__(self, update_phase_callback, port='/dev/ttyUSB0', baudrate=9600):
        """Initialize head controller.
        
        Args:
            update_phase_callback: Function to call to update phase display
            port: Serial port for head controller
            baudrate: Baud rate for head controller
        """
        self.update_phase = update_phase_callback
        self.port = port
        self.baudrate = baudrate
        self.device = None

    async def connect(self):
        """Connect to head controller if not already connected."""
        # Check if existing connection is still alive
        if self.device is not None:
            try:
                # Quick health check - see if reader/writer still exist
                if self.device.reader is None or self.device.writer is None or self.device.writer.is_closing():
                    print(f"[HeadController] Connection dead, reconnecting to {self.port}")
                    self.device = None
            except Exception as e:
                print(f"[HeadController] Health check failed: {e}, reconnecting")
                self.device = None
        
        if self.device is None:
            print(f"[HeadController] Connecting to {self.port} at {self.baudrate} baud...")
            self.device = AsyncSerialDevice(self.port, self.baudrate)
            await self.device.connect()
            print(f"[HeadController] Connected successfully to {self.port}")

    # Head device contact/power operations
    
    async def check_contact(self):
        """Check if probe is in contact with device."""
        await self.connect()
        print(f"[HeadController] Sending 'Stat' command...")
        response = await self.device.send_command("Stat", retries=3)
        print(f"[HeadController] Received response: '{response}'")
        if 'ERROR' in response:
            raise RuntimeError("proghead error")
        contacted = 'PRESENT' in response
        print(f"contacted = {contacted}")
        return contacted

    async def set_power(self, enable):
        """Enable or disable programmer power."""
        await self.connect()
        response = await self.device.send_command("PowerOn" if enable else "PowerOff", retries=3)
        if not 'OK' in response:
            raise RuntimeError("proghead error powering on/off")
 
    async def set_logic(self, enable):
        """Enable or disable programmer logic."""
        await self.connect()
        response = await self.device.send_command("LogicOn" if enable else "LogicOff", retries=3)
        if not 'OK' in response:
            raise RuntimeError("proghead error logic on/off")

    async def set_all(self, enable):
        """Enable or disable all programmer outputs."""
        await self.connect()
        response = await self.device.send_command("AllOn" if enable else "AllOff", retries=3)
        if not 'OK' in response:
            raise RuntimeError("proghead error all on/off")
