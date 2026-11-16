#!/bin/sh
# Start-up for the container: make sure the data folders exist and belong to the app's user, then run the app as that user.
set -e
mkdir -p /data/resume_files /data/logs
chown -R appuser:appuser /data
exec runuser -u appuser -- "$@"
