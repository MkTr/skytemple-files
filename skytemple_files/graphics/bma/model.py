import math
from typing import Tuple, List

from PIL import Image, ImageDraw, ImageFont

from skytemple_files.common.util import *
from skytemple_files.graphics.bpa.model import Bpa
from skytemple_files.graphics.bpc.model import Bpc, BPC_TILE_DIM

# Mask palette used for image composition
MASK_PAL = [
    0x00, 0x00, 0x00,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff,
]
MASK_PAL *= 16


class Bma:
    def __init__(self, data: bytes):
        from skytemple_files.common.types.file_types import FileType
        if not isinstance(data, memoryview):
            data = memoryview(data)

        self.map_width_camera = read_uintle(data, 0)
        self.map_height_camera = read_uintle(data, 1)
        # ALL game maps have the same values here. Changing them does nothing,
        # so the game seems to be hardcoded to 3x3.
        self.tiling_width = read_uintle(data, 2)
        self.tiling_height = read_uintle(data, 3)
        # Map width & height in chunks, so map.map_width_camera / map.tiling_width
        # The only maps this is not true for are G01P08A. S01P01B, S15P05A, S15P05B, it seems they
        # are missing one tile in width (32x instead of 33x)
        # The game doesn't seem to care if this value is off by less than 3 (tiling_w/h).
        # But NOTE that this has consequences for the collision and unknown data layers! See notes at collision
        # below!
        self.map_width_chunks = read_uintle(data, 4)
        self.map_height_chunks = read_uintle(data, 5)
        # Through tests against the BPC, it was determined that unk5 is the number of layers:
        # It seems to be ignored by the game, however
        self.number_of_layers = read_uintle(data, 6, 2)
        # Some kind of boolean flag? Seems to control if there is a third data block between
        # layer data and collision - Seems to be related to NPC conversations, see below.
        self.unk6 = read_uintle(data, 8, 2)
        # Some maps weirdly have 0x02 here and then have two collision layers, but they always seem redundant?
        self.number_of_collision_layers = read_uintle(data, 0xA, 2)

        # in p01p01a: 0xc - 0x27: Layer 1 header? 0xc messes everthing up. after that each row? 27 rows...?
        #             0xc -> 0xc8 = 200
        #             Same again? 0x28 is 0xc8 again. 0x29 - 0x43 are 27 rows for layer 1 again... Seems to repeat, with some odd ones in between
        #             Sometimes 0xC6 instead: Only 21 entries?
        #             -> UNTIL 0x214. At 0x215 Layer 2 starts.
        #             SEEMS TO BE NRL ENCODING:
        #                   2x12 bits of information stored in 3 bytes. C8 ->
        #                       Copy next and repeat 8 types (=9). 3x9=27!
        #               Decompressed length = (map_width_chunks*map_height_chunks*12)/8
        #                   = 513
        #               27 / 1,5 = 18! So the first set contains each tile for each row.
        #
        #               This seems to be the solution, it's the same for RRT
        #               [It also explains why changing a tile changes all tiles below!!]:
        #               "Each row has a series of Pair-24 NRL compressed values,
        #               one for each chunk column (rounded up to the nearest even number).
        #               These values are xor'ed with the respective indices of the previous
        #               row to get the actual indices of the chunks in the current row.
        #               The first row assumes all previous indices were 0."
        #               source:
        #               https://projectpokemon.org/docs/mystery-dungeon-nds/rrt-background-format-r113/
        #
        number_of_bytes_per_layer = self.map_width_chunks * self.map_height_chunks * 2
        # If the map width is odd, we have one extra tile per row:
        if self.map_width_chunks % 2 != 0:
            number_of_bytes_per_layer += self.map_height_chunks * 2
        number_of_bytes_per_layer = math.ceil(number_of_bytes_per_layer)

        # Read first layer
        self.layer0, compressed_layer0_size = self._read_layer(FileType.BMA_LAYER_NRL.decompress(
            data[0xC:],
            stop_when_size=number_of_bytes_per_layer
        ))
        self.layer1 = None
        compressed_layer1_size = 0
        collision_size = 0
        if self.number_of_layers > 1:
            # Read second layer
            self.layer1, compressed_layer1_size = self._read_layer(FileType.BMA_LAYER_NRL.decompress(
                data[0xC + compressed_layer0_size:],
                stop_when_size=number_of_bytes_per_layer
            ))

        offset_begin_next = 0xC + compressed_layer0_size + compressed_layer1_size
        self.unknown_data_block = None
        if self.unk6:
            # Unknown data block in generic NRL for "chat places"?
            # Seems to have something to do with counters? Like shop counters / NPC interactions.
            # Theory from looking at the maps:
            # It seems that if the player tries interact on these blocks, the game checks the other blocks for NPCs
            # to interact with (as if the player were standing on them)
            self.unknown_data_block, data_block_len = self._read_unknown_data_block(FileType.GENERIC_NRL.decompress(
                data[offset_begin_next:],
                # It is unknown what size calculation is actually used here in game, see notes below for collision
                # (search for 'NOTE!!!')
                # We assume it's the same as for the collision.
                stop_when_size=self.map_width_camera * self.map_height_camera
            ))
            offset_begin_next += data_block_len
        self.collision = None
        if self.number_of_collision_layers > 0:
            # Read level collision
            # The collision is stored like this:
            # RLE:
            # Each byte codes one byte, that can have the values 0 or 1.
            # The highest bit determines whether to output 0 or 1 bytes. All the other
            # bits form an unsigned integer. This int determines the number of bytes to output. 1 extra
            # byte is always output. (So 0x03 means output 4 0 bytes and 0x83 means output 4 1 bytes).
            # The maximum value of repeats is the map with in 8x8 tiles. So for a 54 tile map, the max values
            # are 0x53 and 0xC3.
            #
            # To get the actual collision value, all bytes are XORed with the value of the tile in the previous row,
            # this is the same principle as for the layer tile indices.
            # False (0) = Walktru; True (1) = Solid
            #
            # NOTE!!! Tests have shown, that the collision layers use map_width_camera and map_height_camera
            #         instead of map_width/height_chunks * tiling_width/height. The map that proves this is G01P08A!
            number_of_bytes_for_col = self.map_width_camera * self.map_height_camera
            self.collision, collision_size = self._read_collision(FileType.BMA_COLLISION_RLE.decompress(
                data[offset_begin_next:],
                stop_when_size=number_of_bytes_for_col
            ))
            offset_begin_next += collision_size
        self.collision2 = None
        if self.number_of_collision_layers > 1:
            # A second collision layer...?
            number_of_bytes_for_col = self.map_width_camera * self.map_height_camera
            self.collision2, collision_size2 = self._read_collision(FileType.BMA_COLLISION_RLE.decompress(
                data[offset_begin_next:],
                stop_when_size=number_of_bytes_for_col
            ))

    def __str__(self):
        return f"M: {self.map_width_camera}x{self.map_height_camera}, " \
               f"T: {self.tiling_width}x{self.tiling_height} - " \
               f"MM: {self.map_width_chunks}x{self.map_height_chunks} - " \
               f"L: {self.number_of_layers} - " \
               f"Col: {self.number_of_collision_layers} - " \
               f"unk6: 0x{self.unk6:04x}"

    def _read_layer(self, data: Tuple[bytes, int]):
        # To get the actual index of a chunk, the value is XORed with the tile value right above!
        previous_row_values = [0 for _ in range(0, self.map_width_chunks)]
        layer = []
        max_tiles = self.map_width_chunks * self.map_height_chunks
        i = 0
        skipped_on_prev = True
        for chunk in iter_bytes(data[0], 2):
            chunk = int.from_bytes(chunk, 'little')
            if i >= max_tiles:
                # this happens if there is a leftover 12bit word.
                break
            index_in_row = i % self.map_width_chunks
            # If the map width is odd, there is one extra chunk at the end of every row,
            # we remove this chunk.
            # TODO: DO NOT FORGET TO ADD THEM BACK DURING SERIALIZATION
            if not skipped_on_prev and index_in_row == 0 and self.map_width_chunks % 2 != 0:
                skipped_on_prev = True
                continue
            skipped_on_prev = False
            cv = chunk ^ previous_row_values[index_in_row]
            previous_row_values[index_in_row] = cv
            layer.append(cv)
            i += 1
        return layer, data[1]

    def _read_collision(self, data: Tuple[bytes, int]):
        # To get the actual index of a chunk, the value is XORed with the tile value right above!
        previous_row_values = [False for _ in range(0, self.map_width_camera)]
        col = []
        for i, chunk in enumerate(data[0]):
            index_in_row = i % self.map_width_camera
            cv = bool(chunk ^ int(previous_row_values[index_in_row]))
            previous_row_values[index_in_row] = cv
            col.append(cv)
        return col, data[1]

    def _read_unknown_data_block(self, data: Tuple[bytes, int]):
        # TODO: There doesn't seem to be this XOR thing here?
        unk = []
        for i, chunk in enumerate(data[0]):
            unk.append(chunk)
        return unk, data[1]

    def to_pil(
            self, bpc: Bpc, palettes: List[List[int]], bpas: List[Bpa],
            include_collision=True, include_unknown_data_block=True
    ) -> List[Image.Image]:
        """
        Converts the entire map into an image, as shown in the game. Each PIL image in the list returned is one
        frame. The palettes argument can be retrieved from the map's BPL (bpl.palettes).

        The method does not care about frame speeds. Each step of animation is simply returned as a new image,
        so if BPAs use different frame speeds, this is ignored; they effectively run at the same speed.
        If BPAs are using a different amount of frames per tile, the length of returned list of images will be the lowest
        common denominator of the different frame lengths.

        Does not include palette animations. You can apply them by switching out the palettes of the PIL
        using the information provided by the BPL.

        TODO: The speed can be increased SIGNIFICANTLY if we only re-render the changed
              animated tiles instead!
        """

        chunk_width = BPC_TILE_DIM * self.tiling_width
        chunk_height = BPC_TILE_DIM * self.tiling_height

        width_map = self.map_width_chunks * chunk_width
        height_map = self.map_height_chunks * chunk_height

        final_images = []
        lower_layer_bpc = 0 if bpc.number_of_layers == 1 else 1
        chunks_lower = bpc.chunks_animated_to_pil(lower_layer_bpc, palettes, bpas, 1)
        for img in chunks_lower:
            fimg = Image.new('P', (width_map, height_map))
            fimg.putpalette(img.getpalette())

            # yes. self.layer0 is always the LOWER layer! It's the opposite from BPC
            for i, mt_idx in enumerate(self.layer0):
                x = i % self.map_width_chunks
                y = math.floor(i / self.map_width_chunks)
                fimg.paste(
                    img.crop((0, mt_idx * chunk_width, chunk_width, mt_idx * chunk_width + chunk_height)),
                    (x * chunk_width, y * chunk_height)
                )

            final_images.append(fimg)

        if bpc.number_of_layers > 1:
            # Overlay higher layer tiles
            chunks_higher = bpc.chunks_animated_to_pil(0, palettes, bpas, 1)
            len_lower = len(chunks_lower)
            len_higher = len(chunks_higher)
            if len_higher != len_lower:
                # oh fun! We are missing animations for one of the layers, let's stretch to the lowest common multiple
                lm = lcm(len_higher, len_lower)
                for i in range(len_lower, lm):
                    final_images.append(final_images[i % len_lower].copy())
                for i in range(len_higher, lm):
                    chunks_higher.append(chunks_higher[i % len_higher].copy())

            for j, img in enumerate(chunks_higher):
                fimg = final_images[j]
                for i, mt_idx in enumerate(self.layer1):
                    x = i % self.map_width_chunks
                    y = math.floor(i / self.map_width_chunks)

                    cropped_img = img.crop((0, mt_idx * chunk_width, chunk_width, mt_idx * chunk_width + chunk_height))
                    cropped_img_mask = cropped_img.copy()
                    cropped_img_mask.putpalette(MASK_PAL)
                    fimg.paste(
                        cropped_img,
                        (x * chunk_width, y * chunk_height),
                        mask=cropped_img_mask.convert('1')
                    )

        final_images_were_rgb_converted = False
        if include_collision and self.number_of_collision_layers > 0:
            for i, img in enumerate(final_images):
                final_images_were_rgb_converted = True
                # time for some RGB action!
                final_images[i] = img.convert('RGB')
                img = final_images[i]
                draw = ImageDraw.Draw(img, 'RGBA')
                for j, col in enumerate(self.collision):
                    x = j % self.map_width_camera
                    y = math.floor(j / self.map_width_camera)
                    if col:
                        draw.rectangle((
                            (x * BPC_TILE_DIM, y * BPC_TILE_DIM),
                            ((x+1) * BPC_TILE_DIM, (y+1) * BPC_TILE_DIM)
                        ), fill=(0xff, 0x00, 0x00, 0x40))
                # Second collision layer
                if self.number_of_collision_layers > 1:
                    for j, col in enumerate(self.collision2):
                        x = j % self.map_width_camera
                        y = math.floor(j / self.map_width_camera)
                        if col:
                            draw.ellipse((
                                (x * BPC_TILE_DIM, y * BPC_TILE_DIM),
                                ((x+1) * BPC_TILE_DIM, (y+1) * BPC_TILE_DIM)
                            ), fill=(0x00, 0x00, 0xff, 0x40))

        if include_unknown_data_block and self.unk6 > 0:
            fnt = ImageFont.load_default()
            for i, img in enumerate(final_images):
                if not final_images_were_rgb_converted:
                    final_images[i] = img.convert('RGB')
                    img = final_images[i]
                draw = ImageDraw.Draw(img, 'RGBA')
                for j, unk in enumerate(self.unknown_data_block):
                    x = j % self.map_width_camera
                    y = math.floor(j / self.map_width_camera)
                    if unk > 0:
                        draw.text(
                            (x * BPC_TILE_DIM, y * BPC_TILE_DIM),
                            str(unk),
                            font=fnt,
                            fill=(0x00, 0xff, 0x00)
                        )

        return final_images