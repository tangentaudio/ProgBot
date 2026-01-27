"""Motion control (smoothie) device operations."""
import asyncio
import time
from device_io import AsyncSerialDevice
from logger import get_logger

log = get_logger(__name__)


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
                    log.debug(f"[MotionController] Connection dead, reconnecting to {self.port}")
                    self.device = None
            except Exception as e:
                log.debug(f"[MotionController] Health check failed: {e}, reconnecting")
                self.device = None
        
        if self.device is None:
            log.debug(f"[MotionController] Connecting to {self.port}")
            self.device = AsyncSerialDevice(self.port, self.baudrate)
            await self.device.connect()

    async def send_gcode_wait_ok(self, cmd, timeout=5):
        """Send GCode command and wait for 'ok' response."""
        if not self.device:
            raise RuntimeError("motion device not connected")
        log.debug(f"[MOTION] Sending: {cmd}")
        response = await self.device.send_command(cmd, timeout=timeout)
        if not 'ok' in response:
            raise RuntimeError("not ok")
                
    async def init(self, do_homing=True):
        """Initialize mechanical systems (homing, coordinates, etc)."""
        await self.connect()
        log.info(f"Clearing alarm...")
        await self.device.send_command("M999")

        homed = False
        if do_homing:
            # Always perform homing at cycle start for safety
            # Smoothie with must_be_homed=false won't report Alarm when unhomed,
            # so we cannot reliably detect unhomed state from status query alone.
            # The safest approach is to always home at cycle start.
            log.info(f"Performing homing cycle...")
            try:
                await self.send_gcode_wait_ok("$H", timeout=20)
                homed = True
                log.debug(f"[MOTION] Homing completed successfully")
            except Exception as e:
                log.error(f"[MOTION] Homing failed: {e}")
                raise RuntimeError(f"Homing failed: {e}")
    
        # Reset work coordinates after homing
        if homed:
            log.info(f"Set G54 zero...")
            await self.send_gcode_wait_ok("G92 X0 Y0 Z0")
    
        log.info(f"Retract BLTouch...")
        await self.send_gcode_wait_ok("M281 G4 P0.5 M400")
    
        log.info(f"Init coord sys and units...")
        await self.send_gcode_wait_ok("G90 G54 G21")

    async def motors_off(self):
        """Turn off motors."""
        await self.connect()
        log.info(f"Motors off.")
        await self.send_gcode_wait_ok("M18")
     
    async def rapid_xy_abs(self, x, y):
        """Rapid movement to absolute XY position."""
        await self.connect()
        log.info(f"rapid_xy_abs x={x} y={y}")
        await self.send_gcode_wait_ok(f"G90 G0 X{x} Y{y}", timeout=10)
        await self.send_gcode_wait_ok("M400", timeout=5)

    async def rapid_xy_rel(self, dist_x, dist_y):
        """Rapid movement by relative XY distance."""
        await self.connect()
        log.info(f"rapid_xy_rel dist_x={dist_x} dist_y={dist_y}")
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

    async def move_z_rel(self, dist, rate=500):
        """Controlled relative Z movement at specified rate."""
        await self.connect()
        await self.send_gcode_wait_ok(f"G91 G1 Z{dist} F{rate}", timeout=10)
        await self.send_gcode_wait_ok("M400", timeout=5)
        await self.send_gcode_wait_ok("G90", timeout=2)  # Back to absolute mode

    async def get_position(self):
        """Query current machine position. Returns dict with 'x', 'y', 'z' keys."""
        await self.connect()
        
        # Send status query
        self.device.writer.write("?\n".encode())
        await self.device.writer.drain()
        
        # Read responses until we get status or timeout
        start_time = time.time()
        while time.time() - start_time < 2.0:
            try:
                response = await asyncio.wait_for(self.device.line_queue.get(), timeout=0.5)
                log.debug(f"[MOTION] Position query response: {response}")
                if '<' in response and '>' in response:
                    # Parse status: <Idle|MPos:0.000,0.000,0.000|WPos:0.000,0.000,0.000>
                    # We want WPos (work position)
                    if 'WPos:' in response:
                        wpos_start = response.find('WPos:') + 5
                        wpos_end = response.find('|', wpos_start) if '|' in response[wpos_start:] else response.find('>', wpos_start)
                        if wpos_end == -1:
                            wpos_end = response.find('>')
                        wpos_str = response[wpos_start:wpos_end]
                        parts = wpos_str.split(',')
                        if len(parts) >= 3:
                            return {
                                'x': float(parts[0]),
                                'y': float(parts[1]),
                                'z': float(parts[2])
                            }
                    elif 'MPos:' in response:
                        # Fallback to machine position if no work position
                        mpos_start = response.find('MPos:') + 5
                        mpos_end = response.find('|', mpos_start)
                        if mpos_end == -1:
                            mpos_end = response.find('>')
                        mpos_str = response[mpos_start:mpos_end]
                        parts = mpos_str.split(',')
                        if len(parts) >= 3:
                            return {
                                'x': float(parts[0]),
                                'y': float(parts[1]),
                                'z': float(parts[2])
                            }
            except asyncio.TimeoutError:
                continue
        
        raise RuntimeError("Position query timeout")

    async def do_probe(self):
        """Execute probe operation and return measured distance."""
        await self.connect()
        
        # Send probe command directly to writer
        self.device.writer.write("M280 G4 P0.5 G30 M281 G4 P0.5 M400\n".encode())
        await self.device.writer.drain()
        log.debug("[MOTION] Probe command sent, waiting for Z: response...")
        
        # Keep reading responses until we get one with 'Z:' or timeout
        start_time = time.time()
        timeout = 15.0
        
        while time.time() - start_time < timeout:
            try:
                response = await asyncio.wait_for(self.device.line_queue.get(), timeout=1.0)
                log.debug(f"[MOTION] Probe response: {response}")
                log.info(f"Received: {response}")
                
                if 'Z:' in response:
                    junk, dist = response.split(':')
                    dist = float(dist)
                    log.info(f"Probe OK distance={dist}")
                    log.debug(f"[MOTION] Probe complete: {dist}")
                    return dist
                else:
                    # Got 'ok' or other response, keep waiting for Z:
                    log.debug(f"[MOTION] Got '{response}', continuing to wait for Z: response...")
                    continue
            except asyncio.TimeoutError:
                # 1 second elapsed, check if total timeout exceeded
                continue
        
        # Timeout - no Z: response received
        log.debug(f"[MOTION] Probe timeout after {timeout}s")
        raise RuntimeError(f"Probe timeout - no Z: response after {timeout}s")
