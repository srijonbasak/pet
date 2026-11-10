"""Read NetworkManager's cached 2.4 GHz network list without changing Wi-Fi."""

import subprocess


def _split_nmcli(line):
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def computer_networks():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-e", "yes", "-f", "SSID,FREQ,SIGNAL,SECURITY",
             "device", "wifi", "list", "--rescan", "no"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    networks = {}
    for line in result.stdout.splitlines():
        fields = _split_nmcli(line)
        if len(fields) != 4:
            continue
        name, frequency, signal, security = fields
        try:
            mhz = int(frequency.split()[0])
            strength = int(signal)
        except (ValueError, IndexError):
            continue
        if name and 2400 <= mhz < 2500 and (name not in networks or strength > networks[name][0]):
            networks[name] = (strength, security in ("", "--"))
    return [(name, *details) for name, details in sorted(networks.items(), key=lambda item: -item[1][0])]
