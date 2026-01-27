#!/bin/bash

# ===== 1. Process User Input =====
TARGET_USER=$1
TARGET_HOST=$2
TARGET_PORT=$3
CONFIG_ALIAS=$4

[ -z "$TARGET_USER" ] && read -p "Enter target username: " TARGET_USER
[ -z "$TARGET_HOST" ] && read -p "Enter target IP/Hostname: " TARGET_HOST
[ -z "$TARGET_PORT" ] && read -p "Enter SSH Port (Default 22): " TARGET_PORT
TARGET_PORT=${TARGET_PORT:-22}

# Set Alias and Key Name Prefix
if [ -z "$CONFIG_ALIAS" ]; then
    CONFIG_ALIAS="$TARGET_HOST"
    KEY_NAME_PREFIX="${TARGET_HOST//./_}"
else
    KEY_NAME_PREFIX="$CONFIG_ALIAS"
fi

# ===== 2. Fix Host Identification Changed =====
echo "[PROC] Clearing old host keys for $TARGET_HOST..."
ssh-keygen -R "$TARGET_HOST" > /dev/null 2>&1
if [ "$TARGET_PORT" != "22" ]; then
    ssh-keygen -R "[$TARGET_HOST]:$TARGET_PORT" > /dev/null 2>&1
fi

# ===== 3. Set Paths =====
SSH_DIR="$HOME/.ssh"
CONFIG_PATH="$SSH_DIR/config"
KEY_PATH="$SSH_DIR/id_rsa_$KEY_NAME_PREFIX"
PUB_PATH="$KEY_PATH.pub"

# ===== 4. Check for Duplicate =====
if [ -f "$CONFIG_PATH" ]; then
    if grep -iq "Host $CONFIG_ALIAS" "$CONFIG_PATH"; then
        echo "[INFO] Config for '$CONFIG_ALIAS' already exists."
        echo "Connection Command: ssh $CONFIG_ALIAS"
        exit 0
    fi
fi

# ===== 5. Key Generation =====
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ ! -f "$KEY_PATH" ]; then
    echo "[PROC] Generating key: $KEY_PATH"
    ssh-keygen -t rsa -b 4096 -f "$KEY_PATH" -N "" -C "$(whoami)@$(hostname)"
fi

# ===== 6. Transfer Public Key =====
echo "[PROC] Registering public key. Password may be required."
# Using ssh-copy-id is the standard Linux way to handle this safely
ssh-copy-id -o StrictHostKeyChecking=no -i "$PUB_PATH" -p "$TARGET_PORT" "$TARGET_USER@$TARGET_HOST"

if [ $? -ne 0 ]; then
    echo "[ERROR] Transfer failed."
    exit 1
fi

# ===== 7. Register Config File (Standard UTF-8) =====
echo
read -p "Add to SSH config? (Y/N): " ADD_CONF
if [[ "$ADD_CONF" =~ ^[Yy]$ ]]; then
    echo "[PROC] Appending to config..."
    
    # Append block to config file
    cat >> "$CONFIG_PATH" << EOF

Host $CONFIG_ALIAS
    HostName $TARGET_HOST
    User $TARGET_USER
    Port $TARGET_PORT
    IdentityFile $KEY_PATH
EOF

    chmod 600 "$CONFIG_PATH"
    echo "[DONE] Config registered successfully!"
fi

echo
echo "Connection Command: ssh $CONFIG_ALIAS"