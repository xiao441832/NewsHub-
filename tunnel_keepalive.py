"""Tunnel keepalive - auto-reconnects SSH tunnel when it drops"""
import subprocess
import time
import os

TUNNEL_CMD = ["ssh", "-o", "StrictHostKeyChecking=no",
              "-o", "ServerAliveInterval=30",
              "-o", "ServerAliveCountMax=3",
              "-o", "ExitOnForwardFailure=yes",
              "-R", "80:localhost:8080", "serveo.net"]

def get_tunnel_url():
    """Start tunnel and return the public URL"""
    proc = subprocess.Popen(
        TUNNEL_CMD,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='ignore'
    )
    time.sleep(6)
    
    os.set_blocking(proc.stdout.fileno(), False)
    try:
        output = proc.stdout.read() or ""
        for line in output.split('\n'):
            if 'http' in line:
                # Extract URL
                import re
                match = re.search(r'https?://[^\s]+', line)
                if match:
                    return proc, match.group(0)
    except:
        pass
    return proc, None

def run_forever():
    """Keep tunnel alive, reconnect when it dies"""
    print("Tunnel keepalive started. Press Ctrl+C to stop.")
    
    while True:
        proc, url = get_tunnel_url()
        if url:
            print(f"✓ Tunnel active: {url}")
        else:
            print("✗ Failed to start tunnel, retrying in 10s...")
            time.sleep(10)
            continue
        
        # Monitor process
        while proc.poll() is None:
            time.sleep(5)
        
        print(f"✗ Tunnel died (exit {proc.returncode}), reconnecting...")
        time.sleep(3)

if __name__ == "__main__":
    run_forever()
