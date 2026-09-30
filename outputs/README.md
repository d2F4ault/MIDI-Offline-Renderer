# PianoFall Outputs Archive

This directory stores finished, silent 1920×1200 MP4 falling-notes piano visualizations rendered by the automated pipeline.

## Directory Structure

Rendered videos are archived chronologically by date of processing:

```text
outputs/
  └── YYYY-MM-DD/
        └── <original-midi-stem>.mp4
```

## Specifications

- **Resolution**: 1920 × 1200
- **Framerate**: 60 FPS
- **Video Codec**: H.264 / AVC (`libx264`, High Profile, CRF 18, `yuv420p`)
- **Audio**: Silent (no audio track embedded)
- **Container**: MP4 (`+faststart` web-optimized header)
