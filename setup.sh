#!/bin/bash
# Setup script for Daily Insta

echo "Setting up Daily Insta..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from example..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env file with your API keys:"
    echo "   - GEMINI_API_KEY"
    echo "   - POSTIZ_API_KEY"
    echo ""
fi

# Create output directory
mkdir -p output

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your API keys"
echo "2. Run: source venv/bin/activate"
echo "3. Test: python src/main.py --list-channels"
echo "4. Dry run: python src/main.py --channel book_summaries --dry-run"
echo ""
