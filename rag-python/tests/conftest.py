"""Global test configuration and fixtures for pytest."""

import os
import pytest

# Default test suite runs in dev mode unless overridden
os.environ.setdefault("AUTH_MODE", "dev")
