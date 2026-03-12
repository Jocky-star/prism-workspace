#!/bin/bash
# Camera photo cleanup — delete photos older than 7 days
# Runs daily via cron

CAMERA_DIR="$HOME/.openclaw/workspace/camera"
TIMELAPSE_DIR="$CAMERA_DIR/timelapse"
RETENTION_DAYS=7

if [ ! -d "$CAMERA_DIR" ]; then
    exit 0
fi

# Delete photo/wellness/raw jpg files older than retention period
find "$CAMERA_DIR" -maxdepth 1 -name "*.jpg" -type f -mtime +$RETENTION_DAYS -delete 2>/dev/null

# Delete old timelapse daily folders
if [ -d "$TIMELAPSE_DIR" ]; then
    find "$TIMELAPSE_DIR" -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null
fi

# Delete old timelapse videos (keep recent ones)
find "$CAMERA_DIR/videos" -maxdepth 1 -name "*.mp4" -type f -mtime +14 -delete 2>/dev/null
