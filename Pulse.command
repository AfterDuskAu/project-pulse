#!/bin/zsh
# Double-click to refresh Project Pulse: it reads your projects (read-only) and opens the page.
cd "$(dirname "$0")" || exit 1
/usr/bin/env python3 pulse.py "$@"
result=$?
if [ $result -ne 0 ]; then
  echo ""
  echo "Pulse stopped with an error (above). Press Return to close this window."
  read -r _
fi
exit $result
