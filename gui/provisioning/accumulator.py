"""Response accumulator for handling serial output.

The ResponseAccumulator collects lines from serial output, applies
noise filtering, and searches for expected patterns.
"""

import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class ResponseAccumulator:
    """Accumulates serial lines and searches for patterns.
    
    Handles real-world serial behavior where debug logs, prompts,
    and other noise may be interspersed with expected responses.
    
    Buffer limits (text-only, modest data volume):
    - Max 32 KB total accumulated text
    - Max 4 KB per line
    - Lines exceeding limit are truncated with warning
    """
    
    MAX_BUFFER_SIZE = 32 * 1024  # 32 KB total
    MAX_LINE_SIZE = 4 * 1024  # 4 KB per line
    
    def __init__(
        self,
        ignore_patterns: Optional[List[str]] = None,
        strip_prompt: Optional[str] = None
    ):
        r"""Initialize the accumulator.
        
        Args:
            ignore_patterns: List of regex patterns to filter out (e.g., [r"^\[DEBUG\]"])
            strip_prompt: Prompt string to strip from line starts (e.g., "> ")
        """
        self.buffer: List[str] = []  # All lines received (raw)
        self.filtered_buffer: List[str] = []  # Lines after noise filtering
        self.buffer_size = 0  # Current buffer size in bytes
        
        # Compile ignore patterns for efficiency
        self.ignore_patterns: List[re.Pattern] = []
        if ignore_patterns:
            for pattern in ignore_patterns:
                try:
                    self.ignore_patterns.append(re.compile(pattern))
                except re.error as e:
                    logger.warning(f"Invalid ignore pattern '{pattern}': {e}")
        
        self.strip_prompt = strip_prompt
    
    def add_line(self, line: str) -> None:
        """Add a line to the buffer, applying filters.
        
        Lines are truncated at MAX_LINE_SIZE bytes.
        Oldest lines are dropped if buffer exceeds MAX_BUFFER_SIZE.
        
        Args:
            line: The line to add (without trailing newline)
        """
        # Truncate oversized lines
        if len(line) > self.MAX_LINE_SIZE:
            logger.warning(
                f"Line truncated from {len(line)} to {self.MAX_LINE_SIZE} bytes"
            )
            line = line[:self.MAX_LINE_SIZE]
        
        # Always add to raw buffer
        self.buffer.append(line)
        self.buffer_size += len(line) + 1  # +1 for conceptual newline
        
        # Drop oldest lines if over limit
        while self.buffer_size > self.MAX_BUFFER_SIZE and len(self.buffer) > 1:
            dropped = self.buffer.pop(0)
            self.buffer_size -= len(dropped) + 1
            # Also drop from filtered if present
            if self.filtered_buffer and self.filtered_buffer[0] == dropped:
                self.filtered_buffer.pop(0)
            logger.debug("Dropped oldest line due to buffer limit")
        
        # Apply prompt stripping
        filtered_line = line
        if self.strip_prompt and line.startswith(self.strip_prompt):
            filtered_line = line[len(self.strip_prompt):]
        
        # Check against ignore patterns
        for pattern in self.ignore_patterns:
            if pattern.search(filtered_line):
                logger.debug(f"Filtered out line: {line[:50]}...")
                return  # Don't add to filtered buffer
        
        self.filtered_buffer.append(filtered_line)
    
    def search(self, pattern: str) -> Tuple[bool, Optional[str], dict]:
        """Search for pattern in accumulated text.
        
        Searches in two ways:
        1. Each individual filtered line
        2. The concatenated filtered buffer (for multi-line patterns)
        
        Args:
            pattern: Regex pattern to search for (may contain named groups)
            
        Returns:
            Tuple of (matched: bool, matched_text: str or None, captures: dict)
            captures contains all named groups from the pattern
        """
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            logger.error(f"Invalid search pattern '{pattern}': {e}")
            return (False, None, {})
        
        # First, try each line individually (most common case)
        for line in self.filtered_buffer:
            match = compiled.search(line)
            if match:
                captures = match.groupdict()
                logger.debug(f"Pattern matched in line: {line[:50]}...")
                return (True, match.group(0), captures)
        
        # Then try the full concatenated text (for multi-line patterns)
        full_text = self.get_full_text()
        match = compiled.search(full_text)
        if match:
            captures = match.groupdict()
            logger.debug(f"Pattern matched in full text")
            return (True, match.group(0), captures)
        
        return (False, None, {})
    
    def search_any(self, patterns: List[str]) -> Tuple[bool, Optional[str], dict, int]:
        """Search for any of the given patterns (first match wins).
        
        Args:
            patterns: List of regex patterns to try
            
        Returns:
            Tuple of (matched, matched_text, captures, pattern_index)
            pattern_index is which pattern matched (-1 if none)
        """
        for i, pattern in enumerate(patterns):
            matched, text, captures = self.search(pattern)
            if matched:
                return (True, text, captures, i)
        return (False, None, {}, -1)
    
    def get_full_text(self) -> str:
        """Return all filtered lines joined with newlines."""
        return '\n'.join(self.filtered_buffer)
    
    def get_raw_text(self) -> str:
        """Return all raw lines joined with newlines (unfiltered)."""
        return '\n'.join(self.buffer)
    
    def clear(self) -> None:
        """Clear buffers for next step."""
        self.buffer.clear()
        self.filtered_buffer.clear()
        self.buffer_size = 0
    
    @property
    def line_count(self) -> int:
        """Number of lines in the raw buffer."""
        return len(self.buffer)
    
    @property
    def filtered_line_count(self) -> int:
        """Number of lines in the filtered buffer."""
        return len(self.filtered_buffer)
