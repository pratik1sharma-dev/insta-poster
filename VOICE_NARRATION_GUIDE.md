# Voice Narration Guide for Cinematic Reels

## ✅ Voice Support Added!

Cinematic reels now support **voiceover narration** using Text-to-Speech (TTS).

---

## 🎙️ TTS Provider Options

### 1. **Edge TTS** (Recommended - FREE)
- **Quality**: ⭐⭐⭐⭐ (Very Good)
- **Cost**: FREE
- **Voices**: Natural Microsoft voices
- **Best For**: Indian English, multiple accents
- **Setup**: `pip install edge-tts`

### 2. **ElevenLabs** (Premium)
- **Quality**: ⭐⭐⭐⭐⭐ (Best)
- **Cost**: Paid (subscription)
- **Voices**: Ultra-natural, emotional
- **Best For**: Professional content
- **Setup**: `pip install elevenlabs` + API key

### 3. **gTTS** (Fallback - FREE)
- **Quality**: ⭐⭐⭐ (Basic)
- **Cost**: FREE
- **Voices**: Google's basic TTS
- **Best For**: Testing
- **Setup**: `pip install gtts` (already installed)

---

## 🚀 Quick Start

### **Install Edge TTS** (Recommended):
```bash
pip install edge-tts
```

### **Generate Cinematic Reel with Voice**:
```bash
# With voice narration
python src/main.py --channel wealthcapsules --cinematic --voice --dry-run

# Without voice (text only)
python src/main.py --channel wealthcapsules --cinematic --dry-run
```

---

## ⚙️ Configuration

### **Set TTS Provider in `.env`**:
```bash
# Default: Edge TTS (free, good quality)
TTS_PROVIDER=edge

# Or use ElevenLabs (requires API key)
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_api_key_here
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# Or use gTTS (basic fallback)
TTS_PROVIDER=gtts
```

### **Configure Voice per Channel** (Optional):

In `channels.yaml`:
```yaml
wealthcapsules:
  name: "WealthCapsules"
  voice_id: "en-IN-NeerjaNeural"  # Female Indian English (Edge TTS)
  # or for ElevenLabs:
  # voice_id: "21m00Tcm4TlvDq8ikWAM"  # Rachel voice
```

---

## 🎬 How It Works

### **Without Voice**:
```
Image + Text Overlay → 4s duration (reading speed)
```

### **With Voice**:
```
Image + Text Overlay + Voice → Duration = Voice length + 0.3s tail
```

**Example**:
- Caption: "Your parents saved ₹50 lakh in FDs over 30 years" (9 words)
- Voice duration: 3.2s
- Total clip duration: 3.5s (3.2s + 0.3s tail)

---

## 🎵 Audio Mixing

### **Background Music Volume**:
```python
# Without voice: Music at 15% volume
cinematic_music_volume = 0.15

# With voice: Music at 8% volume (auto-adjusted)
cinematic_music_volume = 0.08  # Doesn't overpower voice
```

**How it mixes**:
- Voice: 100% volume (clear and prominent)
- Music: 8% volume (subtle background mood)

---

## 🌍 Available Voices

### **Edge TTS Voices (Indian English)**:

```python
# Male voices
"en-IN-PrabhatNeural"  # Default male (warm, clear)

# Female voices
"en-IN-NeerjaNeural"   # Female (professional, clear)
"en-IN-NeerjaExpressive" # Female (expressive, emotional)
```

### **List All Edge TTS Voices**:
```bash
edge-tts --list-voices | grep "en-IN"
```

### **ElevenLabs Voices** (if using premium):
- Rachel: `21m00Tcm4TlvDq8ikWAM` (American English, female)
- Domi: `AZnzlk1XvdvUeBnXmlld` (American English, female)
- Bella: `EXAVITQu4vr4xnSDxMaL` (American English, female)
- Antoni: `ErXwobaYiN019PkySvjV` (American English, male)

---

## 📊 Duration Comparison

### **4-slide Cinematic Reel**:

**Text Only (No Voice)**:
```
Slide 1: 8 words → 4.0s
Slide 2: 10 words → 4.4s
Slide 3: 12 words → 4.9s
Slide 4: 14 words → 5.5s
Total: ~19s + transitions = ~20s
```

**With Voice**:
```
Slide 1: Voice 3.0s → 3.3s
Slide 2: Voice 3.5s → 3.8s
Slide 3: Voice 4.0s → 4.3s
Slide 4: Voice 4.5s → 4.8s
Total: ~16s + transitions = ~17s
```

**Voice reels are typically shorter** because voice is faster than reading.

---

## 🎯 Best Practices

### **1. Caption Length for Voice**:
- ✅ **8-12 words** - Perfect for voice pacing
- ⚠️ **13-14 words** - Maximum, still works
- ❌ **15+ words** - Too fast, feels rushed

### **2. Voice vs Text-Only**:

**Use Voice When**:
- You want professional, polished feel
- Target audience consumes with sound on
- Educational/informative content
- Storytelling with emotional arc

**Use Text-Only When**:
- Target audience watches muted
- Visual impact is more important
- Minimalist aesthetic
- Faster production (no TTS processing)

### **3. Music Selection**:
- With voice: Use **instrumental only**, no lyrics
- Volume: Keep at 8% or lower
- Style: Subtle, non-distracting (ambient, lo-fi)

---

## 🛠️ Troubleshooting

### **"edge-tts not installed"**:
```bash
pip install edge-tts
```

### **"elevenlabs not installed"**:
```bash
pip install elevenlabs
```

### **Voice sounds robotic**:
- Switch from gTTS to Edge TTS
- Use ElevenLabs for most natural voice
- Try different voice IDs

### **Voice too loud/soft**:
Edit `_build_cinematic_clips()` in `cinematic_reel_generator.py`:
```python
f"[1:a]volume=1.0[a]"  # Change 1.0 to 0.8 (softer) or 1.2 (louder)
```

### **Music overpowers voice**:
In `.env`:
```bash
CINEMATIC_MUSIC_VOLUME=0.05  # Even quieter
```

---

## 🔄 Migration from Text-Only

### **Existing Command**:
```bash
python src/main.py --channel wealthcapsules --cinematic
```

### **With Voice**:
```bash
python src/main.py --channel wealthcapsules --cinematic --voice
```

**That's it!** Everything else stays the same.

---

## 📈 Cost Comparison

| Provider | 10,000 characters | Monthly Cost |
|----------|-------------------|--------------|
| **Edge TTS** | FREE | $0 |
| **gTTS** | FREE | $0 |
| **ElevenLabs** | ~8 min audio | $22/month (starter) |

**For testing/hobbyist**: Use Edge TTS (free, great quality)
**For professional**: Consider ElevenLabs (best quality, emotional range)

---

## ✅ Summary

✅ **Voice support added** to cinematic reels
✅ **3 TTS providers** (Edge, ElevenLabs, gTTS)
✅ **Auto-adjusted duration** based on voice length
✅ **Smart music mixing** (8% volume with voice)
✅ **CLI flag**: `--voice` to enable
✅ **Per-channel voice** configuration supported

**Recommended**: Use **Edge TTS** (free) with `en-IN-PrabhatNeural` for Indian audiences.
