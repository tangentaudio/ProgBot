"""Async I/O operations for serial device communication and hardware control."""
import asyncio
import serial_asyncio
import time


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


class AsyncSerialDevice:
    """Manages async serial communication with a device."""
    
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.reader = None
        self.writer = None
        # Queue to store full lines received from the device
        self.line_queue = asyncio.Queue()
        self._reader_task = None  # Store task reference for cleanup

    async def connect(self):
        """Initializes connection and background reader."""
        # If already connected, don't create duplicate reader task
        if self.reader is not None and self._reader_task is not None:
            debug_log(f"[{self.port}] Already connected, skipping duplicate connect()")
            return
        
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port,
            baudrate=self.baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        debug_log(f"Connected: {self.port} ({self.baudrate} baud, 8N1)")
        # Run the reader task forever and store reference
        self._reader_task = asyncio.create_task(self._run_reader())

    async def disconnect_async(self):
        """Properly disconnect and wait for reader task to complete."""
        debug_log(f"[{self.port}] disconnect_async called")
        
        # Force close transport to immediately release the serial port
        if self.writer:
            debug_log(f"[{self.port}] Force closing transport...")
            try:
                if hasattr(self.writer, 'transport') and self.writer.transport:
                    self.writer.transport.abort()
                    debug_log(f"[{self.port}] Transport aborted")
                else:
                    self.writer.close()
                    debug_log(f"[{self.port}] Writer closed")
            except Exception as e:
                debug_log(f"[{self.port}] Error closing: {e}")
        
        # Now wait for reader task to actually finish
        if self._reader_task and not self._reader_task.done():
            debug_log(f"[{self.port}] Waiting for reader task to complete...")
            try:
                await asyncio.wait_for(self._reader_task, timeout=1.0)
                debug_log(f"[{self.port}] Reader task completed")
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception) as e:
                debug_log(f"[{self.port}] Reader task ended: {type(e).__name__}")
        
        self.reader = None
        self.writer = None
        self._reader_task = None
        debug_log(f"[{self.port}] disconnect_async complete")

    async def _run_reader(self):
        """Constantly reads from serial and splits by newline."""
        debug_log(f"[{self.port}] Reader task started")
        while True:
            try:
                # readline() specifically waits for the \n delimiter
                read_start = time.time()
                line = await self.reader.readline()
                read_time = time.time() - read_start
                if line:
                    # Clean and put into the queue for the 'await' caller
                    decoded_line = line.decode('latin1').strip()
                    # Only log slow reads (> 1 second) to reduce log spam
                    if read_time > 1.0:
                        debug_log(f"[{self.port}] Slow read: {repr(decoded_line)} (took {read_time:.3f}s)")
                    await self.line_queue.put(decoded_line)
                else:
                    debug_log(f"[{self.port}] readline() returned empty - connection may be closed")
                    break
            except Exception as e:
                debug_log(f"[{self.port}] Error reading: {e}")
                break
        debug_log(f"[{self.port}] Reader task exited")

    async def send_command(self, command, timeout=5.0, newline=True, retries=1):
        """
        Sends a command and awaits the very next full line 
        delimited by \n from the hardware. Retries on timeout.
        
        Args:
            command: Command string to send
            timeout: Total timeout for all retries
            newline: Whether to append newline to command
            retries: Number of attempts to make (default 1 = no retry)
        """
        start_time = time.time()
        
        # Ensure command ends with newline if the hardware expects it
        if newline and not command.endswith('\n'):
            command += '\n'

        # Calculate timeout per attempt
        timeout_per_attempt = timeout / retries if retries > 0 else timeout
        
        last_error = None
        for attempt in range(retries):
            try:
                # Clear any old data in the queue so we don't get a stale response
                queue_size = self.line_queue.qsize()
                if queue_size > 0:
                    debug_log(f"[{self.port}] WARNING: Queue had {queue_size} items, clearing")
                while not self.line_queue.empty():
                    self.line_queue.get_nowait()

                # Send the command
                self.writer.write(command.encode())
                await self.writer.drain()

                # Wait for the next line to arrive in the queue
                result = await asyncio.wait_for(self.line_queue.get(), timeout=timeout_per_attempt)
                # Success! Return the result
                return result
                
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < retries - 1:
                    debug_log(f"[{self.port}] Timeout on attempt {attempt+1}/{retries}, retrying...")
                    await asyncio.sleep(0.1)  # Brief delay before retry
                else:
                    debug_log(f"[{self.port}] All {retries} attempts failed")
        
        # All retries exhausted
        raise TimeoutError(f"Device {self.port} failed to respond after {retries} attempts (timeout={timeout}s)")
