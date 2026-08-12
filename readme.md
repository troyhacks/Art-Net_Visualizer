# Art-Net LED Map Visualizer

A Python tool to visualize LED maps by receiving and displaying Art-Net data in real-time.

## Features

- Receives Art-Net DMX packets over the network
- Displays pixels according to your LED map configuration
- Handles both dense and sparse LED maps
- Supports multiple Art-Net universes
- Real-time visualization at 60 FPS
- Cross-platform (Windows, Mac, Linux)

## Installation

### Requirements

- Python 3.7+
- pygame

### Install Dependencies

```bash
pip install pygame
```

Or on some systems:

```bash
pip3 install pygame
```

## Usage

### Basic Usage

```bash
python artnet_visualizer.py your_map.json
```

### With Options

```bash
python artnet_visualizer.py wiggle_ledmap2.json --universe 0 --pixels-per-universe 170 --pixel-size 15
```

### Command Line Options

- `map_file` - Path to your LED map JSON file (required)
- `--universe, -u` - Starting Art-Net universe number (default: 0)
- `--pixels-per-universe, -p` - Pixels per universe (default: 170 for 510 bytes)
- `--pixel-size, -s` - Display size of each pixel square in pixels (default: 10)
- `--bg-color, -b` - Background color as R,G,B (default: 20,20,20)

### Examples

**48x48 Wiggle map starting at universe 0:**
```bash
python artnet_visualizer.py wiggle_ledmap2.json -u 0 -p 170 -s 12
```

**32x32 sparse map with 384 pixels:**
```bash
python artnet_visualizer.py projection.json -u 0 -p 170 -s 15 -b 0,0,10
```

**Quick config - 16 outputs with 144 LEDs each:**
```bash
# Display output 0 (universes 0-0, since 144 LEDs fits in 1 universe)
python artnet_visualizer.py mymap.json --quick-config 16x144 --output 0

# Display output 5 (universes 5-5)
python artnet_visualizer.py mymap.json -q 16x144 -o 5

# Display output 15 (universes 15-15)
python artnet_visualizer.py mymap.json -q 16x144 -o 15
```

**Quick config - 28 outputs with 1020 LEDs each:**
```bash
# Display output 0 (universes 0-5, since 1020 LEDs needs 6 universes)
python artnet_visualizer.py mymap.json -q 28x1020 -o 0

# Display output 10 (universes 60-65)
python artnet_visualizer.py mymap.json -q 28x1020 -o 10
```

**Using artnetmap usermod config:**
```bash
# Display output 0 from artnetmap config
python artnet_visualizer.py mymap.json --artnetmap artnetmap_mysetup.json --output 0

# Display output 15 (automatically uses correct universes and pixel count)
python artnet_visualizer.py mymap.json -a artnetmap_mysetup.json -o 15
```

**Custom universe configuration:**
```bash
python artnet_visualizer.py mymap.json -u 5 -p 100 -s 20
```

## How It Works

1. **Loads LED Map**: Reads your JSON map file and determines:
   - Grid dimensions (width × height)
   - Which logical positions map to physical LEDs
   - How many real pixels exist (counts non-null entries)
   - How many Art-Net universes are needed

2. **Listens for Art-Net**: Opens UDP socket on port 6454 and listens for Art-Net DMX packets

3. **Processes Packets**: 
   - Validates Art-Net header and opcode
   - Extracts universe number and DMX data
   - Maps DMX RGB data to physical pixel indices
   - Updates pixel buffer

4. **Displays Grid**: 
   - Renders each mapped pixel at its logical position
   - Shows unmapped positions as background color
   - Updates display at 60 FPS

## LED Map Format

Your JSON map file should have this structure:

```json
{
  "n": "Map Name",
  "width": 32,
  "height": 32,
  "map": [
    -1, -1, 0, 1, 2, -1, -1,
    ...
  ]
}
```

Where:
- `n`: Name of the map
- `width`: Grid width
- `height`: Grid height  
- `map`: Array of width × height entries
  - `-1` or `null`: Unmapped/ghost pixel
  - `0-N`: Physical LED index

The map uses "logical-to-physical" format:
- `map[logicalPosition] = physicalLED`

## ArtNetMap Usermod Config Format

If you're using the WLE-DMM artnetmap usermod, you can use its config file directly:

```
{"n":28,"ch":510,"ip":"192.168.1.255","pad":0}
[0,6,12,18,24,30,36,42,48,54,60,66,72,78,84,90,96,102,108,114,120,126,132,138,144,150,156,162]
[1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020,1020]
```

Format:
- Line 1: JSON metadata (`n`=outputs, `ch`=channels/universe, `ip`=target, `pad`=padding mode)
- Line 2: JSON array of start universes for each output
- Line 3: JSON array of LED counts for each output

Use with `--artnetmap` flag:
```bash
python artnet_visualizer.py mymap.json --artnetmap artnetmap_preset.json --output 0
```

The visualizer will automatically configure universes and pixel counts for the selected output.

## Keyboard Controls

- `ESC` or `Q` - Quit the visualizer

## Troubleshooting

### No display showing

- Make sure your controller is sending Art-Net to the correct IP address
- Check that the universe numbers match (`--universe` parameter)
- Verify pixels per universe matches your controller configuration
- Try capturing network traffic with Wireshark to verify Art-Net packets are being sent

### Wrong colors/positions

- Verify your LED map file matches your physical layout
- Check that the starting universe is correct
- Ensure pixels per universe matches your controller (default 170 = 510 bytes ÷ 3)

### Performance issues

- Reduce pixel size with `--pixel-size` option
- Check network traffic - too many packets can overwhelm processing
- Close other applications using network resources

## Technical Details

### Art-Net Packet Structure

The visualizer expects standard Art-Net DMX packets:
- Port: 6454 UDP
- OpCode: 0x5000 (DMX)
- Protocol: 14
- RGB data: 3 bytes per pixel

### Pixel Mapping

The tool builds a reverse lookup table:
```
reverse_map[physical_pixel_index] = (x, y) display position
```

This allows efficient rendering regardless of how complex the LED map is.

### Universe Calculation

Number of universes = ceil(real_pixel_count / pixels_per_universe)

Example:
- 384 real pixels ÷ 170 pixels/universe = 2.26 → 3 universes needed
- Universe 0: pixels 0-169
- Universe 1: pixels 170-339  
- Universe 2: pixels 340-383

## Advanced Usage

### Testing Multiple Configurations

Create a test script:

```bash
#!/bin/bash
# Test different maps
python artnet_visualizer.py maps/wiggle.json -u 0 -s 8 &
python artnet_visualizer.py maps/projection.json -u 10 -s 12 &
wait
```

### Network Configuration

To listen on a specific interface:
```python
# Modify the bind line in the script:
self.sock.bind(('192.168.1.100', ARTNET_PORT))  # Specific IP
```

### Custom Background Patterns

Modify the `draw()` method to add grid lines, labels, or other visual aids:

```python
# Draw grid lines every 8 pixels
for i in range(0, self.width, 8):
    pygame.draw.line(self.screen, (50, 50, 50), 
                     (i * self.pixel_size, 0),
                     (i * self.pixel_size, self.height * self.pixel_size))
```

## License

This tool is provided as-is for testing LED maps. Use freely for personal and commercial projects.

## Related Tools

- **WLED** - The LED control software this visualizer is designed to test with
- **Art-Net** - Industry standard lighting control protocol
- **xLights** - Sequencing software that can output Art-Net

## Contributing

Feel free to extend this tool with features like:
- SACN/E1.31 support
- Color space conversions
- Brightness controls
- Recording/playback of Art-Net streams
- Multi-display support for huge installations