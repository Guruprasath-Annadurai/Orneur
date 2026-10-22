"""Foundation-X control-plane checks.

These helpers fail closed on lifecycle and data-admission fixtures.
They do not train a model and they do not write the acceptance register.
"""

from orca.foundation_x.lifecycle import LifecycleDecision, assess_lifecycle

__all__ = ["LifecycleDecision", "assess_lifecycle"]
