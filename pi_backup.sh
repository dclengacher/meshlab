#!/bin/bash
# Nightly off-Pi backup to Google Drive (gdrive:pi-backups)
# - Safe snapshots of every SQLite DB (no corruption while services write)
# - Code + docs: ~/mesh, ~/birdnet, ~/BirdNET-Pi (no .git)
# - System config files
# - BirdSongs recordings (copy only: never deletes from Drive)
# - Changed/deleted files kept 14 days under old/DATE

set -u
DEST="gdrive:pi-backups"
DAY=$(date +%F)
STAGE="$HOME/.backup_stage"
LOG="$HOME/mesh/logs/backup.log"
mkdir -p "$STAGE/db" "$STAGE/sys" "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "===== $(date) start ====="

# 1. DB snapshots
rm -f "$STAGE"/db/*.db
for f in $(find "$HOME/mesh" "$HOME/birdnet" -name "*.db" -not -path "*/.git/*") "$HOME/BirdNET-Pi/scripts/birds.db"; do
  [ -f "$f" ] || continue
  name=$(echo "${f#$HOME/}" | tr '/' '_')
  python3 -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$f" "$STAGE/db/$name" && echo "db ok: $f"
done

# 2. System config
cp -f /etc/birdnet/birdnet.conf /etc/modprobe.d/usb-audio-order.conf /etc/udev/rules.d/90-digirig-no-pulse.rules "$STAGE/sys/" 2>/dev/null
crontab -l > "$STAGE/sys/crontab.txt" 2>/dev/null
cp -f /etc/systemd/system/*.service "$STAGE/sys/" 2>/dev/null

# 3. Upload
OPTS="--transfers 4 --exclude .git/** --exclude __pycache__/** --exclude *.db --exclude .venv/**"
rclone sync "$STAGE/db"           "$DEST/db"         --backup-dir "$DEST/old/$DAY/db"
rclone sync "$STAGE/sys"          "$DEST/sys"        --backup-dir "$DEST/old/$DAY/sys"
rclone sync "$HOME/mesh"          "$DEST/mesh"       $OPTS --backup-dir "$DEST/old/$DAY/mesh"
rclone sync "$HOME/birdnet"       "$DEST/birdnet"    $OPTS --backup-dir "$DEST/old/$DAY/birdnet"
rclone sync "$HOME/BirdNET-Pi"    "$DEST/BirdNET-Pi" $OPTS --backup-dir "$DEST/old/$DAY/BirdNET-Pi"
rclone copy "$HOME/BirdSongs"     "$DEST/BirdSongs"  --transfers 4

# 4. Prune old versions > 14 days
rclone delete "$DEST/old" --min-age 14d
rclone rmdirs "$DEST/old" --leave-root

echo "===== $(date) done ====="
