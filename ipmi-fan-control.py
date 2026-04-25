     1|#!/usr/bin/env python3
     2|"""
     3|Supermicro IPMI Fan Control — Stop the churning.
     4|Pure Python, works on Windows/Mac/Linux.
     5|
     6|Usage:
     7|  1. Edit the CONFIG section below with your BMC details
     8|  2. Run: python ipmi-fan-control.py
     9|  3. Pick a preset or set custom values
    10|  4. Done — fans stay fixed until you change them again
    11|
    12|Requires: pip install pyghmi (auto-installed if missing)
    13|"""
    14|
    15|# ============================================================
    16|# CONFIG — Edit these three values
    17|# ============================================================
    18|BMC_IP       = "192.168.1.100"   # Your BMC/IPMI IP address
    19|BMC_USER     = "ADMIN"           # Your IPMI username
    20|BMC_PASSWORD="***"   # Your IPMI password
    21|# ============================================================
    22|
    23|
    24|import sys
    25|import subprocess
    26|import time
    27|
    28|# Auto-install pyghmi if missing
    29|try:
    30|    from pyghmi.ipmi import command
    31|except ImportError:
    32|    print("Installing pyghmi (pure Python IPMI library)...")
    33|    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyghmi"])
    34|    from pyghmi.ipmi import command
    35|
    36|# Supermicro fan mode codes
    37|FAN_MODES = {
    38|    "1": ("00", "Heavy Duty",  "Low RPM, quietest, fixed duty cycle"),
    39|    "2": ("01", "Standard",    "BMC auto-control (factory default)"),
    40|    "3": ("02", "Full (100%)", "All fans max speed"),
    41|    "4": ("04", "Optimal",     "BMC balanced mode"),
    42|    "5": ("10", "PUE2",        "Power save mode"),
    43|}
    44|
    45|PRESETS = {
    46|    "q": ("Quiet",   "00", 30, 20),
    47|    "n": ("Normal",  "00", 50, 40),
    48|    "c": ("Cool",    "00", 70, 60),
    49|    "f": ("Full",    "02", None, None),
    50|    "r": ("Reset",   "01", None, None),
    51|}
    52|
    53|
    54|def connect():
    55|    """Connect to BMC and return IPMI command object."""
    56|    print(f"Connecting to BMC at {BMC_IP}...")
    57|    try:
    58|        ic = command.Command(bmc=BMC_IP, userid=BMC_USER, password=BMC_PASSWORD)
    59|        return ic
    60|    except Exception as e:
    61|        print(f"\nERROR: Could not connect to BMC at {BMC_IP}")
    62|        print(f"  Reason: {e}")
    63|        print(f"\nCheck:")
    64|        print(f"  - BMC IP is correct and reachable (try: ping {BMC_IP})")
    65|        print(f"  - Username and password are correct")
    66|        print(f"  - IPMI is enabled in BIOS")
    67|        sys.exit(1)
    68|
    69|
    70|def get_fan_mode(ic):
    71|    """Read current fan mode."""
    72|    try:
    73|        r = ic.raw_command(netfn=0x30, command=0x45, data=[0x00])
    74|        if r["code"] == 0:
    75|            code = r["data"][0]
    76|            names = {"0": "Heavy Duty", "1": "Standard", "2": "Full (100%)", "4": "Optimal", "16": "PUE2"}
    77|            return f"{code} ({names.get(str(code), 'Unknown')})"
    78|    except:
    79|        pass
    80|    return "Unknown"
    81|
    82|
    83|def get_duty(ic, zone):
    84|    """Read current duty cycle for a zone (0 or 1)."""
    85|    try:
    86|        r = ic.raw_command(netfn=0x30, command=0x70, data=[0x66, 0x00, zone])
    87|        if r["code"] == 0:
    88|            return r["data"][0]
    89|    except:
    90|        pass
    91|    return None
    92|
    93|
    94|def set_fan_mode(ic, mode_hex):
    95|    """Set fan mode via Supermicro OEM raw command."""
    96|    ic.raw_command(netfn=0x30, command=0x45, data=[0x01, mode_hex])
    97|
    98|
    99|def set_duty(ic, zone, percent):
   100|    """Set fan duty cycle for a zone."""
   101|    ic.raw_command(netfn=0x30, command=0x70, data=[0x66, 0x01, zone, percent])
   102|
   103|
   104|def apply_fan_control(ic, mode_hex, duty_z0=None, duty_z1=None):
   105|    """
   106|    Apply fan control with proper Supermicro BMC timing.
   107|    Step 1: Force FULL mode (breaks out of any active preset)
   108|    Step 2: Sleep 2s (BMC needs this)
   109|    Step 3: Set target mode
   110|    Step 4: Sleep 2s
   111|    Step 5: Set duty cycles
   112|    """
   113|    mode_names = {"00": "Heavy Duty", "01": "Standard", "02": "Full", "04": "Optimal", "10": "PUE2"}
   114|    mode_name = mode_names.get(mode_hex, mode_hex)
   115|
   116|    print("  Transitioning BMC...")
   117|    set_fan_mode(ic, 0x02)     # Force FULL
   118|    time.sleep(2)
   119|    set_fan_mode(ic, int(mode_hex, 16))  # Target mode
   120|    print(f"  Mode set to {mode_name}")
   121|
   122|    if duty_z0 is not None:
   123|        time.sleep(2)
   124|        set_duty(ic, 0, duty_z0)
   125|        print(f"  Zone 0 duty set to {duty_z0}%")
   126|
   127|    if duty_z1 is not None:
   128|        if duty_z0 is None:
   129|            time.sleep(2)
   130|        set_duty(ic, 1, duty_z1)
   131|        print(f"  Zone 1 duty set to {duty_z1}%")
   132|
   133|    print("  Done!")

    # Verify it stuck
    time.sleep(1)
    z0v = get_duty(ic, 0)
    z1v = get_duty(ic, 1)
    if duty_z0 is not None and z0v is not None and abs(z0v - duty_z0) > 5:
        print(f"  WARNING: Zone 0 duty read back as {z0v}% (set {duty_z0}%)")
        print("           BMC may have rounded the value — this is normal")
    if duty_z1 is not None and z1v is not None and abs(z1v - duty_z1) > 5:
        print(f"  WARNING: Zone 1 duty read back as {z1v}% (set {duty_z1}%)")
        print("           BMC may have rounded the value — this is normal")
   134|
   135|
   136|def show_status(ic):
   137|    """Show current sensor readings."""
   138|    print("\n" + "=" * 55)
   139|    print(f"  BMC: {BMC_IP}")
   140|
   141|    # Temps
   142|    print("\n  TEMPERATURES:")
   143|    sensors = list(ic.get_sensor_data())
   144|    for s in sensors:
   145|        if s.type == "Temperature" and s.value is not None:
   146|            label = s.name
   147|            temp = s.value
   148|            if temp >= 85:
   149|                icon = "[!!!]"
   150|            elif temp >= 70:
   151|                icon = "[!! ]"
   152|            else:
   153|                icon = "[OK ]"
   154|            print(f"    {icon} {label:<22s} {temp:>5.1f}{s.units}")
   155|
   156|    # Fans
   157|    print("\n  FANS:")
   158|    for s in sensors:
   159|        if s.type == "Fan" and s.value is not None:
   160|            rpm = s.value
   161|            if rpm < 200:
   162|                icon = "[!!!]"
   163|            elif rpm < 500:
   164|                icon = "[!! ]"
   165|            else:
   166|                icon = "[OK ]"
   167|            print(f"    {icon} {s.name:<22s} {rpm:>7.0f} {s.units}")
   168|
   169|    # Fan control
   170|    mode = get_fan_mode(ic)
   171|    z0 = get_duty(ic, 0)
   172|    z1 = get_duty(ic, 1)
   173|    print(f"\n  FAN CONTROL:")
   174|    print(f"    Mode:     {mode}")
   175|    print(f"    Zone 0:   {z0}%" if z0 is not None else "    Zone 0:   N/A")
   176|    print(f"    Zone 1:   {z1}%" if z1 is not None else "    Zone 1:   N/A")
   177|
   178|    print("=" * 55)
   179|
   180|
   181|def main():
   182|    print()
   183|    print("  Supermicro IPMI Fan Control")
   184|    print("  Stops fan churning on X9/X10/X11/X12 boards")
   185|    print()
   186|
   187|    # Check config
   188|    if BMC_PASSWORD=*** "your-password":
   189|        print("  ERROR: Edit the CONFIG section at the top of this script")
   190|        print("         Set BMC_IP, BMC_USER, and BMC_PASSWORD")
   191|        sys.exit(1)
   192|
   193|    ic = connect()
   194|    print("  Connected!\n")
   195|
   196|    while True:
   197|        show_status(ic)
   198|
   199|        print("\n  QUICK PRESETS:")
   200|        print("    [q] Quiet    — Heavy Duty, 40%/30% (near silent)")
   201|        print("    [n] Normal   — Heavy Duty, 50%/40% (balanced)")
   202|        print("    [c] Cool     — Heavy Duty, 70%/60% (more airflow)")
   203|        print("    [f] Full     — 100% all fans (max cooling)")
   204|        print("    [r] Reset    — Standard mode (BMC auto, factory default)")
   205|        print()
   206|        print("    [m] Manual   — pick mode + duty yourself")
   207|        print("    [s] Status   — refresh readings")
   208|        print("    [x] Exit")
   209|
   210|        choice = input("\n  Choice: ").strip().lower()
   211|
   212|        if choice == "x":
   213|            print()
   214|            break
   215|
   216|        elif choice == "s":
   217|            continue
   218|
   219|        elif choice in PRESETS:
   220|            name, mode, z0, z1 = PRESETS[choice]
   221|            print(f"\n  Applying preset: {name}...")
   222|            apply_fan_control(ic, mode, z0, z1)
   223|            input("\n  Press Enter to see results...")
   224|
   225|        elif choice == "m":
   226|            print("\n  Select mode:")
   227|            for k, (code, name, desc) in FAN_MODES.items():
   228|                print(f"    [{k}] {name:<16s} — {desc}")
   229|            mode_choice = input("  Mode: ").strip()
   230|            if mode_choice not in FAN_MODES:
   231|                print("  Invalid choice")
   232|                continue
   233|
   234|            mode_hex = FAN_MODES[mode_choice][0]
   235|
   236|            # Duty cycle only makes sense for Heavy Duty mode
   237|            z0, z1 = None, None
   238|            if mode_hex == "00":
   239|                try:
   240|                    z0 = int(input("  Zone 0 duty % (10-100): ").strip())
   241|                    z1 = int(input("  Zone 1 duty % (10-100): ").strip())
   242|                    z0 = max(10, min(100, z0))
   243|                    z1 = max(10, min(100, z1))
   244|                except ValueError:
   245|                    print("  Invalid value, using defaults (50/40)")
   246|                    z0, z1 = 50, 40
   247|
   248|            print("\n  Applying...")
   249|            apply_fan_control(ic, mode_hex, z0, z1)
   250|            input("\n  Press Enter to see results...")
   251|
   252|        else:
   253|            print("  Invalid choice")
   254|
   255|    print("  Bye!")
   256|    ic.ipmi_session.logout()
   257|
   258|
   259|if __name__ == "__main__":
   260|    main()
   261|