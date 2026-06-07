"""Run the local Web UI when the package is invoked with python -m pyreuser3.web.

The module delegates directly to the server entry point.
"""

from .server import main

if __name__ == "__main__":
    main()
