#!/usr/bin/env python3
"""
Supermicro IPMI Fan Control — Stop the churning.
Works on Windows, Mac, Linux.
Uses ipmitool via subprocess (auto-downloaded on Windows, pre-installed on Linux/Mac).

Usage:
  1. Edit the CONFIG section below with your BMC details
  2. Run: python ipmi-fan-control.py
  3. Pick a preset
  4. Done — fans stay fixed until you change them

Requirements: Python 3.6+ (ipmitool auto-downloaded on Windows)
"""

# ============================================================
# CONFIG — Edit these three values
# ============================================================
BMC_IP       = "192.168.1.100"   # Your BMC/IPMI IP address
BMC_USER     = "ADMIN"           # Your IPMI username
BMC_PASSWORD = "your-password"   # Your IPMI password
# ============================================================


import os
import sys
import platform
import subprocess
import time
import urllib.request

PRESETS = {
    "q": ("Quiet",   "01", 40, 30),
    "n": ("Normal",  "01", 50, 40),
    "c": ("Cool",    "01", 70, 60),
    "f": ("Full",    "02", None, None),
    "r": ("Reset",   "01", None, None),
}

# Download ipmitool.exe from our GitHub release (cross-compiled from source)
IPMITOOL_EXE_URL = "https://github.com/brooksaw/ipmi-dashboard/releases/latest/download/ipmitool.exe"


def find_ipmitool():
    """Find or install ipmitool."""
    system = platform.system()

    if system == "Windows":
        exe = "ipmitool.exe"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, "ipmitool.exe"),
            exe,  # check PATH
        ]
        for c in candidates:
            try:
                result = subprocess.run([c, "-V"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    print(f"  Found ipmitool: {c}")
                    return c
            except:
                continue

        # Not found — offer to download
        print("  ipmitool not found on your system.")
        print()
        download = input("  Download ipmitool.exe? [Y/n]: ").strip().lower()
        if download in ("", "y", "yes"):
            if download_ipmitool_windows():
                return os.path.join(script_dir, "ipmitool.exe")

        print()
        print("  MANUAL INSTALL:")
        print("    1. Go to: https://github.com/brooksaw/ipmi-dashboard/releases")
        print("    2. Download ipmitool.exe")
        print(f"    3. Place it in: {script_dir}")
        print()
        print("  Or install via Chocolatey:  choco install ipmitool")
        print("  Or install via WSL:         sudo apt install ipmitool")
        sys.exit(1)

    else:
        # Linux/Mac — check then install
        try:
            result = subprocess.run(["ipmitool", "-V"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return "ipmitool"
        except FileNotFoundError:
            pass

        print("  ipmitool not found. Installing...")
        if system == "Darwin":
            subprocess.run(["brew", "install", "ipmitool"], check=False)
        else:
            subprocess.run(["sudo", "apt-get", "install", "-y", "ipmitool"], check=False)

        try:
            subprocess.run(["ipmitool", "-V"], capture_output=True, timeout=5)
            return "ipmitool"
        except:
            print("  ERROR: Could not install ipmitool. Install it manually.")
            sys.exit(1)


def download_ipmitool_windows():
    """Download ipmitool.exe from GitHub releases."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(script_dir, "ipmitool.exe")

    print("  Downloading ipmitool.exe...")
    try:
        urllib.request.urlretrieve(IPMITOOL_EXE_URL, dst)
        # Verify it actually downloaded (not a 404 HTML page)
        with open(dst, "rb") as f:
            magic = f.read(2)
        if magic[:2] == b"MZ":  # Valid PE/EXE
            print(f"  Installed ipmitool.exe to {dst}")
            return True
        else:
            # Got an HTML error page instead of a binary
            os.unlink(dst)
            print("  Download failed: binary not available yet.")
            print("  The GitHub Actions build needs to run first.")
            return False
    except Exception as e:
        print(f"  Download failed: {e}")
        if os.path.exists(dst):
            os.unlink(dst)
        return False


def ipmi_raw(ipmitool, *args):
    """Run ipmitool raw command and return stdout."""
    cmd = [
        ipmitool, "-I", "lanplus",
        "-H", BMC_IP, "-U", BMC_USER, "-P", BMC_PASSWORD,
        "-N", "5000", "-R", "1"
    ] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except:
        return ""


def ipmi_cmd(ipmitool, *args):
    """Run ipmitool command and return stdout."""
    cmd = [
        ipmitool, "-I", "lanplus",
        "-H", BMC_IP, "-U", BMC_USER, "-P", BMC_PASSWORD,
        "-N", "5000", "-R", "1"
    ] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return ""


def get_fan_mode(ipmitool):
    """Read current fan mode."""
    raw = ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x00").strip().replace(" ", "")
    names = {"00": "Heavy Duty", "01": "Standard", "02": "Full (100%)", "04": "Optimal", "10": "PUE2"}
    if raw:
        return f"{raw} ({names.get(raw, 'Unknown')})"
    return "Unknown"


def get_duty(ipmitool, zone):
    """Read current duty cycle for a zone (0 or 1)."""
    raw = ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x00", f"0x{zone:02x}")
    raw = raw.strip().replace(" ", "")
    if raw:
        try:
            return int(raw, 16)
        except:
            pass
    return None


def apply_fan_control(ipmitool, mode_hex, duty_z0=None, duty_z1=None):
    """
    Apply fan control with proper Supermicro BMC timing.
    Proven sequence:
      1. Force FULL mode (breaks out of any active preset)
      2. Sleep 2s (BMC timing requirement)
      3. Set target mode
      4. Sleep 2s
      5. Set duty cycles
    """
    mode_names = {"00": "Heavy Duty", "01": "Standard", "02": "Full", "04": "Optimal", "10": "PUE2"}
    mode_name = mode_names.get(mode_hex, mode_hex)

    print("  Transitioning BMC...")
    ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x01", "0x02")  # Force FULL
    print("  [1] Forced FULL mode")
    time.sleep(2)

    ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x01", mode_hex)  # Target mode
    print(f"  [2] Mode set to {mode_name}")
    time.sleep(2)

    if duty_z0 is not None:
        hex_z0 = f"0x{duty_z0:02x}"
        ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x01", "0x00", hex_z0)
        print(f"  [3] Zone 0 duty set to {duty_z0}%")
        time.sleep(1)

    if duty_z1 is not None:
        hex_z1 = f"0x{duty_z1:02x}"
        ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x01", "0x01", hex_z1)
        print(f"  [4] Zone 1 duty set to {duty_z1}%")
        time.sleep(1)

    # Verify
    z0v = get_duty(ipmitool, 0)
    z1v = get_duty(ipmitool, 1)
    print(f"  [5] Verified: Z0={z0v}% Z1={z1v}%")
    print("  Done!")


def show_status(ipmitool):
    """Show current sensor readings using ipmitool SDR."""

    print("\n" + "=" * 55)
    print(f"  BMC: {BMC_IP}")

    # Temps
    print("\n  TEMPERATURES:")
    output = ipmi_cmd(ipmitool, "sdr", "type", "temperature")
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) >= 5:
            name = parts[0].strip()
            status = parts[2].strip()
            value = parts[4].strip()
            if status.lower() == "ns" or "No Reading" in value:
                print(f"    [---] {name:<22s} N/A")
            else:
                try:
                    temp = int(value.split()[0])
                    icon = "[!!!]" if temp >= 85 else "[!! ]" if temp >= 70 else "[OK ]"
                    print(f"    {icon} {name:<22s} {temp}\u00b0C")
                except:
                    print(f"    [---] {name:<22s} {value}")

    # Fans
    print("\n  FANS:")
    output = ipmi_cmd(ipmitool, "sdr", "type", "fan")
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) >= 5:
            name = parts[0].strip()
            status = parts[2].strip()
            value = parts[4].strip()
            if status.lower() == "ns" or "No Reading" in value:
                print(f"    [---] {name:<22s} NOT PRESENT")
            elif "RPM" in value:
                try:
                    rpm = int(value.split()[0])
                    icon = "[!!!]" if rpm < 200 else "[!! ]" if rpm < 500 else "[OK ]"
                    print(f"    {icon} {name:<22s} {rpm} RPM")
                except:
                    print(f"    [---] {name:<22s} {value}")

    # Fan control state
    mode = get_fan_mode(ipmitool)
    z0 = get_duty(ipmitool, 0)
    z1 = get_duty(ipmitool, 1)
    print(f"\n  FAN CONTROL:")
    print(f"    Mode:     {mode}")
    print(f"    Zone 0:   {z0}%" if z0 is not None else "    Zone 0:   N/A")
    print(f"    Zone 1:   {z1}%" if z1 is not None else "    Zone 1:   N/A")
    print("=" * 55)


def main():
    print()
    print("  Supermicro IPMI Fan Control")
    print("  Stops fan churning on X9/X10/X11/X12 boards")
    print()

    # Check config
    if BMC_PASSWORD == "your-password":
        print("  ERROR: Edit the CONFIG section at the top of this script")
        print("         Set BMC_IP, BMC_USER, and BMC_PASSWORD")
        sys.exit(1)

    # Find/setup ipmitool
    print("  Setting up ipmitool...")
    ipmitool = find_ipmitool()

    # Test connection
    print(f"  Connecting to BMC at {BMC_IP}...")
    test = ipmi_cmd(ipmitool, "mc", "info")
    if not test:
        print(f"  ERROR: Cannot reach BMC at {BMC_IP}")
        print(f"  Check: IP correct? Password correct? IPMI enabled in BIOS?")
        sys.exit(1)
    print("  Connected!\n")

    while True:
        show_status(ipmitool)

        print("\n  QUICK PRESETS:")
        print("    [q] Quiet    — Standard, 40%/30% duty (stops churning)")
        print("    [n] Normal   — Standard, 50%/40% duty (balanced)")
        print("    [c] Cool     — Standard, 70%/60% duty (more airflow)")
        print("    [f] Full     — 100% all fans (max cooling)")
        print("    [r] Reset    — Standard mode, BMC auto-manages")
        print()
        print("    [m] Manual   — pick mode + duty yourself")
        print("    [s] Status   — refresh readings")
        print("    [x] Exit")

        choice = input("\n  Choice: ").strip().lower()

        if choice == "x":
            print()
            break
        elif choice == "s":
            continue
        elif choice in PRESETS:
            name, mode, z0, z1 = PRESETS[choice]
            print(f"\n  Applying preset: {name}...")
            apply_fan_control(ipmitool, mode, z0, z1)
            input("\n  Press Enter to see results...")
        elif choice == "m":
            print("\n  Select mode:")
            print("    [1] Heavy Duty  — \u26a0\ufe0f  causes churning on boards with empty fan slots")
            print("    [2] Standard    — \u2705 recommended, BMC auto + duty guidance")
            print("    [3] Full (100%) — max speed")
            print("    [4] Optimal     — BMC balanced")
            print("    [5] PUE2        — power save")
            mode_choice = input("  Mode: ").strip()
            modes = {"1": "00", "2": "01", "3": "02", "4": "04", "5": "10"}
            if mode_choice not in modes:
                print("  Invalid choice")
                continue
            mode_hex = modes[mode_choice]
            z0, z1 = None, None
            # Both Heavy Duty and Standard need duty cycles
            if mode_hex in ("00", "01"):
                try:
                    z0 = int(input("  Zone 0 duty % (10-100, recommended 50): ").strip())
                    z1 = int(input("  Zone 1 duty % (10-100, recommended 40): ").strip())
                    z0 = max(10, min(100, z0))
                    z1 = max(10, min(100, z1))
                except ValueError:
                    print("  Invalid value, using defaults (50/40)")
                    z0, z1 = 50, 40
            print("\n  Applying...")
            apply_fan_control(ipmitool, mode_hex, z0, z1)
            input("\n  Press Enter to see results...")
        else:
            print("  Invalid choice")


if __name__ == "__main__":
    main()
