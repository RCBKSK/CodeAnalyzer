#!/usr/bin/env python3
"""
Main entry point that runs Flask development server with detailed logging
"""
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_app import app

if __name__ == "__main__":
    # Set up environment  
    os.makedirs('data', exist_ok=True)
    
    # Run Flask development server with debug mode for detailed logs
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
