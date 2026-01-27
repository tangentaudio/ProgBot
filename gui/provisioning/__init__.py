"""Provisioning infrastructure package.

This package provides an expect-like script engine for provisioning
target devices via serial communication.

Key components:
- ProvisioningEngine: Executes scripts against target devices
- ProvisionScript: Defines a sequence of provisioning steps
- ProvisionStep: A single send/expect operation
- ProvisionResult: Result of script execution
- VariableContext: Manages variable substitution
- ResponseAccumulator: Handles serial response buffering and pattern matching
"""

from .models import (
    ProvisionStep,
    ProvisionScript,
    StepResult,
    ProvisionResult,
)
from .engine import ProvisioningEngine
from .variables import VariableContext
from .accumulator import ResponseAccumulator

__all__ = [
    'ProvisioningEngine',
    'ProvisionScript',
    'ProvisionStep',
    'ProvisionResult',
    'StepResult',
    'VariableContext',
    'ResponseAccumulator',
]
