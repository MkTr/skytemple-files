#  Copyright 2020 Parakoopa
#
#  This file is part of SkyTemple.
#
#  SkyTemple is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SkyTemple is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SkyTemple.  If not, see <https://www.gnu.org/licenses/>.

from enum import Enum

class FontType(Enum):
    FONT_DAT = 0x00
    FONT_SIR0 = 0x01

FONT_ENTRY_LEN = 0x1C
FONT_DEFAULT_BPROW = 2

FONT_SIR0_DATA_LEN = 72
FONT_SIR0_ENTRY_LEN = 0xC
FONT_DEFAULT_CAT = 0x02
FONT_DEFAULT_PADDING = 0xFF

FONT_VALID_TABLES = [0x00, 0x81, 0x82, 0x83, 0x84, 0x87]

XML_FONT = "Font"
XML_TABLE = "Table"
XML_TABLE__ID = "tableid"
XML_CHAR = "Char"
XML_CHAR__ID = "id"
XML_CHAR__WIDTH = "width"
XML_CHAR__BPROW = "bprow"
XML_CHAR__CAT = "category"
XML_CHAR__PADDING = "padding"
