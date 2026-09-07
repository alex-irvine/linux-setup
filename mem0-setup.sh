#!/usr/bin/env bash
set -euo pipefail

# Retained as an inert compatibility entry point. It deliberately leaves hosted
# credentials, records, plugin data, and snapshots untouched for the deferred
# post-reset export.
printf '[mem0-setup] inactive; hosted Mem0 data and credentials were preserved offline\n'
