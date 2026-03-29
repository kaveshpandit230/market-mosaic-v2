"""
passenger_wsgi.py — GoDaddy cPanel Python App entry point

Upload this file to your app root directory on GoDaddy.
In cPanel → Setup Python App:
  - Python version: 3.x (latest available)
  - Application root: market_mosaic   (or whatever folder you upload to)
  - Application URL: /  (or a subdomain)
  - Application startup file: passenger_wsgi.py
  - Application Entry point: application

Then in the virtual environment console:
  pip install flask werkzeug

Set environment variable:
  SECRET_KEY = (a long random string, e.g. from: python -c "import secrets; print(secrets.token_hex(32))")
"""

import sys, os

# Add the app directory to the Python path
INTERP = os.path.join(os.environ['HOME'], 'virtualenv', 'market_mosaic', '3.x', 'bin', 'python3')
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

sys.path.insert(0, os.path.dirname(__file__))

from app import app as application  # noqa: F401
