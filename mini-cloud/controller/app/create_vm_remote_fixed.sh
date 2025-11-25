#!/usr/bin/env bash
set -euo pipefail

MASTER=""
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes"
SCP_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes"

DEFAULT_ISO_SR_UUID="55dab0cc-d86e-0561-3cea-5cf0d4fa4472"
ISO_SR_PATH="/var/opt/iso_images"

usage() {
    echo "Usage: $0 --host HOST --name NAME --template TEMPLATE --cpu N --ram MB --disk SIZE --network NETWORK --ssh-key PATH"
    exit 1
}

if [[ $# -eq 0 ]]; then usage; fi

# ----------------- Parse args -----------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) MASTER="$2"; shift ;;
        --name) VM_NAME="$2"; shift ;;
        --template) TEMPLATE="$2"; shift ;;
        --cpu) VCPUS="$2"; shift ;;
        --ram) RAM_MB="$2"; shift ;;
        --disk) DISK_SIZE="$2"; shift ;;
        --network) NETWORK="$2"; shift ;;
        --ssh-key) SSH_KEY_FILE="$2"; shift ;;
        *) echo "[ERROR] Unknown argument: $1"; usage ;;
    esac
    shift
done

if [[ -z "$MASTER" ]]; then 
    echo "[ERROR] --host is required"
    exit 1
fi

# Expand ~ if used
SSH_KEY_FILE="${SSH_KEY_FILE/#\~/$HOME}"

if [[ ! -f "$SSH_KEY_FILE" ]]; then
    echo "[ERROR] SSH key file not found: $SSH_KEY_FILE"
    exit 1
fi

SSH_CMD="ssh $SSH_OPTS root@$MASTER"
SCP_CMD="scp $SCP_OPTS"

echo "[INFO] Running VM creation on host: $MASTER"

# ----------------- ISO SR selection -----------------
case "$MASTER" in
    "10.20.24.40") ISO_SR_UUID="55dab0cc-d86e-0561-3cea-5cf0d4fa4472" ;;
    "10.20.24.38") ISO_SR_UUID="9a75933f-64b0-fa8c-055d-8368f116361c" ;;
    *) ISO_SR_UUID="$DEFAULT_ISO_SR_UUID" ;;
esac

# ----------------- WORKDIR + cloud-init ISO generation -----------------
SAFE_NAME=$(echo "$VM_NAME" | tr ' ' '_' | tr '/' '_')
WORKDIR="/tmp/vmseed_${SAFE_NAME}_$(date +%s)"
mkdir -p "$WORKDIR"

ISO_NAME="${SAFE_NAME}-seed.iso"
trap 'rm -rf "$WORKDIR" "$ISO_NAME" >/dev/null 2>&1 || true' EXIT

remote() { $SSH_CMD -- "$@"; }
remote_quiet() { $SSH_CMD -- "$@" >/dev/null 2>&1 || true; }

# Generate cloud-init config
SSH_KEY_CONTENT=$(sed 's/"/\\"/g' "$SSH_KEY_FILE")

cat > "$WORKDIR/user-data" << EOF
#cloud-config
users:
- name: ubuntu
  sudo: ALL=(ALL) NOPASSWD:ALL
  ssh_authorized_keys:
  - $SSH_KEY_CONTENT
ssh_pwauth: false
disable_root: true
EOF

cat > "$WORKDIR/meta-data" << EOF
instance-id: $SAFE_NAME
local-hostname: $SAFE_NAME
EOF

# ISO creation requires genisoimage
if ! command -v genisoimage >/dev/null 2>&1; then
    echo "[ERROR] genisoimage not found. Install with: apt install genisoimage"
    exit 1
fi

genisoimage -quiet -output "$ISO_NAME" -volid cidata -joliet -rock \
    "$WORKDIR/meta-data" "$WORKDIR/user-data"

# Copy ISO to host
remote_quiet "mkdir -p $ISO_SR_PATH"
$SCP_CMD "$ISO_NAME" root@"$MASTER":"$ISO_SR_PATH/"
remote_quiet "xe sr-scan uuid=$ISO_SR_UUID || true"
sleep 2

# Import ISO into SR
ISO_VDI=$(remote "xe vdi-list sr-uuid=$ISO_SR_UUID name-label=\"$ISO_NAME\" --minimal" | tr -d '[:space:]' || true)

if [[ -z "$ISO_VDI" ]]; then
    ISO_PATH_REMOTE="$ISO_SR_PATH/$ISO_NAME"
    echo "[INFO] Importing ISO into SR: $ISO_PATH_REMOTE"
    remote_quiet "xe vdi-import sr-uuid=$ISO_SR_UUID filename=\"$ISO_PATH_REMOTE\" || true"
    sleep 1
    ISO_VDI=$(remote "xe vdi-list sr-uuid=$ISO_SR_UUID name-label=\"$ISO_NAME\" --minimal" | tr -d '[:space:]' || true)
fi

# ----------------- Create VM from template -----------------
TEMPLATE_UUID=$(remote "xe template-list name-label=\"$TEMPLATE\" --minimal" | tr -d '[:space:]' || true)
if [[ -z "$TEMPLATE_UUID" ]]; then
    echo "[ERROR] Template not found: $TEMPLATE"
    exit 1
fi

VM_UUID=$(remote "xe vm-clone uuid=$TEMPLATE_UUID new-name-label=\"$VM_NAME\" --minimal" | tr -d '[:space:]' || true)
if [[ -z "$VM_UUID" ]]; then
    echo "[ERROR] Failed to clone VM from template $TEMPLATE"
    exit 1
fi

# Set CPU / RAM
remote_quiet "xe vm-param-set uuid=$VM_UUID VCPUs-max=$VCPUS VCPUs-at-startup=$VCPUS"
remote_quiet "xe vm-memory-limits-set uuid=$VM_UUID static-min=${RAM_MB}MiB static-max=${RAM_MB}MiB dynamic-min=${RAM_MB}MiB dynamic-max=${RAM_MB}MiB"

# Attach ISO if available
if [[ -n "$ISO_VDI" && "$ISO_VDI" != "null" ]]; then
    echo "[INFO] Attaching ISO VDI: $ISO_VDI"
    remote_quiet "xe vbd-create vm-uuid=$VM_UUID vdi-uuid=$ISO_VDI device=1 type=CD mode=RO || true"
fi

# ----------------- Start VM -----------------
remote_quiet "xe vm-start uuid=$VM_UUID || true"
echo "[INFO] VM started; waiting for IP..."

sleep 15

# ----------------- IP Detection Loop -----------------
VM_IP=""
attempt=0
max_attempts=60

while [[ -z "$VM_IP" && $attempt -lt $max_attempts ]]; do
    attempt=$((attempt+1))
    sleep 2

    # 1) xenstore read common key
    VM_IP=$(remote "xenstore-read vm-data/ip || true" 2>/dev/null || true)
    [[ -n "$VM_IP" ]] && break

    # 2) vif path
    VM_IP=$(remote "xenstore-read device/vif/0/ip || true" 2>/dev/null || true)
    [[ -n "$VM_IP" ]] && break

    # 3) domid lookup
    DOM_ID=$(remote "xe vm-param-get uuid=$VM_UUID param-name=dom-id || true" 2>/dev/null || true)
    if [[ -n "$DOM_ID" && "$DOM_ID" != "0" ]]; then
        VM_IP=$(remote "xenstore-read /local/domain/$DOM_ID/data/ip || true" 2>/dev/null || true)
        [[ -n "$VM_IP" ]] && break
    fi

    # 4) vm-data/networks (extract IPv4)
    NETWORKS=$(remote "xenstore-read vm-data/networks || true" 2>/dev/null || true)
    if [[ -n "$NETWORKS" ]]; then
        IP_CAND=$(echo "$NETWORKS" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n1 || true)
        if [[ -n "$IP_CAND" ]]; then VM_IP="$IP_CAND"; break; fi
    fi

    # 5) ARP + MAC-based fallback
    MAC=$(remote "xe vif-list vm-uuid=$VM_UUID params=MAC --minimal || true" 2>/dev/null || true)
    if [[ -n "$MAC" && "$MAC" != "null" ]]; then
        ARPIP=$(remote "arp -n | grep \"$MAC\" | awk '{print \$1}' || true")
        if [[ -n "$ARPIP" ]]; then VM_IP="$ARPIP"; break; fi
    fi
done

echo "--------------------------------------------"
echo "VM CREATED SUCCESSFULLY"
echo "Name: $VM_NAME"
echo "UUID: $VM_UUID"
echo "IP: $VM_IP"
echo "ISO VDI: $ISO_VDI"
echo "--------------------------------------------"
