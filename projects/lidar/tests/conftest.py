"""Shared fixtures and test configuration."""

import pytest
import numpy as np


def pytest_configure(config):
    """Register markers."""
    config.addinivalue_line("markers", "integration: marks tests requiring S3/network access")
    config.addinivalue_line("markers", "slow: marks tests that are slow")
