#!/bin/bash
cd "$(dirname "$0")"
exec ./cloudflared-real.exe tunnel --url http://localhost:8080 --no-autoupdate --protocol http2 2>&1
