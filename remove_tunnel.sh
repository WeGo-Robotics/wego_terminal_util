#!/bin/bash

TARGET_HOST=$1

case "$TARGET_HOST" in
    "?"|h|-h|--help|help)
        cat <<'EOF'

Usage: remove_tunnel <device_ip>

  device_ip : Target device IP or hostname to remove

Example:
  remove_tunnel 192.168.0.10

This removes matching key files from ~/.ssh and entries from ~/.ssh/config.

EOF
        exit 0
        ;;
esac

# 1. Get input if argument is missing
if [ -z "$TARGET_HOST" ]; then
    read -p "Enter Target IP/Hostname to remove: " TARGET_HOST
fi

if [ -z "$TARGET_HOST" ]; then
    echo "[Error] No input provided. Exiting."
    exit 1
fi

SSH_DIR="$HOME/.ssh"
CONFIG_FILE="$SSH_DIR/config"
# Replace dots with underscores for key file matching
HOST_SAFE=$(echo "$TARGET_HOST" | sed 's/\./_/g')

echo ""
echo "[Status] Removing ALL entries related to: $TARGET_HOST"
echo "--------------------------------------------------"

# 2. Delete Key Files
echo "[Process] Deleting matching key files..."
# Deletes id_rsa_HOST_SAFE and id_rsa_HOST_SAFE.pub if they exist
find "$SSH_DIR" -name "id_rsa_${HOST_SAFE}*" -type f -delete
echo "- Cleanup of key files complete."

# 3. Remove Sections from Config
if [ -f "$CONFIG_FILE" ]; then
    echo "[Process] Removing Host/HostName matches from config..."
    
    # Use awk to filter out the matching Host/HostName block
    # Logic: 
    # - If a line matches 'Host target' or 'HostName target', start skipping.
    # - If skipping and a new 'Host ' line appears, stop skipping.
    # - Print lines only when not skipping.
    
    TEMP_CONFIG=$(mktemp)
    awk -v target="$TARGET_HOST" '
        BEGIN { skip = 0 }
        $1 == "Host" && $2 == target { skip = 1; next }
        $1 == "HostName" && $2 == target { skip = 1; next }
        skip == 1 && $1 == "Host" { skip = 0 }
        !skip { print $0 }
    ' "$CONFIG_FILE" > "$TEMP_CONFIG"
    
    mv "$TEMP_CONFIG" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    
    echo "- Config file updated (UTF-8 without BOM)."
fi

echo "--------------------------------------------------"
echo "[Finish] Cleanup complete."
echo ""