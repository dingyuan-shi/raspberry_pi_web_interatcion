"""Core library for the Raspberry Pi web remote-control service.

* :mod:`pi_remote_core.commands` — textual command protocol
* :mod:`pi_remote_core.system_info` — system metrics
* :mod:`pi_remote_core.config` — runtime configuration
"""

from .commands import CommandHandler, HELP_TEXT  # noqa: F401
from . import system_info  # noqa: F401
from . import config  # noqa: F401

__version__ = "1.0.0"
