# Privacy Policy

BirdNET-PiPy is designed with privacy in mind. All processing happens locally on your device.

## What Stays on Your Device

- **Audio recordings** - Raw audio is processed locally and deleted immediately. Only detected bird clips are saved.
- **Detection data** - Bird species, timestamps, and confidence scores stored in a local database.
- **Location** - Your coordinates are stored locally to help filter species predictions.
- **Settings & passwords** - All configuration stays on your device. Passwords are securely hashed.

## What We Don't Collect

- No analytics or telemetry
- No personal information
- No tracking cookies
- No data sent to cloud services

## External Requests

| Feature | Service | What's Sent | When |
|---------|---------|-------------|------|
| Bird images | Wikimedia Commons | Species name | When viewing gallery/details |
| Weather data | Open-Meteo | Coordinates | When a bird is detected* |
| Location search | OpenStreetMap | Search text | When searching in setup |
| Update check | GitHub | Version info | When checking for updates |

*Weather requests are cached hourly to minimize API calls. Weather data is attached to detections to record conditions at the time of sighting.

## BirdNET Model

The AI model runs entirely on your device. No audio is ever sent to external servers for analysis.

## Your Control

- View, export, or delete your data anytime
- Disable recording whenever you want
- All code is open source and auditable

---

*Last updated: January 2026*
