"""Application Launcher — delegates to main entry point."""

import sys


# Fix console encoding on Windows
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')  # type: ignore
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')  # type: ignore
    except Exception:
        pass


def launch_app():
    """Application entry point — delegates to main()."""
    from main import main
    main()


if __name__ == "__main__":
    launch_app()