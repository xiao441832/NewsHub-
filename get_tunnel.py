import subprocess, re, time

proc = subprocess.Popen(
    [r"D:\news-hub\cloudflared-real.exe", "tunnel", "--url", "http://localhost:8080", "--no-autoupdate", "--protocol", "http2"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)

with open(r"D:\news-hub\tunnel_url.txt", "w") as f:
    f.write("starting...\n")

for line in proc.stdout:
    m = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
    if m:
        with open(r"D:\news-hub\tunnel_url.txt", "w") as f:
            f.write(m.group(1))
        break

# Keep process alive
proc.wait()
