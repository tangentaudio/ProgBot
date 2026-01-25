"""Target device controller for testing and communication."""
import asyncio
from device_io import AsyncSerialDevice


class TargetController:
    """Handles target device testing and communication."""
    
    def __init__(self, update_phase_callback, port='/dev/ttyACM1', baudrate=115200):
        """Initialize target controller.
        
        Args:
            update_phase_callback: Function to call to update phase display
            port: Serial port for target UART
            baudrate: Baud rate for target UART
        """
        self.update_phase = update_phase_callback
        self.port = port
        self.baudrate = baudrate
        self.device = None

    async def connect(self):
        """Connect to target UART if not already connected."""
        # Check if existing connection is still alive
        if self.device is not None:
            try:
                # Quick health check - see if reader/writer still exist
                if self.device.reader is None or self.device.writer is None or self.device.writer.is_closing():
                    print(f"[TargetController] Connection dead, reconnecting to {self.port}")
                    self.device = None
            except Exception as e:
                print(f"[TargetController] Health check failed: {e}, reconnecting")
                self.device = None
        
        if self.device is None:
            self.device = AsyncSerialDevice(self.port, self.baudrate)
            await self.device.connect()

    async def test(self):
        """Test device communication."""
        await self.connect()
        try:
            response = await self.device.send_command("beep 1")
            print(f"resp={response}")
            
            await asyncio.sleep(1)
            
            response = await self.device.send_command("beep 1")
            print(f"resp={response}")
        except:
            pass

    def create_monitor_task(self):
        """Start a background task to print UART lines until cancelled."""
        async def monitor_loop():
            await self.connect()
            try:
                while True:
                    line = await self.device.read()
                    if line:
                        print(f"{line}")
            except asyncio.CancelledError:
                raise

        return asyncio.create_task(monitor_loop())
