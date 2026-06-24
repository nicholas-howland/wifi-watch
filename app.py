#!/usr/bin/env python3

import os
import time
import sqlite3
import socket
import ipaddress
import subprocess
import platform
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread, Lock

import requests
from flask import Flask, jsonify, render_template


# ----------------------------
# Configuration
# ----------------------------

NETWORK_CIDR = os.getenv("WIFI_WATCH_NETWORK", "192.168.1.0/24")
SCAN_INTERVAL_SECONDS = int(os.getenv("WIFI_WATCH_INTERVAL", "60"))
PING_TIMEOUT_SECONDS = int(os.getenv("WIFI_WATCH_PING_TIMEOUT", "1"))
MAX_WORKERS = int(os.getenv("WIFI_WATCH_WORKERS", "64"))

DB_PATH = os.getenv("WIFI_WATCH_DB", "wifi_watch.db")

# Bind to 127.0.0.1 by default for safety.
# Use 0.0.0.0 only if you want other LAN devices to view the dashboard.
WEB_HOST = os.getenv("WIFI_WATCH_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WIFI_WATCH_WEB_PORT", "5000"))


app = Flask(__name__)
db_lock = Lock()


# ----------------------------
# Database
# ----------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT UNIQUE NOT NULL,
                hostname TEXT,
                mac TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS join_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                hostname TEXT,
                mac TEXT,
                seen_at TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()


# ----------------------------
# Utility functions
# ----------------------------

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def ping_host(ip):
    """
    Returns True if the host responds to ICMP ping.
    Works on Linux/macOS/Windows with minor flag differences.
    """
    system = platform.system().lower()

    if "windows" in system:
        cmd = [
            "ping",
            "-n", "1",
            "-w", str(PING_TIMEOUT_SECONDS * 1000),
            str(ip)
        ]
    else:
        cmd = [
            "ping",
            "-c", "1",
            "-W", str(PING_TIMEOUT_SECONDS),
            str(ip)
        ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PING_TIMEOUT_SECONDS + 2
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def resolve_hostname(ip):
    try:
        hostname, _, _ = socket.gethostbyaddr(str(ip))
        return hostname
    except Exception:
        return None


def get_mac_from_arp(ip):
    """
    Best-effort MAC lookup after pinging.
    This depends on the local ARP/neigh table and may not always work.
    """
    ip = str(ip)
    system = platform.system().lower()

    try:
        if "linux" in system:
            result = subprocess.run(
                ["ip", "neigh", "show", ip],
                capture_output=True,
                text=True,
                timeout=2
            )
            output = result.stdout.strip()

            # Example:
            # 192.168.1.20 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
            parts = output.split()
            if "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    return parts[idx + 1]

        else:
            result = subprocess.run(
                ["arp", "-a", ip],
                capture_output=True,
                text=True,
                timeout=2
            )
            output = result.stdout.strip()

            # Very simple MAC-ish extraction
            for token in output.replace("-", ":").split():
                if token.count(":") == 5:
                    return token.lower()

    except Exception:
        pass

    return None




def record_scan_results(active_hosts):
    """
    active_hosts format:
    {
        "192.168.1.10": {
            "hostname": "example.local",
            "mac": "aa:bb:cc:dd:ee:ff"
        }
    }
    """
    now = utc_now_iso()

    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        # Mark everything inactive first.
        cur.execute("UPDATE devices SET active = 0")

        for ip, data in active_hosts.items():
            hostname = data.get("hostname")
            mac = data.get("mac")

            cur.execute("SELECT id FROM devices WHERE ip = ?", (ip,))
            existing = cur.fetchone()

            if existing is None:
                cur.execute("""
                    INSERT INTO devices (
                        ip, hostname, mac, first_seen, last_seen, active
                    )
                    VALUES (?, ?, ?, ?, ?, 1)
                """, (ip, hostname, mac, now, now))

                cur.execute("""
                    INSERT INTO join_events (
                        ip, hostname, mac, seen_at
                    )
                    VALUES (?, ?, ?, ?)
                """, (ip, hostname, mac, now))

                print(f"[+] New device detected: {ip} {hostname or ''} {mac or ''}")

            else:
                cur.execute("""
                    UPDATE devices
                    SET hostname = COALESCE(?, hostname),
                        mac = COALESCE(?, mac),
                        last_seen = ?,
                        active = 1
                    WHERE ip = ?
                """, (hostname, mac, now, ip))

        conn.commit()
        conn.close()


# ----------------------------
# Scanner
# ----------------------------

def scan_network_once():
    print(f"[*] Scanning {NETWORK_CIDR}")

    network = ipaddress.ip_network(NETWORK_CIDR, strict=False)
    hosts = list(network.hosts())
    active_hosts = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(ping_host, ip): ip
            for ip in hosts
        }

        for future in as_completed(futures):
            ip = futures[future]

            try:
                is_alive = future.result()
            except Exception:
                is_alive = False

            if is_alive:
                ip_str = str(ip)
                hostname = resolve_hostname(ip_str)
                mac = get_mac_from_arp(ip_str)

                active_hosts[ip_str] = {
                    "hostname": hostname,
                    "mac": mac
                }

    record_scan_results(active_hosts)

    print(f"[*] Scan complete. Active hosts: {len(active_hosts)}")


def scanner_loop():
    while True:
        try:
            scan_network_once()
        except Exception as e:
            print(f"[!] Scanner error: {e}")

        time.sleep(SCAN_INTERVAL_SECONDS)


# ----------------------------
# Web routes
# ----------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/chart.js")
def chartjs():
    return render_template("chart.js")


@app.route("/api/devices")
def api_devices():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT ip, hostname, mac, first_seen, last_seen, active
            FROM devices
            ORDER BY first_seen DESC
        """)

        rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    return jsonify(rows)


@app.route("/api/events")
def api_events():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT ip, hostname, mac, seen_at
            FROM join_events
            ORDER BY seen_at ASC
        """)

        rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    return jsonify(rows)


@app.route("/api/summary")
def api_summary():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS total FROM devices")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS active FROM devices WHERE active = 1")
        active = cur.fetchone()["active"]

        cur.execute("SELECT COUNT(*) AS inactive FROM devices WHERE active = 0")
        inactive = cur.fetchone()["inactive"]

        conn.close()

    return jsonify({
        "total": total,
        "active": active,
        "inactive": inactive,
        "network": NETWORK_CIDR,
        "scan_interval_seconds": SCAN_INTERVAL_SECONDS
    })


# ----------------------------
# Main
# ----------------------------

if __name__ == "__main__":
    init_db()

    scanner_thread = Thread(target=scanner_loop, daemon=True)
    scanner_thread.start()

    print(f"[*] Dashboard running at http://{WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT)
