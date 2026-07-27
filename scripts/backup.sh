#!/bin/bash
# Automated backup script for LUMU Agent Framework
BACKUP_DIR="/opt/backups/lumu"
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/lumu_backup_$DATE.tar.gz"

# Backup application code
tar -czf $BACKUP_FILE \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='data/audio' \
  --exclude='*.pyc' \
  -C /opt agent-framework

# Backup PostgreSQL database
sudo -u postgres pg_dump lumu_agent > "$BACKUP_DIR/db_backup_$DATE.sql"
gzip "$BACKUP_DIR/db_backup_$DATE.sql"

# Keep last 30 days
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE"
echo "DB backup: $BACKUP_DIR/db_backup_$DATE.sql.gz"
