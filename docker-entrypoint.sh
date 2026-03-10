#!/bin/sh
# Sync container time with NTP so Binance API signed requests don't get -1021
if command -v ntpdate >/dev/null 2>&1; then
  ntpdate -u pool.ntp.org 2>/dev/null || true
fi
export PATH="/usr/local/bin:/usr/bin:/bin"
exec gosu app "$@"
