#!/usr/bin/env python3
"""
Quick verification script to check if the system is properly configured.
"""
import sys
from pathlib import Path


def check_env_file():
    """Check if .env file exists and has required keys."""
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ .env file not found")
        return False

    with open(env_path) as f:
        content = f.read()

    required_keys = ["GEMINI_API_KEY", "POSTIZ_API_KEY"]
    missing = []

    for key in required_keys:
        if key not in content or f"{key}=your_" in content:
            missing.append(key)

    if missing:
        print(f"❌ Missing or placeholder values in .env: {', '.join(missing)}")
        return False

    print("✅ .env file configured")
    return True


def check_channels_config():
    """Check if channels.yaml exists."""
    config_path = Path("src/config/channels.yaml")
    if not config_path.exists():
        print("❌ channels.yaml not found")
        return False

    print("✅ channels.yaml found")
    return True


def check_imports():
    """Check if all required packages are installed."""
    try:
        import google.generativeai
        import pydantic
        import yaml
        import requests
        from PIL import Image
        import schedule
        print("✅ All required packages installed")
        return True
    except ImportError as e:
        print(f"❌ Missing package: {e.name}")
        print("   Run: pip install -r requirements.txt")
        return False


def check_postiz_connection():
    """Check if Postiz API is accessible."""
    try:
        from src.config import settings
        from src.publishers import PostizClient

        client = PostizClient()
        if client.health_check():
            print("✅ Postiz API is accessible")
            return True
        else:
            print("⚠️  Postiz API health check failed")
            print(f"   Check if Postiz is running at: {settings.postiz_api_url}")
            return False
    except Exception as e:
        print(f"⚠️  Could not connect to Postiz: {e}")
        return False


def check_gemini_api():
    """Check if Gemini API key is valid."""
    try:
        import google.generativeai as genai
        from src.config import settings

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-pro")

        # Simple test
        response = model.generate_content("Say 'OK' if you can read this")
        if response.text:
            print("✅ Gemini API key is valid")
            return True
        else:
            print("❌ Gemini API key might be invalid")
            return False
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return False


def main():
    """Run all verification checks."""
    print("="*80)
    print("Daily Insta - Setup Verification")
    print("="*80)
    print()

    checks = [
        ("Environment Configuration", check_env_file),
        ("Channel Configuration", check_channels_config),
        ("Python Packages", check_imports),
        ("Postiz Connection", check_postiz_connection),
        ("Gemini API", check_gemini_api),
    ]

    results = []
    for name, check_func in checks:
        print(f"\n{name}:")
        try:
            results.append(check_func())
        except Exception as e:
            print(f"❌ Error during check: {e}")
            results.append(False)

    print("\n" + "="*80)
    passed = sum(results)
    total = len(results)
    print(f"\nResults: {passed}/{total} checks passed")

    if passed == total:
        print("\n🎉 All checks passed! You're ready to go.")
        print("\nNext step: python src/main.py --channel book_summaries --dry-run")
    else:
        print("\n⚠️  Some checks failed. Please fix the issues above.")

    print("="*80)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
