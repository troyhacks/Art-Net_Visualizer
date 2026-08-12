#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Art-Net LED Map Visualizer
Receives Art-Net data and displays it according to an LED map configuration
"""

import socket
import struct
import json
import pygame
import sys
import argparse
from typing import Dict, List, Tuple, Optional

# Art-Net constants
ARTNET_PORT = 6454
ARTNET_HEADER = b'Art-Net\x00'
ARTNET_OPCODE_DMX = 0x5000

class ArtNetVisualizer:
    def __init__(self, map_file: str, artnetmap_file: Optional[str] = None,
                 quick_config: Optional[str] = None,
                 universe_start: int = 0, pixels_per_universe: int = 170,
                 output_index: int = 0, pixel_size: int = 10,
                 background_color: Tuple[int, int, int] = (20, 20, 20)):
        """
        Initialize the Art-Net visualizer

        Args:
            map_file: Path to LED map JSON file
            artnetmap_file: Optional path to artnetmap usermod config (overrides universe settings)
            quick_config: Quick config pattern like "16x144" (16 outputs, 144 LEDs each)
            universe_start: Starting universe number (if no artnetmap/quick_config)
            pixels_per_universe: Pixels per Art-Net universe (default 170)
            output_index: Which output to display from artnetmap/quick_config (default 0)
            pixel_size: Size of each pixel square in the display
            background_color: RGB color for unmapped/background pixels
        """
        self.map_file = map_file
        self.artnetmap_file = artnetmap_file
        self.quick_config = quick_config
        self.output_index = output_index
        self.pixel_size = pixel_size
        self.background_color = background_color
        self.pixels_per_universe = pixels_per_universe

        # Load LED map
        self.load_map()

        # Load configuration (priority: artnetmap > quick_config > manual)
        if artnetmap_file:
            self.load_artnetmap()
        elif quick_config:
            self.generate_quick_config(quick_config)
        else:
            self.universe_start = universe_start
            self.num_universes = (self.real_pixel_count + pixels_per_universe - 1) // pixels_per_universe
            # Manual mode: treat the LED map as a single continuous output.
            # Universes [universe_start, universe_start + num_universes) carry
            # pixel_buffer[0..real_pixel_count-1] in order.
            self.output_start_universe = [universe_start]
            self.output_pixel_count = [self.real_pixel_count]
            self.output_universes = [self.num_universes]
            self.output_pixel_start = [0]
            self.active_outputs = [0]

        print(f"Loaded map: {self.map_name}")
        print(f"Dimensions: {self.width}x{self.height} ({self.width * self.height} logical positions)")
        print(f"Real pixels: {self.real_pixel_count}")
        print(f"Listening for {self.num_universes} universes starting at {self.universe_start}")
        print(f"Pixels per universe: {self.pixels_per_universe}")

        # Initialize pixel buffer (stores RGB values for real pixels)
        self.pixel_buffer = [(0, 0, 0)] * self.real_pixel_count

        # Initialize pygame
        pygame.init()
        self.screen = pygame.display.set_mode((self.width * pixel_size, self.height * pixel_size))
        pygame.display.set_caption(f"Art-Net Visualizer - {self.map_name}")
        self.clock = pygame.time.Clock()

        # Setup UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', ARTNET_PORT))
        self.sock.setblocking(False)

    def load_map(self):
        """Load LED map from JSON file"""
        with open(self.map_file, 'r') as f:
            data = json.load(f)

        self.map_name = data.get('n', 'Unknown')
        self.width = data['width']
        self.height = data['height']
        self.led_map = data['map']

        # Validate map size
        expected_size = self.width * self.height
        if len(self.led_map) != expected_size:
            raise ValueError(f"Map size mismatch: expected {expected_size}, got {len(self.led_map)}")

        # Count real pixels and build reverse mapping
        # reverse_map[physical_pixel] = (x, y) in display grid
        self.reverse_map: Dict[int, Tuple[int, int]] = {}
        self.real_pixel_count = 0

        for logical_pos, physical_led in enumerate(self.led_map):
            if physical_led != -1 and physical_led is not None:
                x = logical_pos % self.width
                y = logical_pos // self.width
                self.reverse_map[physical_led] = (x, y)
                if physical_led >= self.real_pixel_count:
                    self.real_pixel_count = physical_led + 1

        print(f"Built reverse map with {len(self.reverse_map)} entries")

    def load_artnetmap(self):
        """Load artnetmap usermod configuration"""
        with open(self.artnetmap_file, 'r') as f:
            # Read first line (metadata)
            line1 = f.readline().strip()
            metadata = json.loads(line1)

            # Read second line (start universe array)
            line2 = f.readline().strip()
            start_universes = json.loads(line2)

            # Read third line (LEDs per output array)
            line3 = f.readline().strip()
            leds_per_output = json.loads(line3)

        num_outputs = metadata['n']
        self.pixels_per_universe = metadata.get('ch', 510) // 3  # channels to pixels

        # Build per-output tables.
        # Each output's pixels occupy a contiguous slice of pixel_buffer,
        # starting at output_pixel_start[i] = sum(leds_per_output[0..i-1]).
        self.output_start_universe = list(start_universes)
        self.output_pixel_count = list(leds_per_output)
        self.output_universes = [
            (leds_per_output[i] + self.pixels_per_universe - 1) // self.pixels_per_universe
            for i in range(num_outputs)
        ]
        self.output_pixel_start = [0] * num_outputs
        for i in range(1, num_outputs):
            self.output_pixel_start[i] = (
                self.output_pixel_start[i - 1] + self.output_pixel_count[i - 1]
            )

        # If output_index is -1, listen to ALL outputs
        if self.output_index == -1:
            self.active_outputs = list(range(num_outputs))
            self.universe_start = min(start_universes)
            max_universe = 0
            for i in self.active_outputs:
                end_i = self.output_start_universe[i] + self.output_universes[i] - 1
                if end_i > max_universe:
                    max_universe = end_i
            self.num_universes = max_universe - self.universe_start + 1

            print(f"Loaded artnetmap config: '{metadata.get('name', 'unnamed')}'")
            print(f"Listening to ALL {num_outputs} outputs: universes {self.universe_start}-{max_universe}")
            print(f"Total LEDs expected: {sum(self.output_pixel_count)}")
        else:
            # Single output mode
            if self.output_index >= num_outputs:
                raise ValueError(f"Output index {self.output_index} out of range (0-{num_outputs-1})")

            self.active_outputs = [self.output_index]
            self.universe_start = self.output_start_universe[self.output_index]
            self.num_universes = self.output_universes[self.output_index]

            print(f"Loaded artnetmap config: '{metadata.get('name', 'unnamed')}'")
            out_leds = self.output_pixel_count[self.output_index]
            print(f"Output {self.output_index}: {out_leds} LEDs, universes {self.universe_start}-{self.universe_start + self.num_universes - 1}")
            print(f"Total outputs in config: {num_outputs}")

    def generate_quick_config(self, quick_config: str):
        """
        Generate simple sequential configuration from pattern like "16x144" or "28x1020"

        Args:
            quick_config: Pattern like "NxL" where N=outputs, L=LEDs per output
        """
        try:
            parts = quick_config.lower().split('x')
            if len(parts) != 2:
                raise ValueError("Quick config must be in format NxL (e.g., 16x144)")

            num_outputs = int(parts[0])
            leds_per_output = int(parts[1])

            if num_outputs < 1 or leds_per_output < 1:
                raise ValueError("Outputs and LEDs must be positive numbers")

            # Calculate universes per output based on standard universe capacity
            standard_pixels_per_universe = self.pixels_per_universe  # Usually 170
            universes_per_output = (leds_per_output + standard_pixels_per_universe - 1) // standard_pixels_per_universe

            # If output_index is -1, listen to ALL outputs
            if self.output_index == -1:
                self.universe_start = 0
                self.num_universes = num_outputs * universes_per_output
                total_leds = num_outputs * leds_per_output

                # IMPORTANT: Override pixels_per_universe for output-based config
                # Each universe carries exactly leds_per_output pixels (not 170)
                if universes_per_output == 1:
                    # If 1 universe per output, each universe has exactly leds_per_output pixels
                    self.pixels_per_universe = leds_per_output

                # Build per-output tables so process_dmx_data can find the owning output.
                self.output_start_universe = [i * universes_per_output for i in range(num_outputs)]
                self.output_universes = [universes_per_output] * num_outputs
                self.output_pixel_count = [leds_per_output] * num_outputs
                self.output_pixel_start = [i * leds_per_output for i in range(num_outputs)]
                self.active_outputs = list(range(num_outputs))

                print(f"Quick config: {num_outputs} outputs x {leds_per_output} LEDs")
                print(f"Universes per output: {universes_per_output}")
                print(f"Pixels per universe: {self.pixels_per_universe}")
                print(f"Listening to ALL outputs: universes 0-{self.num_universes - 1}")
                print(f"Total LEDs expected: {total_leds}")
            else:
                # Single output mode
                self.universe_start = self.output_index * universes_per_output
                self.num_universes = universes_per_output

                # Override pixels_per_universe for single-universe outputs
                if universes_per_output == 1:
                    self.pixels_per_universe = leds_per_output

                # Build per-output tables so process_dmx_data finds this output.
                self.output_start_universe = [self.universe_start]
                self.output_universes = [universes_per_output]
                self.output_pixel_count = [leds_per_output]
                self.output_pixel_start = [self.output_index * leds_per_output]
                self.active_outputs = [0]

                print(f"Quick config: {num_outputs} outputs x {leds_per_output} LEDs")
                print(f"Universes per output: {universes_per_output}")
                print(f"Pixels per universe: {self.pixels_per_universe}")
                print(f"Output {self.output_index}: universes {self.universe_start}-{self.universe_start + self.num_universes - 1}")

        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid quick config format '{quick_config}': {e}")

    def parse_artnet_packet(self, data: bytes) -> Optional[Tuple[int, bytes]]:
        """
        Parse Art-Net packet and return (universe, dmx_data) if valid

        Art-Net DMX packet structure:
        - 0-7: "Art-Net\0" header
        - 8-9: OpCode (0x5000 for DMX)
        - 10-11: Protocol version (14)
        - 12: Sequence
        - 13: Physical
        - 14-15: Universe (little-endian)
        - 16-17: Length (big-endian, number of DMX channels)
        - 18+: DMX data
        """
        if len(data) < 18:
            return None

        # Check header
        if data[0:8] != ARTNET_HEADER:
            return None

        # Check opcode
        opcode = struct.unpack('<H', data[8:10])[0]
        if opcode != ARTNET_OPCODE_DMX:
            return None

        # Extract universe (little-endian)
        universe = struct.unpack('<H', data[14:16])[0]

        # Extract length (big-endian)
        length = struct.unpack('>H', data[16:18])[0]

        # Extract DMX data
        dmx_data = data[18:18+length]

        return (universe, dmx_data)

    def process_dmx_data(self, universe: int, dmx_data: bytes):
        """Process DMX data from Art-Net packet"""
        if universe < self.universe_start or universe >= self.universe_start + self.num_universes:
            return  # Not for us

        # Find which output owns this universe. Padding/unused universes
        # (e.g. uni 4 between output 0 and output 1 in the libertine map)
        # match no output and are silently dropped.
        out_idx = None
        for i in self.active_outputs:
            start_u = self.output_start_universe[i]
            if start_u <= universe < start_u + self.output_universes[i]:
                out_idx = i
                break
        if out_idx is None:
            return

        # Pixel offset = where this output's slice starts in pixel_buffer
        # + offset within that output for this particular universe.
        universe_offset = universe - self.output_start_universe[out_idx]
        pixel_offset = self.output_pixel_start[out_idx] + universe_offset * self.pixels_per_universe
        output_pixel_end = self.output_pixel_start[out_idx] + self.output_pixel_count[out_idx]

        # Parse RGB data (assuming 3 bytes per pixel)
        num_pixels = len(dmx_data) // 3

        for i in range(num_pixels):
            pixel_index = pixel_offset + i
            if pixel_index >= output_pixel_end or pixel_index >= self.real_pixel_count:
                break

            r = dmx_data[i * 3]
            g = dmx_data[i * 3 + 1]
            b = dmx_data[i * 3 + 2]

            self.pixel_buffer[pixel_index] = (r, g, b)

    def draw(self):
        """Draw the LED grid"""
        # Fill background
        self.screen.fill(self.background_color)

        # Draw each mapped pixel
        for physical_pixel, (x, y) in self.reverse_map.items():
            if physical_pixel < len(self.pixel_buffer):
                color = self.pixel_buffer[physical_pixel]
                rect = pygame.Rect(
                    x * self.pixel_size,
                    y * self.pixel_size,
                    self.pixel_size,
                    self.pixel_size
                )
                pygame.draw.rect(self.screen, color, rect)

                # Optional: draw pixel border
                pygame.draw.rect(self.screen, (0,0,0), rect, 1) # was 40,40,40

        pygame.display.flip()

    def run(self):
        """Main loop"""
        running = True
        frames = 0

        try:
            while running:
                # Handle pygame events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
                            running = False

                # Process incoming Art-Net packets (non-blocking)
                packets_processed = 0
                while packets_processed < 100:  # Limit packets per frame
                    try:
                        data, addr = self.sock.recvfrom(4096)
                        result = self.parse_artnet_packet(data)
                        if result:
                            universe, dmx_data = result
                            self.process_dmx_data(universe, dmx_data)
                        packets_processed += 1
                    except BlockingIOError:
                        break  # No more packets available

                # Draw
                self.draw()

                # Limit frame rate
                self.clock.tick(60)  # 60 FPS

                frames += 1
                if frames % 60 == 0:
                    fps = self.clock.get_fps()
                    pygame.display.set_caption(f"Art-Net Visualizer - {self.map_name} - {fps:.1f} FPS")

        finally:
            self.sock.close()
            pygame.quit()

def main():
    parser = argparse.ArgumentParser(description='Art-Net LED Map Visualizer')
    parser.add_argument('map_file', help='Path to LED map JSON file')
    parser.add_argument('--artnetmap', '-a', type=str, default=None,
                        help='Path to artnetmap usermod config file')
    parser.add_argument('--quick-config', '-q', type=str, default=None,
                        help='Quick config pattern: NxL (e.g., "16x144" for 16 outputs, 144 LEDs each)')
    parser.add_argument('--output', '-o', type=int, default=-1,
                        help='Output index from artnetmap/quick-config (default: -1 = all outputs)')
    parser.add_argument('--universe', '-u', type=int, default=0,
                        help='Starting universe number (default: 0, ignored if --artnetmap or --quick-config used)')
    parser.add_argument('--pixels-per-universe', '-p', type=int, default=170,
                        help='Pixels per universe (default: 170)')
    parser.add_argument('--pixel-size', '-s', type=int, default=10,
                        help='Size of each pixel in display (default: 10)')
    parser.add_argument('--bg-color', '-b', type=str, default='20,20,20',
                        help='Background color as R,G,B (default: 20,20,20)')

    args = parser.parse_args()

    # Parse background color
    try:
        bg_color = tuple(int(x) for x in args.bg_color.split(','))
        if len(bg_color) != 3:
            raise ValueError
    except ValueError:
        print("Error: Background color must be in format R,G,B (e.g., 20,20,20)")
        sys.exit(1)

    try:
        visualizer = ArtNetVisualizer(
            args.map_file,
            artnetmap_file=args.artnetmap,
            quick_config=args.quick_config,
            universe_start=args.universe,
            pixels_per_universe=args.pixels_per_universe,
            output_index=args.output,
            pixel_size=args.pixel_size,
            background_color=bg_color
        )
        visualizer.run()
    except FileNotFoundError as e:
        print(f"Error: File not found: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()