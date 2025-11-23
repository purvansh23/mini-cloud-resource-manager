#!/bin/bash
# idempotent-attach-pbd.sh
# Usage: idempotent-attach-pbd.sh <SR_UUID> <HOST_UUID> <NFS_SERVER> <NFS_EXPORT>
SR_UUID="$1"
HOST_UUID="$2"
NFS_SERVER="$3"
NFS_EXPORT="$4"

if [ -z "$SR_UUID" ] || [ -z "$HOST_UUID" ] || [ -z "$NFS_SERVER" ] || [ -z "$NFS_EXPORT" ]; then
  echo "Usage: $0 SR_UUID HOST_UUID NFS_SERVER NFS_EXPORT" >&2
  exit 2
fi

# Look for existing PBD on the SR for the host
EXISTING=$(xe pbd-list sr-uuid=${SR_UUID} params=uuid,host-uuid | awk -v h="$HOST_UUID" '
  BEGIN{RS="\n\n";FS="\n"}
  { for(i=1;i<=NF;i++){ if($i ~ /host-uuid/ && $i ~ h){ for(j=1;j<=NF;j++) if($j ~ /uuid/){ print $j; exit } } } }' | awk -F': ' '{print $2}')

if [ -n "$EXISTING" ]; then
  echo "Found existing PBD: $EXISTING"
  xe pbd-plug uuid=${EXISTING} || true
  exit 0
fi

# Create
NEW=$(xe pbd-create sr-uuid=${SR_UUID} host-uuid=${HOST_UUID} device-config:server=${NFS_SERVER} device-config:serverpath=${NFS_EXPORT} 2>&1)
if echo "$NEW" | grep -q "uuid"; then
  PBD_UUID=$(echo "$NEW" | awk -F': ' '/uuid/ {print $2}')
  echo "Created PBD $PBD_UUID"
  xe pbd-plug uuid=${PBD_UUID}
  exit 0
else
  echo "Failed to create PBD: $NEW" >&2
  exit 1
fi
