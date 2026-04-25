     1|#!/usr/bin/env python3
     2|"""
     3|Supermicro IPMI Fan Control — Stop the churning.
     4|Works on Windows, Mac, Linux.
     5|Uses ipmitool via subprocess (auto-downloaded on Windows, pre-installed on Linux/Mac).
     6|
     7|Usage:
     8|  1. Edit the CONFIG section below with your BMC details
     9|  2. Run: python ipmi-fan-control.py
    10|  3. Pick a preset
    11|  4. Done — fans stay fixed until you change them
    12|
    13|Requirements: Python 3.6+ (ipmitool auto-downloaded)
    14|"""
    15|
    16|# ============================================================
    17|# CONFIG — Edit these three values
    18|# ============================================================
    19|BMC_IP       = "192.168.1.100"   # Your BMC/IPMI IP address
    20|BMC_USER     = "ADMIN"           # Your IPMI username
    21|BMC_PASSWORD="***"   # Your IPMI password
    22|# ============================================================
    23|
    24|
    25|import os
    26|import sys
    27|import platform
    28|import subprocess
    29|import time
    30|import urllib.request
    31|import zipfile
    32|
    33|PRESETS = {
    "q": ("Quiet",   "01", 40, 30),
    "n": ("Normal",  "01", 50, 40),
    "c": ("Cool",    "01", 70, 60),
    37|    "f": ("Full",    "02", None, None),
    38|    "r": ("Reset",   "01", None, None),
    39|}
    40|
    41|IPMITOOL_URL = "https://github.com/arcress/ipmitool-win/archive/refs/heads/master.zip"
    42|IPMITOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipmitool-win")
    43|
    44|
    45|def find_ipmitool():
    46|    """Find or install ipmitool."""
    47|    system = platform.system()
    48|
    49|    if system == "Windows":
    50|        # Check for ipmitool.exe in PATH, then local dir
    51|        exe = "ipmitool.exe"
    52|        # Check common locations
    53|        candidates = [
    54|            os.path.join(IPMITOOL_DIR, "ipmitool.exe"),
    55|            os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipmitool.exe"),
    56|            exe,  # check PATH
    57|        ]
    58|        for c in candidates:
    59|            try:
    60|                result = subprocess.run([c, "-V"], capture_output=True, text=True, timeout=5)
    61|                if result.returncode == 0:
    62|                    print(f"  Found ipmitool: {c}")
    63|                    return c
    64|            except:
    65|                continue
    66|
    67|        # Not found — offer to download
    68|        print("  ipmitool not found on your system.")
    69|        print()
    70|        download = input("  Download ipmitool for Windows? [Y/n]: ").strip().lower()
    71|        if download in ("", "y", "yes"):
    72|            download_ipmitool_windows()
    73|            # Find it again
    74|            for c in candidates:
    75|                try:
    76|                    subprocess.run([c, "-V"], capture_output=True, timeout=5)
    77|                    return c
    78|                except:
    79|                    continue
    80|        print("  ERROR: ipmitool is required. Install it and try again.")
    81|        sys.exit(1)
    82|
    83|    else:
    84|        # Linux/Mac — check then install
    85|        try:
    86|            result = subprocess.run(["ipmitool", "-V"], capture_output=True, text=True, timeout=5)
    87|            if result.returncode == 0:
    88|                return "ipmitool"
    89|        except FileNotFoundError:
    90|            pass
    91|
    92|        print("  ipmitool not found. Installing...")
    93|        if system == "Darwin":
    94|            subprocess.run(["brew", "install", "ipmitool"], check=False)
    95|        else:
    96|            subprocess.run(["sudo", "apt-get", "install", "-y", "ipmitool"], check=False)
    97|
    98|        try:
    99|            subprocess.run(["ipmitool", "-V"], capture_output=True, timeout=5)
   100|            return "ipmitool"
   101|        except:
   102|            print("  ERROR: Could not install ipmitool. Install it manually.")
   103|            sys.exit(1)
   104|
   105|
   106|def download_ipmitool_windows():
   107|    """Download ipmitool for Windows."""
   108|    import tempfile
   109|    script_dir = os.path.dirname(os.path.abspath(__file__))
   110|
   111|    print("  Downloading ipmitool for Windows...")
   112|    try:
   113|        zip_path = os.path.join(tempfile.gettempdir(), "ipmitool-win.zip")
   114|        urllib.request.urlretrieve(IPMITOOL_URL, zip_path)
   115|
   116|        with zipfile.ZipFile(zip_path, 'r') as zf:
   117|            zf.extractall(tempfile.gettempdir())
   118|
   119|        # Find the exe in the extracted dir
   120|        extracted = os.path.join(tempfile.gettempdir(), "ipmitool-win-master")
   121|        for root, dirs, files in os.walk(extracted):
   122|            for f in files:
   123|                if f.lower() == "ipmitool.exe":
   124|                    src = os.path.join(root, f)
   125|                    dst = os.path.join(script_dir, "ipmitool.exe")
   126|                    with open(src, 'rb') as sf, open(dst, 'wb') as df:
   127|                        df.write(sf.read())
   128|                    print(f"  Installed ipmitool.exe to {dst}")
   129|                    os.unlink(zip_path)
   130|                    return
   131|
   132|        print("  WARNING: Could not find ipmitool.exe in download.")
   133|        print("  Download manually from: https://github.com/arcress/ipmitool-win")
   134|        os.unlink(zip_path)
   135|    except Exception as e:
   136|        print(f"  Download failed: {e}")
   137|        print("  Download manually from: https://github.com/arcress/ipmitool-win")
   138|        print("  Place ipmitool.exe next to this script.")
   139|
   140|
   141|def ipmi_raw(ipmitool, *args):
   142|    """Run ipmitool raw command and return stdout."""
   143|    cmd = [
   144|        ipmitool, "-I", "lanplus",
   145|        "-H", BMC_IP, "-U", BMC_USER, "-P", BMC_PASSWORD,
   146|        "-N", "5000", "-R", "1"
   147|    ] + list(args)
   148|    try:
   149|        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
   150|        return r.stdout.strip()
   151|    except:
   152|        return ""
   153|
   154|
   155|def ipmi_cmd(ipmitool, *args):
   156|    """Run ipmitool command and return stdout."""
   157|    cmd = [
   158|        ipmitool, "-I", "lanplus",
   159|        "-H", BMC_IP, "-U", BMC_USER, "-P", BMC_PASSWORD,
   160|        "-N", "5000", "-R", "1"
   161|    ] + list(args)
   162|    try:
   163|        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
   164|        return r.stdout.strip()
   165|    except:
   166|        return ""
   167|
   168|
   169|def get_fan_mode(ipmitool):
   170|    """Read current fan mode."""
   171|    raw = ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x00").strip().replace(" ", "")
   172|    names = {"00": "Heavy Duty", "01": "Standard", "02": "Full (100%)", "04": "Optimal", "10": "PUE2"}
   173|    if raw:
   174|        return f"{raw} ({names.get(raw, 'Unknown')})"
   175|    return "Unknown"
   176|
   177|
   178|def get_duty(ipmitool, zone):
   179|    """Read current duty cycle for a zone (0 or 1)."""
   180|    raw = ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x00", f"0x{zone:02x}")
   181|    raw = raw.strip().replace(" ", "")
   182|    if raw:
   183|        try:
   184|            return int(raw, 16)
   185|        except:
   186|            pass
   187|    return None
   188|
   189|
   190|def apply_fan_control(ipmitool, mode_hex, duty_z0=None, duty_z1=None):
   191|    """
   192|    Apply fan control with proper Supermicro BMC timing.
   193|    Proven sequence:
   194|      1. Force FULL mode (breaks out of any active preset)
   195|      2. Sleep 2s (BMC timing requirement)
   196|      3. Set target mode
   197|      4. Sleep 2s
   198|      5. Set duty cycles
   199|    """
   200|    mode_names = {"00": "Heavy Duty", "01": "Standard", "02": "Full", "04": "Optimal", "10": "PUE2"}
   201|    mode_name = mode_names.get(mode_hex, mode_hex)
   202|
   203|    print("  Transitioning BMC...")
   204|    ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x01", "0x02")  # Force FULL
   205|    print("  [1] Forced FULL mode")
   206|    time.sleep(2)
   207|
   208|    ipmi_raw(ipmitool, "raw", "0x30", "0x45", "0x01", mode_hex)  # Target mode
   209|    print(f"  [2] Mode set to {mode_name}")
   210|    time.sleep(2)
   211|
   212|    if duty_z0 is not None:
   213|        hex_z0 = f"0x{duty_z0:02x}"
   214|        ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x01", "0x00", hex_z0)
   215|        print(f"  [3] Zone 0 duty set to {duty_z0}%")
   216|        time.sleep(1)
   217|
   218|    if duty_z1 is not None:
   219|        hex_z1 = f"0x{duty_z1:02x}"
   220|        ipmi_raw(ipmitool, "raw", "0x30", "0x70", "0x66", "0x01", "0x01", hex_z1)
   221|        print(f"  [4] Zone 1 duty set to {duty_z1}%")
   222|        time.sleep(1)
   223|
   224|    # Verify
   225|    z0v = get_duty(ipmitool, 0)
   226|    z1v = get_duty(ipmitool, 1)
   227|    print(f"  [5] Verified: Z0={z0v}% Z1={z1v}%")
   228|    print("  Done!")
   229|
   230|
   231|def show_status(ipmitool):
   232|    """Show current sensor readings using ipmitool SDR."""
   233|    print("\n" + "=" * 55)
   234|    print(f"  BMC: {BMC_IP}")
   235|
   236|    # Temps
   237|    print("\n  TEMPERATURES:")
   238|    output = ipmi_cmd(ipmitool, "sdr", "type", "temperature")
   239|    for line in output.splitlines():
   240|        parts = line.split("|")
   241|        if len(parts) >= 5:
   242|            name = parts[0].strip()
   243|            status = parts[2].strip()
   244|            value = parts[4].strip()
   245|            if status.lower() == "ns" or "No Reading" in value:
   246|                print(f"    [---] {name:<22s} N/A")
   247|            else:
   248|                try:
   249|                    temp = int(value.split()[0])
   250|                    icon = "[!!!]" if temp >= 85 else "[!! ]" if temp >= 70 else "[OK ]"
   251|                    print(f"    {icon} {name:<22s} {temp}°C")
   252|                except:
   253|                    print(f"    [---] {name:<22s} {value}")
   254|
   255|    # Fans
   256|    print("\n  FANS:")
   257|    output = ipmi_cmd(ipmitool, "sdr", "type", "fan")
   258|    for line in output.splitlines():
   259|        parts = line.split("|")
   260|        if len(parts) >= 5:
   261|            name = parts[0].strip()
   262|            status = parts[2].strip()
   263|            value = parts[4].strip()
   264|            if status.lower() == "ns" or "No Reading" in value:
   265|                print(f"    [---] {name:<22s} NOT PRESENT")
   266|            elif "RPM" in value:
   267|                try:
   268|                    rpm = int(value.split()[0])
   269|                    icon = "[!!!]" if rpm < 200 else "[!! ]" if rpm < 500 else "[OK ]"
   270|                    print(f"    {icon} {name:<22s} {rpm} RPM")
   271|                except:
   272|                    print(f"    [---] {name:<22s} {value}")
   273|
   274|    # Fan control state
   275|    mode = get_fan_mode(ipmitool)
   276|    z0 = get_duty(ipmitool, 0)
   277|    z1 = get_duty(ipmitool, 1)
   278|    print(f"\n  FAN CONTROL:")
   279|    print(f"    Mode:     {mode}")
   280|    print(f"    Zone 0:   {z0}%" if z0 is not None else "    Zone 0:   N/A")
   281|    print(f"    Zone 1:   {z1}%" if z1 is not None else "    Zone 1:   N/A")
   282|    print("=" * 55)
   283|
   284|
   285|def main():
   286|    print()
   287|    print("  Supermicro IPMI Fan Control")
   288|    print("  Stops fan churning on X9/X10/X11/X12 boards")
   289|    print()
   290|
   291|    # Check config
   292|    if BMC_PASSWORD=*** "your-password":
   293|        print("  ERROR: Edit the CONFIG section at the top of this script")
   294|        print("         Set BMC_IP, BMC_USER, and BMC_PASSWORD")
   295|        sys.exit(1)
   296|
   297|    # Find/setup ipmitool
   298|    print("  Setting up ipmitool...")
   299|    ipmitool = find_ipmitool()
   300|
   301|    # Test connection
   302|    print(f"  Connecting to BMC at {BMC_IP}...")
   303|    test = ipmi_cmd(ipmitool, "mc", "info")
   304|    if not test:
   305|        print(f"  ERROR: Cannot reach BMC at {BMC_IP}")
   306|        print(f"  Check: IP correct? Password correct? IPMI enabled in BIOS?")
   307|        sys.exit(1)
   308|    print("  Connected!\n")
   309|
   310|    while True:
   311|        show_status(ipmitool)
   312|
   313|        print("\n  QUICK PRESETS:")
   314|        print("    [q] Quiet    — Standard, 40%/30% (stops churning)")
   315|        print("    [n] Normal   — Standard, 50%/40% (balanced)")
   316|        print("    [c] Cool     — Standard, 70%/60% (more airflow)")
   317|        print("    [f] Full     — 100% all fans (max cooling)")
   318|        print("    [r] Reset    — Standard mode (BMC auto, factory default)")
   319|        print()
   320|        print("    [m] Manual   — pick mode + duty yourself")
   321|        print("    [s] Status   — refresh readings")
   322|        print("    [x] Exit")
   323|
   324|        choice = input("\n  Choice: ").strip().lower()
   325|
   326|        if choice == "x":
   327|            print()
   328|            break
   329|        elif choice == "s":
   330|            continue
   331|        elif choice in PRESETS:
   332|            name, mode, z0, z1 = PRESETS[choice]
   333|            print(f"\n  Applying preset: {name}...")
   334|            apply_fan_control(ipmitool, mode, z0, z1)
   335|            input("\n  Press Enter to see results...")
   336|        elif choice == "m":
   337|            print("\n  Select mode:")
   338|            print("    [1] Heavy Duty  — fixed duty, quietest")
   339|            print("    [2] Standard    — BMC auto (factory)")
   340|            print("    [3] Full (100%) — max speed")
   341|            print("    [4] Optimal     — BMC balanced")
   342|            print("    [5] PUE2        — power save")
   343|            mode_choice = input("  Mode: ").strip()
   344|            modes = {"1": "00", "2": "01", "3": "02", "4": "04", "5": "10"}
   345|            if mode_choice not in modes:
   346|                print("  Invalid choice")
   347|                continue
   348|            mode_hex = modes[mode_choice]
   349|            z0, z1 = None, None
   350|            if mode_hex == "00":
   351|                try:
   352|                    z0 = int(input("  Zone 0 duty % (10-100): ").strip())
   353|                    z1 = int(input("  Zone 1 duty % (10-100): ").strip())
   354|                    z0 = max(10, min(100, z0))
   355|                    z1 = max(10, min(100, z1))
   356|                except ValueError:
   357|                    print("  Invalid value, using defaults (50/40)")
   358|                    z0, z1 = 50, 40
   359|            print("\n  Applying...")
   360|            apply_fan_control(ipmitool, mode_hex, z0, z1)
   361|            input("\n  Press Enter to see results...")
   362|        else:
   363|            print("  Invalid choice")
   364|
   365|
   366|if __name__ == "__main__":
   367|    main()
   368|