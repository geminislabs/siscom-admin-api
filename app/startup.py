"""
Startup utilities for the application.
Handles printing the application banner and initialization messages.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def print_startup_banner() -> None:
    """
    Prints the startup banner with the logo and application info.

    Displays:
    - Application title
    - ASCII art logo with colors
    - Application identifier
    """
    try:
        # Get the path to the logo file
        logo_path = Path(__file__).parent.parent / "assets" / "geminis-labs-logo.txt"

        # Read the logo content
        with open(logo_path, "r", encoding="utf-8") as f:
            logo_content = f.read()

        # Build the banner
        separator = "=" * 60
        title = "\t\tGeminisLabs  :: Siscom Admin API"
        footer = "\t\tsiscom-admin-api • @geminislabs"

        # Print to console and logger
        banner = f"\n{separator}\n{title}\n\n{logo_content}\n{footer}\n{separator}\n"

        print(banner)

    except FileNotFoundError:
        logger.warning(
            f"Logo file not found at {logo_path}. "
            "Startup banner will not be displayed."
        )
    except Exception as e:
        logger.warning(f"Error reading logo file: {e}")
