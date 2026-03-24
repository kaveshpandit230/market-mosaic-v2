#!/bin/bash
# Market Mosaic — Quick Setup Script
# Run this after uploading to GoDaddy or locally

echo "Setting up Market Mosaic..."

# Install dependencies
pip install flask werkzeug razorpay twilio flask-mail --break-system-packages 2>/dev/null || \
pip install flask werkzeug razorpay twilio flask-mail

echo ""
echo "✓ Dependencies installed"
echo ""

# Generate a secret key
SK=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "✓ Generated SECRET_KEY: $SK"
echo "  → Add this to your environment variables on GoDaddy"
echo ""

echo "✓ Setup complete. Start with: python app.py"
echo ""
echo "Next steps:"
echo "  1. Add environment variables (SECRET_KEY, RAZORPAY_KEY_ID, etc.)"
echo "  2. See .env.example for all available variables"
echo "  3. See README.md for full GoDaddy deployment guide"
echo "  4. Make yourself admin: python make_admin.py your@email.com"
