# Screenshots

Drop PNG files here with the names listed below. The main README references them.

| Filename | Capture | Notes |
|---|---|---|
| `dashboard-overview.png` | The full server card with sensor grid + history charts (top of page, scrolled to top) | Main hero shot. Shoot at ~1280px wide for clarity. |
| `fan-control.png` | Fan Control panel expanded showing presets + zone slider + Recent auto adjustments table | One server card with the `<details>` for Fan Control open. |
| `sel-log.png` | System Event Log panel expanded with a few entries | Open the SEL details on a server card. |
| `voltages.png` | Voltages collapsed-section expanded showing the dense mini-tile grid | Open the Voltages `<details>`. |
| `storage.png` | Storage card with disk tiles (Joe's CUBE has 14 disks, mix of Parity/Data/Cache/NVMe) | Wait for at least one poll cycle so tiles are populated. Helpful if any disk shows a non-PASS health for visual variety. |
| `alert-banner.png` | The red/amber alert banner across the top (any active alert) | Threshold breach event. Optional. |
| `multi-server.png` | Two server cards side-by-side | Configure two BMCs, screenshot the grid layout. |

## Tips

- Capture at native resolution, then GitHub auto-scales when embedded.
- Crop tightly to the relevant area; avoid huge whitespace.
- Use a private/incognito browser window so plugins and bookmarks don't leak into the shot.
- For visual consistency: light theme (the only theme right now), zoom level 100%.

## Tools

- **Windows**: Win+Shift+S then save as PNG.
- **macOS**: Cmd+Shift+4 then drag-select.
- **Linux**: Flameshot or `gnome-screenshot -a`.
