#!/bin/bash
# Fake CLI that routes subcommands to demo output
DIR="$(cd "$(dirname "$0")" && pwd)"
case "$1" in
  search)  bash "$DIR/search.sh" ;;
  enrich)  bash "$DIR/enrich.sh" ;;
  agent)   bash "$DIR/agent.sh" ;;
  *)       echo "unknown command: $1" ;;
esac
