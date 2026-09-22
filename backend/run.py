"""
MicroFish Backend Startup Entry Point
"""

import os
import sys

# Fix Windows console character encoding: set UTF-8 encoding before all imports
if sys.platform == 'win32':
    # Set environment variable to ensure Python uses UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Reconfigure standard output streams to UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """Main function"""
    # Validate configuration
    errors = Config.validate()
    if errors:
        print("Configuration Errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check the configuration in the .env file")
        sys.exit(1)
    
    # Create application
    app = create_app()
    
    # Get runtime configuration
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG
    
    # Keep the development server from restarting while a simulation subprocess
    # is active. Flask's reloader terminates child simulations whenever source
    # files change, which can leave a healthy run looking failed or stopped.
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)


if __name__ == '__main__':
    main()

