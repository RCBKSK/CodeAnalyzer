#!/usr/bin/env python3
"""
Custom Flask startup script that provides the detailed logging format
"""
import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    # Import and run the Flask app directly
    from web_app import app
    
    # Set up environment
    os.makedirs('data', exist_ok=True)
    
    # Run Flask development server with debug mode for detailed logs
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)