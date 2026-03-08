# Daily Insta - AI-Powered Instagram Automation

Automated Instagram content generation and posting system powered by Google Gemini and Postiz.

## Features

- 🤖 AI-driven content ideation and planning
- 🎨 Automated image generation for carousel posts
- ✍️ Smart caption and hashtag generation
- 📤 Automated posting via Postiz
- 🔄 Multi-channel support with config-driven approach
- 📊 Scalable architecture for diverse content types

## Architecture

```
Content Pipeline:
1. Content Strategist → Decides topic & hook strategy
2. Content Generator → Creates captions & hashtags
3. Image Generator → Generates carousel images
4. Postiz Publisher → Posts to Instagram
```

## Project Structure

```
daily_insta/
├── src/
│   ├── agents/
│   │   ├── content_strategist.py  # Topic ideation
│   │   ├── content_generator.py   # Captions & hashtags
│   │   └── image_generator.py     # Image creation
│   ├── publishers/
│   │   └── postiz_client.py       # Postiz API integration
│   ├── config/
│   │   └── channels.yaml          # Channel configurations
│   ├── models/
│   │   └── content_models.py      # Data models
│   └── main.py                    # Orchestrator
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. Run the setup script:
```bash
chmod +x setup.sh
./setup.sh
```

2. Configure environment variables:
```bash
# Edit .env with your API keys
GEMINI_API_KEY=your_actual_gemini_key
POSTIZ_API_KEY=your_actual_postiz_key
```

3. Activate virtual environment:
```bash
source venv/bin/activate
```

4. Verify setup:
```bash
# List available channels
python src/main.py --list-channels

# Test with dry run
python src/main.py --channel book_summaries --dry-run
```

## Usage

### Single Post (Manual)
```bash
# Dry run (generate content without posting)
python src/main.py --channel book_summaries --dry-run

# Post with specific topic
python src/main.py --channel book_summaries --topic "Atomic Habits by James Clear"

# Post with AI-selected topic
python src/main.py --channel book_summaries
```

### Automated Scheduling
```bash
# Schedule all channels (2 posts/day each)
python src/scheduler.py

# Schedule specific channel with custom frequency
python src/scheduler.py --channel book_summaries --posts-per-day 3

# Test mode (run all jobs once immediately)
python src/scheduler.py --test-mode
```

### Output
All generated content is saved to `output/{channel}/{timestamp}/`:
- `strategy.json` - AI's strategy decisions
- `content.json` - Generated captions and slide content
- `caption.txt` - Instagram caption with hashtags
- `images/` - Generated carousel images
- `post_result.json` - Publishing result
- `pipeline.log` - Detailed execution log

## Configuration

Each channel is defined in `channels.yaml` with:
- Channel name and theme
- Content strategy parameters
- Curated topics list
- Posting schedule
- Style guidelines
- Visual preferences

## Verification Checklist

Before running in production:

- [ ] **API Keys Configured**: `.env` file has valid `GEMINI_API_KEY` and `POSTIZ_API_KEY`
- [ ] **Postiz Running**: Postiz service is accessible at configured URL
- [ ] **Dry Run Test**: `python src/main.py --channel book_summaries --dry-run` completes successfully
- [ ] **Output Review**: Check generated content in `output/` directory looks good
- [ ] **Channel Config**: Review and customize `src/config/channels.yaml` for your needs
- [ ] **First Live Post**: Run single post manually before enabling scheduler
- [ ] **Scheduler Test**: Run `python src/scheduler.py --test-mode` to verify scheduling

## Tech Stack

- **Python 3.10+**
- **Google Gemini** - Content & image generation
- **Postiz API** - Instagram posting
- **Pydantic** - Data validation
- **PyYAML** - Configuration management
- **Schedule** - Task scheduling
