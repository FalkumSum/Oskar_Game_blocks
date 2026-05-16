import asyncio
import math
import os
import random
import sys
try:
    import sqlite3
except ImportError:
    sqlite3 = None
from dataclasses import dataclass
from typing import List, Tuple

import pygame


Vec3 = Tuple[int, int, int]
IS_WEB = sys.platform == "emscripten"


# Board dimensions: x (width), y (height), z (depth)
BOARD_W = 5
BOARD_H = 14
BOARD_D = 5

SCREEN_W = 1100
SCREEN_H = 1100
FPS = 10

BG_COLOR = (14, 20, 28)
GRID_COLOR = (40, 50, 64)
TEXT_COLOR = (228, 236, 248)
AXIS_X_COLOR = (255, 110, 110)
AXIS_Z_COLOR = (116, 182, 255)
ACTIVE_EDGE_COLOR = (255, 245, 210)
FLOOR_NEAR_COLOR = (64, 84, 110)
FLOOR_FAR_COLOR = (28, 38, 52)

CUBE_W = 30
CUBE_H = 15
CUBE_Y = 30
DEPTH_FAR_SCALE = 0.76
DEPTH_NEAR_SCALE = 1.08

ORIGIN_X = 360
ORIGIN_Y = 610

DROP_BASE_MS = 850
MIN_DROP_MS = 170


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _compute_letterbox(target_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    tw, th = target_size
    if tw <= 0 or th <= 0:
        return 0, 0, SCREEN_W, SCREEN_H
    scale = min(tw / SCREEN_W, th / SCREEN_H)
    sw = max(1, int(SCREEN_W * scale))
    sh = max(1, int(SCREEN_H * scale))
    ox = (tw - sw) // 2
    oy = (th - sh) // 2
    return ox, oy, sw, sh


def present_scaled(canvas: pygame.Surface, target: pygame.Surface) -> None:
    tw, th = target.get_size()
    if (tw, th) == (SCREEN_W, SCREEN_H):
        target.blit(canvas, (0, 0))
    else:
        ox, oy, sw, sh = _compute_letterbox((tw, th))
        target.fill(BG_COLOR)
        scaled = pygame.transform.smoothscale(canvas, (sw, sh))
        target.blit(scaled, (ox, oy))
    pygame.display.flip()


def window_to_canvas(pos: Tuple[int, int], target: pygame.Surface) -> Tuple[int, int]:
    ox, oy, sw, sh = _compute_letterbox(target.get_size())
    px, py = pos
    if sw <= 0 or sh <= 0:
        return px, py
    cx = (px - ox) * SCREEN_W / sw
    cy = (py - oy) * SCREEN_H / sh
    return int(clamp(int(cx), 0, SCREEN_W - 1)), int(clamp(int(cy), 0, SCREEN_H - 1))


def brighten(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return tuple(clamp(int(c * factor), 0, 255) for c in color)


def project_iso(x: int, y: int, z: int) -> Tuple[int, int]:
    sx = ORIGIN_X + (x - z) * CUBE_W
    sy = ORIGIN_Y + (x + z) * CUBE_H - y * CUBE_Y
    return sx, sy


def depth_scale(x: int, z: int) -> float:
    # Small x/z are farther in this isometric view; large x/z are nearer.
    denom = max(1, (BOARD_W - 1) + (BOARD_D - 1))
    t = (x + z) / denom
    return DEPTH_FAR_SCALE + (DEPTH_NEAR_SCALE - DEPTH_FAR_SCALE) * t


def rotate_x(v: Vec3) -> Vec3:
    x, y, z = v
    return x, -z, y


def rotate_y(v: Vec3) -> Vec3:
    x, y, z = v
    return z, y, -x


def rotate_z(v: Vec3) -> Vec3:
    x, y, z = v
    return -y, x, z


def normalize_cells(cells: List[Vec3]) -> List[Vec3]:
    min_x = min(c[0] for c in cells)
    min_y = min(c[1] for c in cells)
    min_z = min(c[2] for c in cells)
    shifted = [(x - min_x, y - min_y, z - min_z) for x, y, z in cells]
    shifted.sort()
    return shifted


PIECE_SHAPES: List[List[Vec3]] = [
    # I-X (4 wide on X)
    [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
    # O
    [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)],
    # T
    [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0)],
    # L
    [(0, 0, 0), (0, 1, 0), (0, 2, 0), (1, 0, 0)],
    # S
    [(0, 0, 0), (1, 0, 0), (1, 0, 1), (2, 0, 1)],
    # Corner
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
    # Pillar bent
    [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 2, 1)],
    # Zig corner
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1)],
]

# Easy mode: 1D pieces only — straight lines along each axis.
EASY_SHAPES: List[List[Vec3]] = [
    # 1-long (single cube)
    [(0, 0, 0)],
    # 2 along X
    [(0, 0, 0), (1, 0, 0)],
    # 2 along Z
    [(0, 0, 0), (0, 0, 1)],
    # 2 along Y
    [(0, 0, 0), (0, 1, 0)],
    # 3 along X
    [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
    # 3 along Z
    [(0, 0, 0), (0, 0, 1), (0, 0, 2)],
    # 3 along Y
    [(0, 0, 0), (0, 1, 0), (0, 2, 0)],
    # 4 along X
    [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
    # 4 along Z
    [(0, 0, 0), (0, 0, 1), (0, 0, 2), (0, 0, 3)],
    # 4 along Y
    [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)],
]

EASY_COLORS: List[Tuple[int, int, int]] = [
    (180, 220, 255),
    (67, 220, 255),
    (116, 182, 255),
    (95, 255, 151),
    (255, 215, 88),
    (255, 175, 70),
    (186, 109, 255),
    (255, 92, 120),
    (255, 122, 204),
    (124, 196, 255),
]

PIECE_COLORS: List[Tuple[int, int, int]] = [
    (67, 220, 255),
    (255, 215, 88),
    (186, 109, 255),
    (255, 146, 77),
    (95, 255, 151),
    (255, 92, 120),
    (124, 196, 255),
    (255, 122, 204),
]


@dataclass
class Piece:
    cells: List[Vec3]
    color: Tuple[int, int, int]
    pos: Vec3

    def absolute_cells(self) -> List[Vec3]:
        px, py, pz = self.pos
        return [(px + x, py + y, pz + z) for x, y, z in self.cells]

    def rotated(self, axis: str) -> "Piece":
        if axis == "x":
            rcells = [rotate_x(c) for c in self.cells]
        elif axis == "y":
            rcells = [rotate_y(c) for c in self.cells]
        else:
            rcells = [rotate_z(c) for c in self.cells]
        return Piece(normalize_cells(rcells), self.color, self.pos)


class Game3DTetris:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 easy_mode: bool = False, fullscreen: bool = False) -> None:
        pygame.display.set_caption("3D Tetris - Pygame")
        self.fullscreen = fullscreen
        self.display = screen
        self.screen = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        self.clock = clock
        self.font = pygame.font.SysFont("consolas", 24)
        self.small_font = pygame.font.SysFont("consolas", 18)
        self.big_font = pygame.font.SysFont("consolas", 46, bold=True)

        self.easy_mode = easy_mode
        self.grid: dict[Vec3, Tuple[int, int, int]] = {}
        self.score = 0
        self.lines = 0
        self.level = 1
        self.paused = False
        self.game_over = False
        self._score_saved = False

        self.bag: List[int] = []
        self.current = self.new_piece()
        self.next_piece = self.new_piece()

        self.camera_mode = 0
        self.camera_names = ["Front", "Right", "Back", "Left", "Top"]

        self.drop_timer = 0
        self.drop_interval = DROP_BASE_MS

        # Key-repeat state for held movement keys.
        # Maps pygame key constant -> ms held (None = not held).
        self._move_keys = {
            pygame.K_LEFT:  ((-1, 0, 0), 0),
            pygame.K_RIGHT: ((1,  0, 0), 0),
            pygame.K_UP:    ((0,  0,-1), 0),
            pygame.K_DOWN:  ((0,  0, 1), 0),
        }
        self._held: dict[int, int] = {}  # key -> ms held
        self._MOVE_DELAY = 180   # ms before repeat starts
        self._MOVE_REPEAT = 60   # ms between repeats

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        flags = pygame.FULLSCREEN | pygame.SCALED if self.fullscreen else pygame.RESIZABLE
        self.display = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)

    def to_view_coords(self, x: int, y: int, z: int) -> Vec3:
        # Rotates board around Y axis in 90 degree steps for camera views.
        if self.camera_mode == 0:
            return x, y, z
        if self.camera_mode == 1:
            return z, y, BOARD_W - 1 - x
        if self.camera_mode == 2:
            return BOARD_W - 1 - x, y, BOARD_D - 1 - z
        if self.camera_mode == 3:
            return BOARD_D - 1 - z, y, x
        return x, y, z

    def cycle_camera(self) -> None:
        self.camera_mode = (self.camera_mode + 1) % len(self.camera_names)

    def piece_spawn(self, cells: List[Vec3]) -> Vec3:
        max_x = max(c[0] for c in cells)
        max_y = max(c[1] for c in cells)
        max_z = max(c[2] for c in cells)
        sx = (BOARD_W - (max_x + 1)) // 2
        sy = BOARD_H - (max_y + 1)
        sz = (BOARD_D - (max_z + 1)) // 2
        return sx, sy, sz

    def refill_bag(self) -> None:
        shapes = EASY_SHAPES if self.easy_mode else PIECE_SHAPES
        self.bag = list(range(len(shapes)))
        random.shuffle(self.bag)

    def new_piece(self) -> Piece:
        if not self.bag:
            self.refill_bag()
        idx = self.bag.pop()
        if self.easy_mode:
            cells = normalize_cells(EASY_SHAPES[idx])
            color = EASY_COLORS[idx]
        else:
            cells = normalize_cells(PIECE_SHAPES[idx])
            color = PIECE_COLORS[idx]
        return Piece(cells, color, self.piece_spawn(cells))

    def is_valid(self, piece: Piece) -> bool:
        for x, y, z in piece.absolute_cells():
            if x < 0 or x >= BOARD_W or z < 0 or z >= BOARD_D or y < 0:
                return False
            if (x, y, z) in self.grid:
                return False
        return True

    def try_move(self, dx: int, dy: int, dz: int) -> bool:
        moved = Piece(self.current.cells[:], self.current.color, (self.current.pos[0] + dx, self.current.pos[1] + dy, self.current.pos[2] + dz))
        if self.is_valid(moved):
            self.current = moved
            return True
        return False

    def try_rotate(self, axis: str) -> None:
        rotated = self.current.rotated(axis)

        # Try simple wall-kicks to keep controls responsive near boundaries.
        kicks = [
            (0, 0, 0),
            (1, 0, 0),
            (-1, 0, 0),
            (0, 0, 1),
            (0, 0, -1),
            (1, 0, 1),
            (-1, 0, -1),
            (1, 0, -1),
            (-1, 0, 1),
            (0, 1, 0),
        ]
        for kx, ky, kz in kicks:
            candidate = Piece(rotated.cells, rotated.color, (rotated.pos[0] + kx, rotated.pos[1] + ky, rotated.pos[2] + kz))
            if self.is_valid(candidate):
                self.current = candidate
                return

    def lock_piece(self) -> None:
        for cell in self.current.absolute_cells():
            self.grid[cell] = self.current.color

        cleared = self.clear_full_planes()
        if cleared:
            self.lines += cleared
            self.score += [0, 120, 300, 520, 800][cleared] * self.level
            self.level = 1 + self.lines // 6
            # Speed up every cleared layer, not just every 6.
            self.drop_interval = max(MIN_DROP_MS, DROP_BASE_MS - self.lines * 28)

        self.current = self.next_piece
        self.next_piece = self.new_piece()

        if not self.is_valid(self.current):
            self.game_over = True

    def clear_full_planes(self) -> int:
        removed = 0
        y = 0
        while y < BOARD_H:
            is_full = True
            for x in range(BOARD_W):
                for z in range(BOARD_D):
                    if (x, y, z) not in self.grid:
                        is_full = False
                        break
                if not is_full:
                    break

            if not is_full:
                y += 1
                continue

            removed += 1
            new_grid: dict[Vec3, Tuple[int, int, int]] = {}
            for (gx, gy, gz), color in self.grid.items():
                if gy == y:
                    continue
                if gy > y:
                    new_grid[(gx, gy - 1, gz)] = color
                else:
                    new_grid[(gx, gy, gz)] = color
            self.grid = new_grid

        return removed

    def ghost_cells(self) -> List[Vec3]:
        """Return the absolute cells of the current piece at its hard-drop position."""
        test = Piece(self.current.cells[:], self.current.color, self.current.pos)
        while True:
            nx, ny, nz = test.pos[0], test.pos[1] - 1, test.pos[2]
            candidate = Piece(test.cells, test.color, (nx, ny, nz))
            if self.is_valid(candidate):
                test = candidate
            else:
                break
        return test.absolute_cells()

    def hard_drop(self) -> None:
        while self.try_move(0, -1, 0):
            self.score += 1
        self.lock_piece()

    def update(self, dt_ms: int) -> None:
        if self.paused or self.game_over:
            return

        # Held-key movement repeat.
        keys = pygame.key.get_pressed()
        for key, (delta, _) in self._move_keys.items():
            if keys[key]:
                prev = self._held.get(key, 0)
                self._held[key] = prev + dt_ms
                # Fire on first press immediately (prev==0), then after delay+repeat.
                if prev == 0 or (prev < self._MOVE_DELAY and self._held[key] >= self._MOVE_DELAY) or \
                        (prev >= self._MOVE_DELAY and
                         (prev - self._MOVE_DELAY) // self._MOVE_REPEAT < (self._held[key] - self._MOVE_DELAY) // self._MOVE_REPEAT):
                    self.try_move(*delta)
            else:
                self._held.pop(key, None)

        self.drop_timer += dt_ms
        if self.drop_timer >= self.drop_interval:
            self.drop_timer = 0
            if not self.try_move(0, -1, 0):
                self.lock_piece()

    def draw_cube(
        self,
        x: int,
        y: int,
        z: int,
        color: Tuple[int, int, int],
        active: bool = False,
        show_top: bool = True,
        show_left: bool = True,
        show_right: bool = True,
    ) -> None:
        sx, sy = project_iso(x, y, z)
        scale = depth_scale(x, z)
        t = (scale - DEPTH_FAR_SCALE) / max(0.001, (DEPTH_NEAR_SCALE - DEPTH_FAR_SCALE))
        top_factor = 0.98 + 0.28 * t
        left_factor = 0.72 + 0.22 * t
        right_factor = 0.58 + 0.18 * t

        top = [
            (sx, sy - CUBE_Y),
            (sx + CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx - CUBE_W, sy - CUBE_Y + CUBE_H),
        ]
        left = [
            (sx - CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx, sy + CUBE_H * 2),
            (sx - CUBE_W, sy + CUBE_H),
        ]
        right = [
            (sx + CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx, sy + CUBE_H * 2),
            (sx + CUBE_W, sy + CUBE_H),
        ]

        if show_top:
            pygame.draw.polygon(self.screen, brighten(color, top_factor), top)
        if show_left:
            pygame.draw.polygon(self.screen, brighten(color, left_factor), left)
        if show_right:
            pygame.draw.polygon(self.screen, brighten(color, right_factor), right)

        edge_color = ACTIVE_EDGE_COLOR if active else (8, 10, 16)
        edge_width = 2 if active else 1
        if show_top:
            pygame.draw.polygon(self.screen, edge_color, top, edge_width)
        if show_left:
            pygame.draw.polygon(self.screen, edge_color, left, edge_width)
        if show_right:
            pygame.draw.polygon(self.screen, edge_color, right, edge_width)

        # Orientation cues on the top face: red points toward +X, blue toward +Z.
        if show_top:
            top_anchor = top[0]
            x_tip = top[1]
            z_tip = top[3]
            pygame.draw.line(self.screen, AXIS_X_COLOR, top_anchor, x_tip, 2)
            pygame.draw.line(self.screen, AXIS_Z_COLOR, top_anchor, z_tip, 2)
            dot = 3
            pygame.draw.circle(self.screen, AXIS_X_COLOR, x_tip, dot)
            pygame.draw.circle(self.screen, AXIS_Z_COLOR, z_tip, dot)

    def draw_well_outline(self) -> None:
        corners = [
            (0, 0, 0),
            (BOARD_W, 0, 0),
            (BOARD_W, 0, BOARD_D),
            (0, 0, BOARD_D),
            (0, BOARD_H, 0),
            (BOARD_W, BOARD_H, 0),
            (BOARD_W, BOARD_H, BOARD_D),
            (0, BOARD_H, BOARD_D),
        ]

        def project_world_corner(cx: int, cy: int, cz: int) -> Tuple[int, int]:
            if self.camera_mode == 0:
                vx, vy, vz = cx, cy, cz
            elif self.camera_mode == 1:
                vx, vy, vz = cz, cy, BOARD_W - cx
            elif self.camera_mode == 2:
                vx, vy, vz = BOARD_W - cx, cy, BOARD_D - cz
            else:
                vx, vy, vz = BOARD_D - cz, cy, cx
            return project_iso(vx, vy, vz)

        pts = [project_world_corner(*c) for c in corners]
        edges = [
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (0, 4),
            (1, 5),
            (2, 6),
            (3, 7),
        ]

        for a, b in edges:
            ax, ay = pts[a]
            bx, by = pts[b]
            pygame.draw.line(self.screen, GRID_COLOR, (ax, ay), (bx, by), 1)

        # Depth floor: fixed geometry (no seams) + depth-based shading.
        floor_tiles = []
        for z in range(BOARD_D):
            for x in range(BOARD_W):
                vx, vy, vz = self.to_view_coords(x, 0, z)
                sx, sy = project_iso(vx, vy, vz)
                scale = depth_scale(vx, vz)
                t = (scale - DEPTH_FAR_SCALE) / max(0.001, (DEPTH_NEAR_SCALE - DEPTH_FAR_SCALE))
                floor_tiles.append((vx + vz, x, z, sx, sy, t))

        floor_tiles.sort(key=lambda item: item[0])

        for _, x, z, sx, sy, t in floor_tiles:
            tile = [
                (sx, sy),
                (sx + CUBE_W, sy + CUBE_H),
                (sx, sy + CUBE_H * 2),
                (sx - CUBE_W, sy + CUBE_H),
            ]

            base = tuple(
                int(FLOOR_FAR_COLOR[i] + (FLOOR_NEAR_COLOR[i] - FLOOR_FAR_COLOR[i]) * t)
                for i in range(3)
            )
            checker = 1.08 if (x + z) % 2 == 0 else 0.94
            fill = brighten(base, checker)
            edge = brighten((26, 34, 46), 0.9 + 0.35 * t)

            pygame.draw.polygon(self.screen, fill, tile)
            pygame.draw.polygon(self.screen, edge, tile, 1)

    def draw_top_view(self) -> None:
        cell = 68
        grid_w = BOARD_W * cell
        grid_h = BOARD_D * cell
        ox = (SCREEN_W - grid_w) // 2 - 120
        oy = 140

        pygame.draw.rect(self.screen, (18, 26, 36), (ox - 18, oy - 18, grid_w + 36, grid_h + 36), border_radius=12)
        pygame.draw.rect(self.screen, (50, 66, 86), (ox - 18, oy - 18, grid_w + 36, grid_h + 36), 2, border_radius=12)

        stacks: dict[Tuple[int, int], Tuple[int, Tuple[int, int, int], bool]] = {}
        for (x, y, z), color in self.grid.items():
            key = (x, z)
            prev = stacks.get(key)
            if prev is None or y > prev[0]:
                stacks[key] = (y, color, False)

        for x, y, z in self.current.absolute_cells():
            key = (x, z)
            prev = stacks.get(key)
            if prev is None or y >= prev[0]:
                stacks[key] = (y, self.current.color, True)

        for z in range(BOARD_D):
            for x in range(BOARD_W):
                rx = ox + x * cell
                ry = oy + z * cell
                pygame.draw.rect(self.screen, (28, 36, 48), (rx, ry, cell, cell))
                pygame.draw.rect(self.screen, (48, 58, 74), (rx, ry, cell, cell), 1)

                top = stacks.get((x, z))
                if top is None:
                    continue

                y, color, active = top
                shade = 0.78 + (0.34 * (y / max(1, BOARD_H - 1)))
                fill = brighten(color, shade)
                inner = pygame.Rect(rx + 5, ry + 5, cell - 10, cell - 10)
                pygame.draw.rect(self.screen, fill, inner, border_radius=8)
                edge = ACTIVE_EDGE_COLOR if active else (12, 16, 24)
                width = 3 if active else 2
                pygame.draw.rect(self.screen, edge, inner, width, border_radius=8)
                htxt = self.small_font.render(str(y), True, (10, 14, 20))
                self.screen.blit(htxt, (rx + 9, ry + 7))

        title = self.font.render("TOP VIEW", True, TEXT_COLOR)
        self.screen.blit(title, (ox, oy - 52))

    def draw_next_preview(self) -> None:
        panel_x = 760
        panel_y = 150
        pygame.draw.rect(self.screen, (22, 30, 42), (panel_x, panel_y, 280, 260), border_radius=10)
        pygame.draw.rect(self.screen, (46, 60, 78), (panel_x, panel_y, 280, 260), 2, border_radius=10)

        title = self.font.render("NEXT", True, TEXT_COLOR)
        self.screen.blit(title, (panel_x + 12, panel_y + 10))

        base_x = panel_x + 130
        base_y = panel_y + 215
        for bx, by, bz in sorted(self.next_piece.cells, key=lambda c: (c[0] + c[2], c[1])):
            sx = base_x + (bx - bz) * 18
            sy = base_y + (bx + bz) * 9 - by * 18
            self.draw_preview_cube(sx, sy, self.next_piece.color)

    def draw_preview_cube(self, sx: int, sy: int, color: Tuple[int, int, int]) -> None:
        w = 18
        h = 9
        y = 18
        top = [(sx, sy - y), (sx + w, sy - y + h), (sx, sy - y + 2 * h), (sx - w, sy - y + h)]
        left = [(sx - w, sy - y + h), (sx, sy - y + 2 * h), (sx, sy + 2 * h), (sx - w, sy + h)]
        right = [(sx + w, sy - y + h), (sx, sy - y + 2 * h), (sx, sy + 2 * h), (sx + w, sy + h)]

        pygame.draw.polygon(self.screen, brighten(color, 1.15), top)
        pygame.draw.polygon(self.screen, brighten(color, 0.82), left)
        pygame.draw.polygon(self.screen, brighten(color, 0.65), right)
        pygame.draw.polygon(self.screen, (12, 16, 24), top, 1)
        pygame.draw.polygon(self.screen, (12, 16, 24), left, 1)
        pygame.draw.polygon(self.screen, (12, 16, 24), right, 1)
        pygame.draw.line(self.screen, AXIS_X_COLOR, top[0], top[1], 2)
        pygame.draw.line(self.screen, AXIS_Z_COLOR, top[0], top[3], 2)

    def draw_hud(self) -> None:
        panel_x = 760
        panel_y = 420
        pygame.draw.rect(self.screen, (22, 30, 42), (panel_x, panel_y, 280, 226), border_radius=10)
        pygame.draw.rect(self.screen, (46, 60, 78), (panel_x, panel_y, 280, 226), 2, border_radius=10)

        mode_label = "EASY" if self.easy_mode else "NORMAL"
        lines = [
            f"Score: {self.score}",
            f"Planes: {self.lines}",
            f"Level: {self.level}",
            f"Mode: {mode_label}  M=switch",
            f"Cam: {self.camera_names[self.camera_mode]}  C",
            "Move: Arrows",
            "Rot X:W/S  Y:Q/E  Z:A/D",
            "Drop: Space  Pause: P",
            f"F11: Fullscreen ({'ON' if self.fullscreen else 'OFF'})",
        ]

        for i, line in enumerate(lines):
            text = self.font.render(line, True, TEXT_COLOR)
            self.screen.blit(text, (panel_x + 14, panel_y + 14 + i * 22))

        if self.paused and not self.game_over:
            overlay = self.big_font.render("PAUSED", True, (255, 232, 155))
            self.screen.blit(overlay, (430, 40))

        if self.game_over:
            overlay = self.big_font.render("GAME OVER", True, (255, 130, 130))
            self.screen.blit(overlay, (380, 40))
            restart = self.font.render("Press R to restart  |  L: Leaderboard", True, TEXT_COLOR)
            self.screen.blit(restart, (360, 96))

    def draw_minimaps(self) -> None:
        panel_x = 760
        panel_y = 648
        panel_w = 280
        panel_h = 440
        pygame.draw.rect(self.screen, (22, 30, 42), (panel_x, panel_y, panel_w, panel_h), border_radius=10)
        pygame.draw.rect(self.screen, (46, 60, 78), (panel_x, panel_y, panel_w, panel_h), 2, border_radius=10)
        title = self.font.render("MINI MAPS", True, TEXT_COLOR)
        self.screen.blit(title, (panel_x + 12, panel_y + 8))

        # Cell sizes chosen so everything fits: top 7×13, front/side 14×13 stacked.
        top_cell = 13
        front_cell = 13
        side_cell = 13

        top_origin = (panel_x + 12, panel_y + 44)
        # top section height: 7*13=91, gap 10, label 18 → front starts at 44+91+10+18=163
        front_origin = (panel_x + 12, panel_y + 163)
        side_origin = (panel_x + 12 + BOARD_W * front_cell + 10, panel_y + 163)

        top_map: dict[Tuple[int, int], Tuple[int, bool, Tuple[int, int, int]]] = {}
        for (x, y, z), color in self.grid.items():
            key = (x, z)
            prev = top_map.get(key)
            if prev is None or y > prev[0]:
                top_map[key] = (y, False, color)
        for x, y, z in self.current.absolute_cells():
            key = (x, z)
            prev = top_map.get(key)
            if prev is None or y >= prev[0]:
                top_map[key] = (y, True, self.current.color)

        for z in range(BOARD_D):
            for x in range(BOARD_W):
                rx = top_origin[0] + x * top_cell
                ry = top_origin[1] + z * top_cell
                pygame.draw.rect(self.screen, (28, 36, 48), (rx, ry, top_cell, top_cell))
                pygame.draw.rect(self.screen, (52, 62, 76), (rx, ry, top_cell, top_cell), 1)
                cell_data = top_map.get((x, z))
                if cell_data is None:
                    continue
                y, active, color = cell_data
                shade = 0.72 + (0.35 * (y / max(1, BOARD_H - 1)))
                fill = brighten(color, shade)
                inner = pygame.Rect(rx + 2, ry + 2, top_cell - 4, top_cell - 4)
                pygame.draw.rect(self.screen, fill, inner, border_radius=3)
                edge = ACTIVE_EDGE_COLOR if active else (12, 16, 24)
                pygame.draw.rect(self.screen, edge, inner, 2, border_radius=3)

        front_map: dict[Tuple[int, int], Tuple[bool, Tuple[int, int, int]]] = {}
        for (x, y, z), color in self.grid.items():
            key = (x, y)
            prev = front_map.get(key)
            if prev is None:
                front_map[key] = (False, color)
        for x, y, z in self.current.absolute_cells():
            front_map[(x, y)] = (True, self.current.color)

        for y in range(BOARD_H):
            for x in range(BOARD_W):
                rx = front_origin[0] + x * front_cell
                ry = front_origin[1] + (BOARD_H - 1 - y) * front_cell
                pygame.draw.rect(self.screen, (28, 36, 48), (rx, ry, front_cell, front_cell))
                pygame.draw.rect(self.screen, (52, 62, 76), (rx, ry, front_cell, front_cell), 1)
                cell_data = front_map.get((x, y))
                if cell_data is None:
                    continue
                active, color = cell_data
                fill = brighten(color, 0.9 if active else 0.75)
                inner = pygame.Rect(rx + 2, ry + 2, front_cell - 4, front_cell - 4)
                pygame.draw.rect(self.screen, fill, inner, border_radius=3)
                edge = ACTIVE_EDGE_COLOR if active else (12, 16, 24)
                pygame.draw.rect(self.screen, edge, inner, 2, border_radius=3)

        side_map: dict[Tuple[int, int], Tuple[bool, Tuple[int, int, int]]] = {}
        for (x, y, z), color in self.grid.items():
            key = (z, y)
            prev = side_map.get(key)
            if prev is None:
                side_map[key] = (False, color)
        for x, y, z in self.current.absolute_cells():
            side_map[(z, y)] = (True, self.current.color)

        for y in range(BOARD_H):
            for z in range(BOARD_D):
                rx = side_origin[0] + z * side_cell
                ry = side_origin[1] + (BOARD_H - 1 - y) * side_cell
                pygame.draw.rect(self.screen, (28, 36, 48), (rx, ry, side_cell, side_cell))
                pygame.draw.rect(self.screen, (52, 62, 76), (rx, ry, side_cell, side_cell), 1)
                cell_data = side_map.get((z, y))
                if cell_data is None:
                    continue
                active, color = cell_data
                fill = brighten(color, 0.9 if active else 0.75)
                inner = pygame.Rect(rx + 2, ry + 2, side_cell - 4, side_cell - 4)
                pygame.draw.rect(self.screen, fill, inner, border_radius=3)
                edge = ACTIVE_EDGE_COLOR if active else (12, 16, 24)
                pygame.draw.rect(self.screen, edge, inner, 2, border_radius=3)

        top_lbl = self.small_font.render("Top (X/Z)", True, TEXT_COLOR)
        front_lbl = self.small_font.render("Front", True, TEXT_COLOR)
        side_lbl = self.small_font.render("Side", True, TEXT_COLOR)
        self.screen.blit(top_lbl, (top_origin[0], top_origin[1] - 18))
        self.screen.blit(front_lbl, (front_origin[0], front_origin[1] - 18))
        self.screen.blit(side_lbl, (side_origin[0], side_origin[1] - 18))

    def draw_ghost_cube(self, x: int, y: int, z: int, color: Tuple[int, int, int]) -> None:
        sx, sy = project_iso(x, y, z)
        top = [
            (sx, sy - CUBE_Y),
            (sx + CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx - CUBE_W, sy - CUBE_Y + CUBE_H),
        ]
        left = [
            (sx - CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx, sy + CUBE_H * 2),
            (sx - CUBE_W, sy + CUBE_H),
        ]
        right = [
            (sx + CUBE_W, sy - CUBE_Y + CUBE_H),
            (sx, sy - CUBE_Y + CUBE_H * 2),
            (sx, sy + CUBE_H * 2),
            (sx + CUBE_W, sy + CUBE_H),
        ]
        ghost_edge = brighten(color, 1.6)
        for face in (top, left, right):
            pygame.draw.polygon(self.screen, ghost_edge, face, 3)

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)

        if self.camera_mode == 4:
            self.draw_top_view()
            self.draw_next_preview()
            self.draw_hud()
            self.draw_minimaps()
            present_scaled(self.screen, self.display)
            return

        self.draw_well_outline()

        ghost_cells = set(self.ghost_cells()) - set(self.current.absolute_cells())

        # Build solid + ghost draw lists separately for clean face-cull.
        solid_cells: List[Tuple[int, int, int, Tuple, bool]] = []
        for (x, y, z), color in self.grid.items():
            vx, vy, vz = self.to_view_coords(x, y, z)
            solid_cells.append((vx, vy, vz, color, False))
        for x, y, z in self.current.absolute_cells():
            vx, vy, vz = self.to_view_coords(x, y, z)
            solid_cells.append((vx, vy, vz, self.current.color, True))

        solid_cells.sort(key=lambda c: (c[0] + c[2], -c[1]))
        occupied = {(x, y, z) for x, y, z, _, _ in solid_cells}

        ghost_draw = []
        for x, y, z in ghost_cells:
            vx, vy, vz = self.to_view_coords(x, y, z)
            ghost_draw.append((vx, vy, vz))
        ghost_draw.sort(key=lambda c: (c[0] + c[2], -c[1]))

        for x, y, z, color, active in solid_cells:
            show_top = (x, y + 1, z) not in occupied
            show_right = (x + 1, y, z) not in occupied
            show_left = (x, y, z + 1) not in occupied
            self.draw_cube(x, y, z, color, active, show_top, show_left, show_right)

        for x, y, z in ghost_draw:
            self.draw_ghost_cube(x, y, z, self.current.color)

        self.draw_next_preview()
        self.draw_hud()
        self.draw_minimaps()

        present_scaled(self.screen, self.display)

    def restart(self, toggle_mode: bool = False) -> None:
        if toggle_mode:
            self.easy_mode = not self.easy_mode
        self.grid.clear()
        self.score = 0
        self.lines = 0
        self.level = 1
        self.drop_interval = DROP_BASE_MS
        self.drop_timer = 0
        self.paused = False
        self.game_over = False
        self._score_saved = False
        self.bag.clear()
        self.current = self.new_piece()
        self.next_piece = self.new_piece()

    async def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                    w = max(800, event.w)
                    h = max(700, event.h)
                    self.display = pygame.display.set_mode((w, h), pygame.RESIZABLE)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_F11:
                        self.toggle_fullscreen()
                    elif event.key == pygame.K_p and not self.game_over:
                        self.paused = not self.paused
                    elif event.key == pygame.K_c:
                        self.cycle_camera()
                    elif event.key == pygame.K_r and self.game_over:
                        self.restart()
                    elif event.key == pygame.K_l and self.game_over:
                        mode_str = "Easy" if self.easy_mode else "Normal"
                        if not self._score_saved:
                            await show_name_entry(self.display, self.clock, self.score, self.lines, self.level, mode_str)
                            self._score_saved = True
                        await show_leaderboard(self.display, self.clock)
                        self.display = pygame.display.get_surface() or self.display
                    elif event.key == pygame.K_m:
                        self.restart(toggle_mode=True)
                    elif self.paused and not self.game_over:
                        if event.key == pygame.K_q:
                            self.try_rotate("y")
                        elif event.key == pygame.K_e:
                            self.try_rotate("y")
                        elif event.key == pygame.K_w:
                            self.try_rotate("x")
                        elif event.key == pygame.K_s:
                            self.try_rotate("x")
                        elif event.key == pygame.K_a:
                            self.try_rotate("z")
                        elif event.key == pygame.K_d:
                            self.try_rotate("z")
                        continue
                    elif self.paused or self.game_over:
                        continue
                    elif event.key == pygame.K_SPACE:
                        self.hard_drop()
                    elif event.key == pygame.K_q:
                        self.try_rotate("y")
                    elif event.key == pygame.K_e:
                        self.try_rotate("y")
                    elif event.key == pygame.K_w:
                        self.try_rotate("x")
                    elif event.key == pygame.K_s:
                        self.try_rotate("x")
                    elif event.key == pygame.K_a:
                        self.try_rotate("z")
                    elif event.key == pygame.K_d:
                        self.try_rotate("z")

            self.update(dt)
            self.draw()
            await asyncio.sleep(0)


async def show_start_screen(screen: pygame.Surface, clock: pygame.time.Clock,
                            fullscreen: bool) -> tuple[str, pygame.Surface, bool]:
    """Show the main menu and return: normal, easy, or quit."""
    pygame.display.set_caption("3D Tetris - Main Menu")
    font_big = pygame.font.SysFont("consolas", 54, bold=True)
    font_med = pygame.font.SysFont("consolas", 32)
    font_sm = pygame.font.SysFont("consolas", 22)

    def apply_menu_mode() -> pygame.Surface:
        flags = pygame.FULLSCREEN | pygame.SCALED if fullscreen else pygame.RESIZABLE
        return pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)

    selected = 0
    options = [
        ("1  Play Normal", "Classic 3D pieces", "normal"),
        ("2  Play Easy", "Straight line pieces only", "easy"),
        ("3  Leaderboard", "View Easy and Normal rankings", "leaderboard"),
        ("4  Quit", "Exit game", "quit"),
    ]

    while True:
        canvas = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        canvas.fill(BG_COLOR)

        title = font_big.render("3D TETRIS", True, (200, 230, 255))
        canvas.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 130))

        subtitle = font_sm.render("Main Menu", True, (120, 145, 170))
        canvas.blit(subtitle, (SCREEN_W // 2 - subtitle.get_width() // 2, 208))

        for i, (label, desc, _action) in enumerate(options):
            y = 280 + i * 120
            is_sel = selected == i
            bg = (38, 58, 82) if is_sel else (22, 30, 42)
            border = (100, 160, 220) if is_sel else (46, 60, 78)
            pygame.draw.rect(canvas, bg, (280, y, 540, 92), border_radius=14)
            pygame.draw.rect(canvas, border, (280, y, 540, 92), 3, border_radius=14)
            lbl_surf = font_med.render(label, True, (240, 248, 255) if is_sel else (170, 195, 220))
            desc_surf = font_sm.render(desc, True, (140, 168, 196))
            canvas.blit(lbl_surf, (310, y + 10))
            canvas.blit(desc_surf, (310, y + 52))

        hint = font_sm.render("Arrow/mouse: choose   Enter: confirm   F11: fullscreen", True, (80, 105, 130))
        canvas.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, 810))

        present_scaled(canvas, screen)
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit", screen, fullscreen
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                w = max(800, event.w)
                h = max(700, event.h)
                screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    selected = (selected - 1) % len(options)
                elif event.key == pygame.K_DOWN:
                    selected = (selected + 1) % len(options)
                elif event.key == pygame.K_F11:
                    fullscreen = not fullscreen
                    screen = apply_menu_mode()
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    action = options[selected][2]
                    if action == "leaderboard":
                        await show_leaderboard(screen, clock)
                    else:
                        return action, screen, fullscreen
                elif event.key == pygame.K_1:
                    return "normal", screen, fullscreen
                elif event.key == pygame.K_2:
                    return "easy", screen, fullscreen
                elif event.key == pygame.K_3:
                    await show_leaderboard(screen, clock)
                elif event.key == pygame.K_4:
                    return "quit", screen, fullscreen
                elif event.key == pygame.K_ESCAPE:
                    return "quit", screen, fullscreen
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = window_to_canvas(event.pos, screen)
                for i, (_, _, action) in enumerate(options):
                    y = 280 + i * 120
                    if 280 <= mx <= 820 and y <= my <= y + 92:
                        selected = i
                        if action == "leaderboard":
                            await show_leaderboard(screen, clock)
                        else:
                            return action, screen, fullscreen
        await asyncio.sleep(0)


SCORES_DB = os.path.join(os.path.dirname(__file__), "scores.db")
MAX_SCORES = 10


def _db_connect():
    if sqlite3 is None or IS_WEB:
        raise RuntimeError("Local SQLite scores are unavailable in the web build.")
    con = sqlite3.connect(SCORES_DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS scores ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "lines INTEGER NOT NULL,"
        "level INTEGER NOT NULL,"
        "mode TEXT NOT NULL"
        ")"
    )
    con.commit()
    return con


def load_scores(mode: str = "") -> List[dict]:
    if sqlite3 is None or IS_WEB:
        return []
    try:
        con = _db_connect()
        if mode:
            rows = con.execute(
                "SELECT name, score, lines, level, mode FROM scores "
                "WHERE mode = ? ORDER BY score DESC LIMIT ?", (mode, MAX_SCORES)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT name, score, lines, level, mode FROM scores "
                "ORDER BY score DESC LIMIT ?", (MAX_SCORES,)
            ).fetchall()
        con.close()
        return [{"name": r[0], "score": r[1], "lines": r[2], "level": r[3], "mode": r[4]} for r in rows]
    except sqlite3.Error:
        return []


def save_score(name: str, score: int, lines: int, level: int, mode: str) -> List[dict]:
    if sqlite3 is None or IS_WEB:
        return []
    try:
        con = _db_connect()
        con.execute(
            "INSERT INTO scores (name, score, lines, level, mode) VALUES (?, ?, ?, ?, ?)",
            (name, score, lines, level, mode),
        )
        con.commit()
        con.close()
    except sqlite3.Error:
        pass
    return load_scores(mode)


async def show_name_entry(screen: pygame.Surface, clock: pygame.time.Clock,
                          score: int, lines: int, level: int, mode: str) -> None:
    """Prompt for player name and save the score."""
    font_big = pygame.font.SysFont("consolas", 46, bold=True)
    font_med = pygame.font.SysFont("consolas", 30)
    font_sm = pygame.font.SysFont("consolas", 22)

    name = ""
    max_len = 16

    while True:
        canvas = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        canvas.fill(BG_COLOR)

        t = font_big.render("GAME OVER", True, (255, 130, 130))
        canvas.blit(t, (SCREEN_W // 2 - t.get_width() // 2, 160))

        for i, (label, val) in enumerate([
            ("Score", str(score)),
            ("Planes", str(lines)),
            ("Level", str(level)),
            ("Mode",  mode),
        ]):
            surf = font_med.render(f"{label}: {val}", True, TEXT_COLOR)
            canvas.blit(surf, (SCREEN_W // 2 - surf.get_width() // 2, 280 + i * 42))

        prompt = font_med.render("Enter your name:", True, (160, 195, 230))
        canvas.blit(prompt, (SCREEN_W // 2 - prompt.get_width() // 2, 470))

        box_w, box_h = 400, 54
        box_x = SCREEN_W // 2 - box_w // 2
        box_y = 520
        pygame.draw.rect(canvas, (28, 40, 56), (box_x, box_y, box_w, box_h), border_radius=10)
        pygame.draw.rect(canvas, (80, 130, 200), (box_x, box_y, box_w, box_h), 2, border_radius=10)
        name_surf = font_med.render(name + "|", True, (230, 245, 255))
        canvas.blit(name_surf, (box_x + 14, box_y + 10))

        hint = font_sm.render("Press Enter to save", True, (90, 115, 140))
        canvas.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, 600))

        present_scaled(canvas, screen)
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit
            elif event.type == pygame.VIDEORESIZE:
                w = max(800, event.w)
                h = max(700, event.h)
                screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    entry_name = name.strip() or "Anonymous"
                    save_score(entry_name, score, lines, level, mode)
                    return
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    return
                elif len(name) < max_len and event.unicode.isprintable() and event.unicode != "":
                    name += event.unicode
        await asyncio.sleep(0)


async def show_leaderboard(screen: pygame.Surface, clock: pygame.time.Clock) -> None:
    font_big = pygame.font.SysFont("consolas", 38, bold=True)
    font_med = pygame.font.SysFont("consolas", 22)
    font_sm  = pygame.font.SysFont("consolas", 18)

    # Two panels side by side
    panel_w = SCREEN_W // 2 - 30
    panels = [
        ("NORMAL", "Normal", 20,              (100, 160, 220)),
        ("EASY",   "Easy",   SCREEN_W // 2 + 10, (100, 210, 130)),
    ]
    headers = ["#", "Name", "Score", "Planes", "Lvl"]
    col_offsets = [0, 30, 180, 290, 360]  # relative to panel left
    row_h = 42
    first_row_y = 166

    while True:
        canvas = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        canvas.fill(BG_COLOR)

        title = font_big.render("LEADERBOARD", True, (200, 230, 255))
        canvas.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 28))

        for panel_label, mode, px, accent in panels:
            scores = load_scores(mode)

            # Panel background
            pygame.draw.rect(canvas, (20, 30, 46), (px, 88, panel_w, SCREEN_H - 148), border_radius=12)
            pygame.draw.rect(canvas, accent, (px, 88, panel_w, SCREEN_H - 148), 2, border_radius=12)

            lbl = font_big.render(panel_label, True, accent)
            canvas.blit(lbl, (px + panel_w // 2 - lbl.get_width() // 2, 96))

            # Headers
            for col, hdr in zip(col_offsets, headers):
                hs = font_sm.render(hdr, True, (110, 145, 185))
                canvas.blit(hs, (px + 12 + col, first_row_y - 22))
            pygame.draw.line(canvas, (44, 60, 82), (px + 8, first_row_y), (px + panel_w - 8, first_row_y), 1)

            for i, entry in enumerate(scores):
                y = first_row_y + 4 + i * row_h
                bg = (28, 40, 58) if i % 2 == 0 else (22, 32, 48)
                pygame.draw.rect(canvas, bg, (px + 8, y, panel_w - 16, row_h - 4), border_radius=6)
                if i == 0:
                    pygame.draw.rect(canvas, accent, (px + 8, y, panel_w - 16, row_h - 4), 2, border_radius=6)

                row_color = (255, 222, 100) if i == 0 else TEXT_COLOR
                vals = [
                    str(i + 1),
                    entry.get("name", "-")[:14],
                    f"{entry.get('score', 0):,}",
                    str(entry.get("lines", 0)),
                    str(entry.get("level", 1)),
                ]
                for col, val in zip(col_offsets, vals):
                    surf = font_med.render(val, True, row_color)
                    canvas.blit(surf, (px + 12 + col, y + 10))

        hint = font_sm.render("Press Enter or Esc to continue", True, (80, 105, 130))
        canvas.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 36))

        present_scaled(canvas, screen)
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit
            elif event.type == pygame.VIDEORESIZE:
                w = max(800, event.w)
                h = max(700, event.h)
                screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                    return
        await asyncio.sleep(0)


async def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    fullscreen = False

    while True:
        choice, screen, fullscreen = await show_start_screen(screen, clock, fullscreen)
        if choice == "quit":
            break
        game = Game3DTetris(
            screen=screen,
            clock=clock,
            easy_mode=(choice == "easy"),
            fullscreen=fullscreen,
        )
        await game.run()
        screen = game.display
        fullscreen = game.fullscreen
    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())

