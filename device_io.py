"""Async I/O operations for serial device communication and hardware control."""
import asyncio
import serial_asyncio


class AsyncSerialDevice:
    """Manages async serial communication with a device."""
    
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.reader = None
        self.writer = None
        # Queue to store full lines received from the device
        self.line_queue = asyncio.Queue()

    async def connect(self):
        """Initializes connection and background reader."""
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baudrate
        )
        print(f"Connected: {self.port} ({self.baudrate} baud)")
        # Run the reader task forever
        asyncio.create_task(self._reader_task())

    async def _reader_task(self):
        """Constantly reads from serial and splits by newline."""
        while True:
            try:
                # readline() specifically waits for the \n delimiter
                line = await self.reader.readline()
                if line:
                    # Clean and put into the queue for the 'await' caller
                    decoded_line = line.decode('latin1').strip()
                    await self.line_queue.put(decoded_line)
            except Exception as e:
                print(f"Error reading {self.port}: {e}")
                break

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
        # Ensure command ends with newline if the hardware expects it
        if newline and not command.endswith('\n'):
            command += '\n'

        # Calculate timeout per attempt
        timeout_per_attempt = timeout / retries if retries > 0 else timeout
        
        last_error = None
        for attempt in range(retries):
            try:
                # Clear any old data in the queue so we don't get a stale response
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
                    print(f"[{self.port}] Timeout on attempt {attempt+1}/{retries}, retrying...")
                    await asyncio.sleep(0.1)  # Brief delay before retry
                else:
                    print(f"[{self.port}] All {retries} attempts failed")
        
        # All retries exhausted
        raise TimeoutError(f"Device {self.port} failed to respond after {retries} attempts (timeout={timeout}s)")

    async def read(self, timeout=1.0):
        """Read the next line from the queue."""
        try:
            return await asyncio.wait_for(self.line_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
