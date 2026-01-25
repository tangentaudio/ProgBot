"""Motion control (smoothie) device operations."""
import asyncio
import time
from device_io import AsyncSerialDevice


def debug_log(msg):
    """Write debug message to /tmp/debug.txt"""
    try:
        with open('/tmp/debug.txt', 'a') as f:
            import datetime
            timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
            f.write(f"[{timestamp}] {msg}\n")
            f.flush()
    except Exception:
        pass


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
        # Check if existing connection is still alive
        if self.device is not None:
            try:
                # Quick health check - see if reader/writer still exist
                if self.device.reader is None or self.device.writer is None or self.device.writer.is_closing():
                    debug_log(f"[MotionController] Connection dead, reconnecting to {self.port}")
                    self.device = None
            except Exception as e:
                debug_log(f"[MotionController] Health check failed: {e}, reconnecting")
                self.device = None
        
        if self.device is None:
            debug_log(f"[MotionController] Connecting to {self.port}")
            self.device = AsyncSerialDevice(self.port, self.baudrate)
            await self.device.connect()

    async def send_gcode_wait_ok(self, cmd, timeout=5):
        """Send GCode command and wait for 'ok' response."""
        if not self.device:
            raise RuntimeError("motion device not connected")
        debug_log(f"[MOTION] Sending: {cmd}")
        response = await self.device.send_command(cmd, timeout=timeout)
        if not 'ok' in response:
            raise RuntimeError("not ok")
                
    async def init(self, do_homing=True):
        """Initialize mechanical systems (homing, coordinates, etc)."""
        await self.connect()
        print(f"Clearing alarm...")
        await self.device.send_command("M999")

        homed = False
        if do_homing:
            # Check if already homed by querying machine state
            print(f"Checking if already homed...")
            try:
                # Send status query and wait for actual status response (not just 'ok')
                self.device.writer.write("?\n".encode())
                await self.device.writer.drain()
                
                # Read responses until we get one with '<' (status format) or timeout
                start_time = time.time()
                status = None
                while time.time() - start_time < 2.0:
                    try:
                        response = await asyncio.wait_for(self.device.line_queue.get(), timeout=0.5)
                        debug_log(f"[MOTION] Status query response: {response}")
                        if '<' in response:  # This is the actual status
                            status = response
                            break
                    except asyncio.TimeoutError:
                        continue
                
                if not status:
                    debug_log(f"[MOTION] No status response received, doing homing")
                    print(f"Status query timeout, homing anyway...")
                    await self.send_gcode_wait_ok("$H", timeout=20)
                    homed = True
                elif 'Alarm' in status:
                    debug_log(f"[MOTION] Machine in Alarm state, homing required")
                    print(f"Machine in Alarm state, homing...")
                    await self.send_gcode_wait_ok("$H", timeout=20)
                    homed = True
                else:
                    # Check if at valid homed position (not 0,0,0)
                    print(f"Already homed, skipping homing cycle")
                    debug_log(f"[MOTION] Skipped homing - status: {status}")
                    homed = False
                    
            except Exception as e:
                # If status query fails, do homing anyway to be safe
                debug_log(f"[MOTION] Status query failed: {e}, doing homing anyway")
                print(f"Status query failed, homing anyway...")
                await self.send_gcode_wait_ok("$H", timeout=20)
                homed = True
    
        # Only reset work coordinates if we just homed
        # If we skipped homing, work coordinates are already correct
        if homed:
            print(f"Set G54 zero...")
            await self.send_gcode_wait_ok("G92 X0 Y0 Z0")
        else:
            print(f"Skipping G92 - work coordinates already set")
            debug_log(f"[MOTION] Skipped G92 - using existing work coordinates")
    
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
        await self.send_gcode_wait_ok("M400", timeout=5)

    async def rapid_xy_rel(self, dist_x, dist_y):
        """Rapid movement by relative XY distance."""
        await self.connect()
        print(f"rapid_xy_rel dist_x={dist_x} dist_y={dist_y}")
        await self.send_gcode_wait_ok(f"G91 G0 X{dist_x} Y{dist_y}", timeout=10)
        await self.send_gcode_wait_ok("M400", timeout=5)
    
    async def rapid_z_abs(self, z):
        """Rapid movement to absolute Z position."""
        await self.connect()
        await self.send_gcode_wait_ok(f"G90 G0 Z{z}", timeout=10)
        await self.send_gcode_wait_ok("M400", timeout=5)
    async def move_z_abs(self, z, rate):
        """Controlled movement to absolute Z position at specified rate."""
        await self.connect()
        await self.send_gcode_wait_ok(f"G90 G1 Z{z} f{rate}", timeout=10)
        await self.send_gcode_wait_ok("M400", timeout=5)
    async def do_probe(self):
        """Execute probe operation and return measured distance."""
        await self.connect()
        
        # Send probe command directly to writer
        self.device.writer.write("M280 G4 P0.5 G30 M281 G4 P0.5 M400\n".encode())
        await self.device.writer.drain()
        debug_log("[MOTION] Probe command sent, waiting for Z: response...")
        
        # Keep reading responses until we get one with 'Z:' or timeout
        start_time = time.time()
        timeout = 15.0
        
        while time.time() - start_time < timeout:
            try:
                response = await asyncio.wait_for(self.device.line_queue.get(), timeout=1.0)
                debug_log(f"[MOTION] Probe response: {response}")
                print(f"Received: {response}")
                
                if 'Z:' in response:
                    junk, dist = response.split(':')
                    dist = float(dist)
                    print(f"Probe OK distance={dist}")
                    debug_log(f"[MOTION] Probe complete: {dist}")
                    return dist
                else:
                    # Got 'ok' or other response, keep waiting for Z:
                    debug_log(f"[MOTION] Got '{response}', continuing to wait for Z: response...")
                    continue
            except asyncio.TimeoutError:
                # 1 second elapsed, check if total timeout exceeded
                continue
        
        # Timeout - no Z: response received
        debug_log(f"[MOTION] Probe timeout after {timeout}s")
        raise RuntimeError(f"Probe timeout - no Z: response after {timeout}s")
