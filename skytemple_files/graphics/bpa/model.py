import math
from typing import List

from PIL import Image

from skytemple_files.common.tiled_image import to_pil, TilemapEntry
from skytemple_files.common.util import *

BPA_PIXEL_BITLEN = 4
BPA_TILE_DIM = 8


class BpaFrameInfo:
    def __init__(self, unk1, unk2):
        # speed?
        self.unk1 = unk1
        # always 0?
        self.unk2 = unk2
        assert self.unk2 == 0


class Bpa:
    def __init__(self, data: bytes):
        if not isinstance(data, memoryview):
            data = memoryview(data)
        self.number_of_images = read_uintle(data, 0, 2)
        self.number_of_frames = read_uintle(data, 2, 2)

        # Read image header
        self.frame_info = []
        for i in range(0, self.number_of_frames):
            self.frame_info.append(BpaFrameInfo(
                read_uintle(data, 4 + i*4, 2),
                read_uintle(data, 4 + i*4 + 2, 2),
            ))
        end_header = 4 + self.number_of_frames * 4

        self.dbg_images = []

        self.tiles = []
        slice_size = int(BPA_TILE_DIM * BPA_TILE_DIM / 2)
        for i, tile in enumerate(iter_bytes(data, slice_size, end_header, end_header + (slice_size * self.number_of_frames * self.number_of_images))):
            self.tiles.append(bytearray(tile))

    def __str__(self):
        return f"Idx: {self.number_of_images}, " \
               f"#c: {self.number_of_frames}"

    def get_tile(self, tile_idx, frame_idx) -> bytes:
        """Returns the tile data of tile no. tile_idx for frame frame_idx."""
        return self.tiles[frame_idx * self.number_of_images + tile_idx]

    def tiles_to_pil(self, palette: List[int]) -> Image.Image:
        """
        Exports the BPA as an image, where each row of 8x8 tiles is the
        animation set for a single tile. The 16 color palette passed is used to color the image.
        """
        dummy_tile_map = []
        width_in_tiles = self.number_of_frames
        etr = self.number_of_frames * self.number_of_images

        # create a dummy tile map containing all the tiles
        # The tiles in the BPA are stored so, that each tile of the each frame is next
        # to each other. So the second frame of the first tile is at self.number_of_images + 1.
        for tile_idx in range(0, self.number_of_images):
            for frame_idx in range(0, self.number_of_frames):
                dummy_tile_map.append(TilemapEntry(
                    idx=frame_idx * self.number_of_images + tile_idx,
                    pal_idx=0,
                    flip_x=False,
                    flip_y=False
                ))
        width = width_in_tiles * BPA_TILE_DIM
        height = math.ceil(etr / width_in_tiles) * BPA_TILE_DIM

        return to_pil(
            dummy_tile_map, self.tiles, [palette], BPA_TILE_DIM, width, height
        )

    def tiles_for_frame(self, frame):
        """Returns the tiles for the specified frame. Strips the empty dummy tile image at the beginning."""
        return self.tiles[frame * self.number_of_images:]