"""Data models for provisioning scripts and results.

These dataclasses define the structure of provisioning scripts and
the results of executing them.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ProvisionStep:
    """A single step in a provisioning script.
    
    Each step can send a command, wait for a response pattern,
    and capture data from the response.
    """
    
    # What to send (optional - some steps just wait for data)
    send: Optional[str] = None  # Command template: "SET SN {serial_number}"
    
    # What to expect back - can have MULTIPLE named capture groups
    # Regex pattern: "MAC=(?P<mac>[0-9A-F:]+).*BT=(?P<bt>\\w+)"
    expect: Optional[str] = None
    
    # Optional: multiple acceptable patterns (first match wins)
    expect_any: Optional[List[str]] = None
    
    # Noise handling (override global settings if provided)
    ignore_patterns: Optional[List[str]] = None  # Regex patterns to skip
    strip_prompt: Optional[str] = None  # Prompt string to strip (e.g., "> ")
    multiline: bool = True  # Accumulate lines until pattern matches
    
    # Timing
    timeout: float = 5.0  # Seconds to wait for expect pattern
    delay_before: float = 0.0  # Delay before sending
    delay_after: float = 0.0  # Delay after receiving
    
    # Error handling / retries
    retries: int = 1  # Number of attempts (1 = no retry, 2 = retry once, etc.)
    retry_delay: float = 0.5  # Seconds to wait between retry attempts
    on_fail: str = 'abort'  # 'abort' | 'skip' | 'continue'
    post_delay: float = 0.0  # Delay after step completes (before next step)
    
    # Description for logging/debugging
    description: Optional[str] = None


@dataclass
class ProvisionScript:
    """Complete provisioning script for a panel.
    
    Contains a list of steps to execute and global defaults
    that apply to all steps unless overridden.
    """
    
    name: str = "default"
    steps: List[ProvisionStep] = field(default_factory=list)
    
    # Global defaults (can be overridden per-step)
    default_timeout: float = 5.0
    default_retries: int = 1
    default_retry_delay: float = 0.5
    default_on_fail: str = 'abort'
    default_post_delay: float = 0.0
    
    # Global noise filtering (applied to all steps unless overridden)
    global_ignore_patterns: Optional[List[str]] = None  # e.g., [r"^\[DEBUG\]"]
    global_strip_prompt: Optional[str] = None  # e.g., "> " or "# "
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProvisionScript':
        """Create a ProvisionScript from a dictionary (e.g., from JSON/panel file).
        
        Args:
            data: Dictionary with script configuration
            
        Returns:
            ProvisionScript instance
        """
        steps = []
        for step_data in data.get('steps', []):
            steps.append(ProvisionStep(**step_data))
        
        return cls(
            name=data.get('name', 'default'),
            steps=steps,
            default_timeout=data.get('default_timeout', 5.0),
            default_retries=data.get('default_retries', 1),
            default_retry_delay=data.get('default_retry_delay', 0.5),
            default_on_fail=data.get('default_on_fail', 'abort'),
            default_post_delay=data.get('default_post_delay', 0.0),
            global_ignore_patterns=data.get('global_ignore_patterns'),
            global_strip_prompt=data.get('global_strip_prompt'),
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'steps': [
                {k: v for k, v in step.__dict__.items() if v is not None}
                for step in self.steps
            ],
            'default_timeout': self.default_timeout,
            'default_retries': self.default_retries,
            'default_on_fail': self.default_on_fail,
            'default_post_delay': self.default_post_delay,
            'global_ignore_patterns': self.global_ignore_patterns,
            'global_strip_prompt': self.global_strip_prompt,
        }


@dataclass
class StepResult:
    """Result of executing a single provisioning step.
    
    Contains the outcome, captured data, and debugging information.
    """
    
    success: bool
    step_index: int = 0  # Which step this result is for
    response: Optional[str] = None  # Raw response received (full buffer)
    matched_text: Optional[str] = None  # The specific text that matched
    captures: dict = field(default_factory=dict)  # All named capture groups
    error: Optional[str] = None  # Error message if failed
    elapsed: float = 0.0  # Time taken in seconds
    lines_received: int = 0  # Total lines accumulated
    retries_used: int = 0  # How many retries were needed


@dataclass
class ProvisionResult:
    """Result of executing a complete provisioning script.
    
    Contains the overall outcome and results from each step.
    """
    
    success: bool
    steps_completed: int
    total_steps: int
    captures: dict = field(default_factory=dict)  # All captured data merged
    step_results: List[StepResult] = field(default_factory=list)
    error: Optional[str] = None  # Overall error message if failed
    elapsed: float = 0.0  # Total time taken
    
    def get_failed_step(self) -> Optional[StepResult]:
        """Get the first failed step result, if any."""
        for result in self.step_results:
            if not result.success:
                return result
        return None
