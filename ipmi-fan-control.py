#!/usr/bin/env python3
"""
Supermicro IPMI Fan Control — Stop the churning.
Pure Python, works on Windows/Mac/Linux.

Usage:
  1. Edit the CONFIG section below with your BMC details
  2. Run: python ipmi-fan-control.py
  3. Pick a preset or set custom values
  4. Done — fans stay fixed until you change them again

Requires: pip install pyghmi (auto-installed if missing)
"""

# ============================================================
# CONFIG — Edit these three values
# ============================================================
BMC_IP       = "192.168.1.100"   # Your BMC/IPMI IP address
BMC_USER     = "ADMIN"           # Your IPMI username
BMC_PASSWORD = "your-password"   # Your IPMI password
# ============================================================


import sys
import subprocess
import time

# Auto-install pyghmi if missing
try:
    from pyghmi.ipmi import command
except ImportError:
    print("Installing pyghmi (pure Python IPMI library)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyghmi"])
    from pyghmi.ipmi import command

# Supermicro fan mode codes
FAN_MODES = {
    "1": ("00", "Heavy Duty",  "Low RPM, quietest, fixed duty cycle"),
    "2": ("01", "Standard",    "BMC auto-control (factory default)"),
    "3": ("02", "Full (100%)", "All fans max speed"),
    "4": ("04", "Optimal",     "BMC balanced mode"),
    "5": ("10", "PUE2",        "Power save mode"),
}

PRESETS = {
    "q": ("Quiet",   "00", 30, 20),
    "n": ("Normal",  "00", 50, 40),
    "c": ("Cool",    "00", 70, 60),
    "f": ("Full",    "02", None, None),
    "r": ("Reset",   "01", None, None),
}


def connect():
    """Connect to BMC and return IPMI command object."""
    print(f"Connecting to BMC at {BMC_IP}...")
    try:
        ic = command.Command(bmc=BMC_IP, userid=BMC_USER, password=BMC_PASSWORD)
        return ic
    except Exception as e:
        print(f"\nERROR: Could not connect to BMC at {BMC_IP}")
        print(f"  Reason: {e}")
        print(f"\nCheck:")
        print(f"  - BMC IP is correct and reachable (try: ping {BMC_IP})")
        print(f"  - Username and password are correct")
        print(f"  - IPMI is enabled in BIOS")
        sys.exit(1)


def get_fan_mode(ic):
    """Read current fan mode."""
    try:
        r = ic.raw_command(netfn=0x30, command=0x45, data=[0x00])
        if r["code"] == 0:
            code = r["data"][0]
            names = {"0": "Heavy Duty", "1": "Standard", "2": "Full (100%)", "4": "Optimal", "16": "PUE2"}
            return f"{code} ({names.get(str(code), 'Unknown')})"
    except:
        pass
    return "Unknown"


def get_duty(ic, zone):
    """Read current duty cycle for a zone (0 or 1)."""
    try:
        r = ic.raw_command(netfn=0x30, command=0x70, data=[0x66, 0x00, zone])
        if r["code"] == 0:
            return r["data"][0]
    except:
        pass
    return None


def set_fan_mode(ic, mode_hex):
    """Set fan mode via Supermicro OEM raw command."""
    ic.raw_command(netfn=0x30, command=0x45, data=[0x01, mode_hex])


def set_duty(ic, zone, percent):
    """Set fan duty cycle for a zone."""
    ic.raw_command(netfn=0x30, command=0x70, data=[0x66, 0x01, zone, percent])


def apply_fan_control(ic, mode_hex, duty_z0=None, duty_z1=None):
    """
    Apply fan control with proper Supermicro BMC timing.
    Step 1: Force FULL mode (breaks out of any active preset)
    Step 2: Sleep 2s (BMC needs this)
    Step 3: Set target mode
    Step 4: Sleep 2s
    Step 5: Set duty cycles
    """
    mode_names = {"00": "Heavy Duty", "01": "Standard", "02": "Full", "04": "Optimal", "10": "PUE2"}
    mode_name = mode_names.get(mode_hex, mode_hex)

    print("  Transitioning BMC...")
    set_fan_mode(ic, 0x02)     # Force FULL
    time.sleep(2)
    set_fan_mode(ic, int(mode_hex, 16))  # Target mode
    print(f"  Mode set to {mode_name}")

    if duty_z0 is not None:
        time.sleep(2)
        set_duty(ic, 0, duty_z0)
        print(f"  Zone 0 duty set to {duty_z0}%")

    if duty_z1 is not None:
        if duty_z0 is None:
            time.sleep(2)
        set_duty(ic, 1, duty_z1)
        print(f"  Zone 1 duty set to {duty_z1}%")

    print("  Done!")


def show_status(ic):
    """Show current sensor readings."""
    print("\n" + "=" * 55)
    print(f"  BMC: {BMC_IP}")

    # Temps
    print("\n  TEMPERATURES:")
    sensors = list(ic.get_sensor_data())
    for s in sensors:
        if s.type == "Temperature" and s.value is not None:
            label = s.name
            temp = s.value
            if temp >= 85:
                icon = "[!!!]"
            elif temp >= 70:
                icon = "[!! ]"
            else:
                icon = "[OK ]"
            print(f"    {icon} {label:<22s} {temp:>5.1f}{s.units}")

    # Fans
    print("\n  FANS:")
    for s in sensors:
        if s.type == "Fan" and s.value is not None:
            rpm = s.value
            if rpm < 200:
                icon = "[!!!]"
            elif rpm < 500:
                icon = "[!! ]"
            else:
                icon = "[OK ]"
            print(f"    {icon} {s.name:<22s} {rpm:>7.0f} {s.units}")

    # Fan control
    mode = get_fan_mode(ic)
    z0 = get_duty(ic, 0)
    z1 = get_duty(ic, 1)
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

    ic = connect()
    print("  Connected!\n")

    while True:
        show_status(ic)

        print("\n  QUICK PRESETS:")
        print("    [q] Quiet    — Heavy Duty, 30%/20% (near silent)")
        print("    [n] Normal   — Heavy Duty, 50%/40% (balanced)")
        print("    [c] Cool     — Heavy Duty, 70%/60% (more airflow)")
        print("    [f] Full     — 100% all fans (max cooling)")
        print("    [r] Reset    — Standard mode (BMC auto, factory default)")
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
            apply_fan_control(ic, mode, z0, z1)
            input("\n  Press Enter to see results...")

        elif choice == "m":
            print("\n  Select mode:")
            for k, (code, name, desc) in FAN_MODES.items():
                print(f"    [{k}] {name:<16s} — {desc}")
            mode_choice = input("  Mode: ").strip()
            if mode_choice not in FAN_MODES:
                print("  Invalid choice")
                continue

            mode_hex = FAN_MODES[mode_choice][0]

            # Duty cycle only makes sense for Heavy Duty mode
            z0, z1 = None, None
            if mode_hex == "00":
                try:
                    z0 = int(input("  Zone 0 duty % (10-100): ").strip())
                    z1 = int(input("  Zone 1 duty % (10-100): ").strip())
                    z0 = max(10, min(100, z0))
                    z1 = max(10, min(100, z1))
                except ValueError:
                    print("  Invalid value, using defaults (50/40)")
                    z0, z1 = 50, 40

            print("\n  Applying...")
            apply_fan_control(ic, mode_hex, z0, z1)
            input("\n  Press Enter to see results...")

        else:
            print("  Invalid choice")

    print("  Bye!")
    ic.ipmi_session.logout()


if __name__ == "__main__":
    main()
