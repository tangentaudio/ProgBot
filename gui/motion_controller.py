"""Motion control (smoothie) device operations."""
import asyncio
from device_io import AsyncSerialDevice


class MotionController:
    """Handles motion control (smoothie) device operations."""
    
    def __init__(self, update_phase_callback, port='/dev/ttyACM0', baudrate=115200):
        """Initialize motion controller.
        
        Args:
            update_phase_callback: Function to call to update phase display
            port: Serial port for motion controller
            baudrate: Baud rate for motion controller
        """
        self.update_phase = update_phase_callback
        self.port = port
        self.baudrate = baudrate
        self.device = None

    async def connect(self):
        """Connect to motion controller if not already connected."""
        if self.device is None:
            self.device = AsyncSerialDevice(self.port, self.baudrate)
            await self.device.connect()

    async def send_gcode_wait_ok(self, cmd, timeout=5):
        """Send GCode command and wait for 'ok' response."""
        if not self.device:
            raise RuntimeError("motion device not connected")
        response = await self.device.send_command(cmd, timeout=timeout)
        if not 'ok' in response:
            raise RuntimeError("not ok")
                
    async def init(self, do_homing=True):
        """Initialize mechanical systems (homing, coordinates, etc)."""
        await self.connect()
        print(f"Clearing alarm...")
        await self.device.send_command("M999")

        if do_homing:
            print(f"Homing...")
            await self.send_gcode_wait_ok("$H", timeout=20)
    
        print(f"Set G54 zero...")
        await self.send_gcode_wait_ok("G92 X0 Y0 Z0")
    
        print(f"Retract BLTouch...")
        await self.send_gcode_wait_ok("M281 G4 P0.5 M400")
    
        print(f"Init coord sys and units...")
        await self.send_gcode_wait_ok("G90 G54 G21")

    async def motors_off(self):
        """Turn off motors."""
        await self.connect()
        print(f"Motors off.")
        await self.send_gcode_wait_ok("M18")
     
    async def rapid_xy_abs(self, x, y):
        """Rapid movement to absolute XY position."""
        await self.connect()
        print(f"rapid_xy_abs x={x} y={y}")
        await self.send_gcode_wait_ok(f"G90 G0 X{x} Y{y}", timeout=10)
        await self.send_gcode_wait_ok("M400")

    async def rapid_xy_rel(self, dist_x, dist_y):
        """Rapid movement by relative XY distance."""
        await self.connect()
        print(f"rapid_xy_rel dist_x={dist_x} dist_y={dist_y}")
        await self.send_gcode_wait_ok(f"G91 G0 X{dist_x} Y{dist_y}", timeout=10)
        await self.send_gcode_wait_ok("M400")
    
    async def rapid_z_abs(self, z):
        """Rapid movement to absolute Z position."""
        await self.connect()
        await self.send_gcode_wait_ok(f"G90 G0 Z{z}", timeout=10)
        await self.send_gcode_wait_ok("M400")

    async def move_z_abs(self, z, rate):
        """Controlled movement to absolute Z position at specified rate."""
        await self.connect()
        await self.send_gcode_wait_ok(f"G90 G1 Z{z} f{rate}", timeout=10)
        await self.send_gcode_wait_ok("M400")
    
    async def do_probe(self):
        """Execute probe operation and return measured distance."""
        await self.connect()
        response = await self.device.send_command("M280 G4 P0.5 G30 M281 G4 P0.5 M400", timeout=15)
        print(f"Received: {response}")
    
        dist = 0.0
        if 'Z:' in response:
            junk, dist = response.split(':')
            dist = float(dist)
            print(f"Probe OK distance={dist}")
            return dist
        else:
            raise RuntimeError("no probe distance received")
