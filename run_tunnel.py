import subprocess, re, time, sys

proc = subprocess.Popen(
    [r"D:\news-hub\cloudflared-real.exe", "tunnel", "--url", "http://localhost:8080", "--no-autoupdate", "--protocol", "http2"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)

url = None
for line in proc.stdout:
    line = line.strip()
    if line:
        print(line, flush=True)
    m = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
    if m:
        url = m.group(1)
        print(f"\n>>> TUNNEL_URL={url}", flush=True)
        break

if url:
    # Keep running
    for line in proc.stdout:
        line = line.strip()
        if line:
            print(line, flush=True)
else:
    proc.kill()
    sys.exit(1)
