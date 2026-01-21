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

    async def send_command(self, command, timeout=5.0, newline=True):
        """
        Sends a command and awaits the very next full line 
        delimited by \n from the hardware.
        """
        # Ensure command ends with newline if the hardware expects it
        if newline and not command.endswith('\n'):
            command += '\n'

        # Clear any old data in the queue so we don't get a stale response
        while not self.line_queue.empty():
            self.line_queue.get_nowait()

        # Send the command
        self.writer.write(command.encode())
        await self.writer.drain()

        # Wait for the next line to arrive in the queue
        try:
            return await asyncio.wait_for(self.line_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Device {self.port} failed to return a line within {timeout}s")

    async def read(self, timeout=1.0):
        """Read the next line from the queue."""
        try:
            return await asyncio.wait_for(self.line_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
