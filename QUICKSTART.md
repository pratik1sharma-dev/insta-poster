# Quick Start Guide

## Initial Setup (One-time)

```bash
# 1. Run setup script
chmod +x setup.sh
./setup.sh

# 2. Edit .env with your API keys
nano .env  # or use your preferred editor

# 3. Activate virtual environment
source venv/bin/activate

# 4. Verify everything is configured
python verify_setup.py
```

## Daily Usage

### Generate and Post Content

```bash
# Dry run (test without posting)
python src/main.py --channel book_summaries --dry-run

# Post with AI-selected topic
python src/main.py --channel book_summaries

# Post specific topic
python src/main.py --channel book_summaries --topic "Atomic Habits by James Clear"
```

### Review Generated Content

After each run, check the output:
```bash
ls -la output/book_summaries/
# Open the most recent timestamp folder to review:
# - strategy.json (AI's decisions)
# - content.json (full content)
# - caption.txt (Instagram caption)
# - images/ (carousel images)
```

### Automated Scheduling

```bash
# Start scheduler (runs in foreground)
python src/scheduler.py

# Run in background (recommended for production)
nohup python src/scheduler.py > scheduler.log 2>&1 &

# Test scheduler without waiting
python src/scheduler.py --test-mode
```

## Common Commands

```bash
# List all configured channels
python src/main.py --list-channels

# Check system status
python verify_setup.py

# View recent outputs
ls -lht output/book_summaries/ | head

# Monitor scheduler logs
tail -f scheduler.log

# Stop background scheduler
pkill -f scheduler.py
```

## Troubleshooting

### "No module named 'src'"
```bash
# Make sure you're in the project directory
cd /Users/pratisharma/personalIdea/daily_insta

# And virtual environment is activated
source venv/bin/activate
```

### "API key not configured"
```bash
# Edit .env and add your keys
nano .env

# Verify configuration
python verify_setup.py
```

### "Postiz connection failed"
```bash
# Check if Postiz is running
curl http://localhost:3000/api/health

# Check .env has correct POSTIZ_API_URL
grep POSTIZ .env
```

### Images not generating properly
The current implementation uses placeholder images. To use actual Gemini Imagen:
- Update `src/agents/image_generator.py` with proper Imagen API calls
- Ensure you have access to Gemini Imagen API

## Adding a New Channel

1. Edit `src/config/channels.yaml`:
```yaml
my_new_channel:
  name: "my_new_channel"
  theme: "Your channel theme"
  target_audience: "Your target audience"
  posting_schedule: "2-3x daily"
  tone: "engaging"
  style_guidelines: "Your style preferences"
  curated_topics:
    - "Topic 1"
    - "Topic 2"
  allow_ai_discovery: true
  visual_preferences:
    - "Preference 1"
    - "Preference 2"
```

2. Test it:
```bash
python src/main.py --channel my_new_channel --dry-run
```

3. Add to scheduler:
```bash
python src/scheduler.py  # Automatically includes all channels
```

## Production Checklist

Before running 24/7:

- [ ] Test dry-run multiple times
- [ ] Review at least 5-10 generated posts
- [ ] Verify Postiz posts successfully
- [ ] Set up proper logging and monitoring
- [ ] Configure proper error notifications
- [ ] Review Instagram's posting limits (avoid spam)
- [ ] Have moderation process for spot-checking
- [ ] Backup output directory regularly
