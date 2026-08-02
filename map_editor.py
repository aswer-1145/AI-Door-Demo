"""
光线投射 Demo - 地图编辑器
使用 pygame 绘制伪 3D 关卡地图 (与游戏中 MAP 二维数组完全兼容)
支持多地图管理, 地图间通过传送门连接。

操作:
  左键点击/拖拽      - 在地图格上绘制当前选中的瓦片类型
  右键点击           - 删除附近的敌人/传送门, 或擦除瓦片 (画空地 0)
  鼠标滚轮           - 缩放视图
  中键按住拖拽 / 空格+左键拖拽 - 平移视图
  0 ~ 4 数字键       - 快速切换瓦片类型
  P                  - 切换"出生点放置"模式 (左键点击放置玩家出生位置)
  D                  - 切换"门扉放置"模式 (H=横向门, V=纵向门, 左键放置)
  G                  - 切换"敌人放置"模式 (H/J/K 切换敌种, 左键放置)
  T                  - 切换"传送门放置"模式 (左键放置, [/]切换目标地图, ↑↓←→微调到达点)
                     放置后自动双向配对: 若目标地图有指回当前地图的传送门, 互相设定到达点
  Backspace          - 清空当前模式所有放置物 (敌人/传送门)
  Ctrl+Z             - 撤销最后一次放置 (敌人/传送门)
  M                  - 添加新地图到列表末尾
  X                  - 删除当前地图 (至少保留 1 张)
  PageUp / PageDown  - 切换到上一张/下一张地图
  C                  - 清空当前地图 (只留外围一圈墙)
  N                  - 新建默认地图 (重置当前地图槽位)
  S                  - 保存所有地图到 map.json (游戏本体自动读取此文件)
  L                  - 从 map.json 加载地图
  E                  - 导出当前地图为 Python 代码
  R                  - 重置视图 (缩放 1x, 居中到地图)
  ESC                - 退出
"""

import json
import os
import math
import sys
from pathlib import Path

import pygame


# ---------------------------------------------------------------------------
# 瓦片颜色 (与游戏 raycasting_demo.py 保持一致)
# ---------------------------------------------------------------------------
TILE_COLORS = {
    0: (25, 25, 35),            # 空地 (深灰)
    1: (180, 180, 180),         # 普通墙 (灰白)
    2: (200, 60, 60),           # 红墙
    3: (60, 200, 60),           # 绿墙
    4: (60, 60, 200),           # 蓝墙
    5: (160, 110, 50),          # 横向门扉 (棕色)
    6: (110, 160, 50),          # 纵向门扉 (黄绿)
}
TILE_LABELS = {
    0: "空地 0",
    1: "墙 1 (白)",
    2: "墙 2 (红)",
    3: "墙 3 (绿)",
    4: "墙 4 (蓝)",
    5: "门扉 5 (横)",
    6: "门扉 6 (纵)",
}

DOOR_COLOR = (160, 110, 50)     # 门扉主色

# 敌人种类配置 (颜色与游戏 raycasting_demo.py 中 ENEMY_TYPES 保持一致)
ENEMY_KINDS = {
    "grunt":  {"color": (190, 50, 50),  "label": "普通 (grunt)",  "key": "H"},
    "sprite": {"color": (235, 205, 70), "label": "快速 (sprite)", "key": "J"},
    "brute":  {"color": (150, 70, 180), "label": "厚血 (brute)",  "key": "K"},
}

# 传送门颜色
PORTAL_COLOR = (100, 200, 255)
PORTAL_GLOW = (60, 140, 200)

# UI 布局常量
PALETTE_W = 180                # 左侧调色板宽度
UI_TOP_H = 60                  # 顶部工具条高度
UI_BOTTOM_H = 40               # 底部状态栏高度
GRID_LINE_COLOR = (70, 70, 90)
BG_COLOR = (18, 18, 28)
PANEL_COLOR = (28, 30, 44)
PANEL_HL = (46, 48, 70)
BORDER_COLOR = (90, 95, 140)
TEXT_COLOR = (230, 230, 240)
TEXT_DIM = (150, 150, 170)
ACCENT = (120, 180, 255)

FPS = 60

SCRIPT_DIR = Path(__file__).parent
MAPS_DIR = SCRIPT_DIR / "maps"
MAPS_DIR.mkdir(exist_ok=True)

# 共享地图文件: 游戏本体 raycasting_demo.py 启动时自动读取此文件
MAP_FILE = SCRIPT_DIR / "map.json"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def make_default_map(w=16, h=13):
    """生成默认地图 (四周一圈墙 1, 内部 0)。"""
    m = [[1 if (x == 0 or y == 0 or x == w - 1 or y == h - 1) else 0
          for x in range(w)] for y in range(h)]
    return m


def darken(color, factor=0.6):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def lighten(color, factor=1.3):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


# ---------------------------------------------------------------------------
# 按钮
# ---------------------------------------------------------------------------
class Button:
    def __init__(self, rect, label, on_click=None, color=PANEL_COLOR, fg=TEXT_COLOR):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.color = color
        self.fg = fg
        self.hover = False

    def draw(self, surf, font):
        c = lighten(self.color, 1.15) if self.hover else self.color
        pygame.draw.rect(surf, c, self.rect, border_radius=4)
        pygame.draw.rect(surf, BORDER_COLOR, self.rect, 1, border_radius=4)
        txt = font.render(self.label, True, self.fg)
        tr = txt.get_rect(center=self.rect.center)
        surf.blit(txt, tr)

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos) and self.on_click:
                self.on_click()
                return True
        return False


# ---------------------------------------------------------------------------
# 编辑器主类
# ---------------------------------------------------------------------------
class MapEditor:
    def __init__(self):
        pygame.init()
        self.screen_w = 1200
        self.screen_h = 720
        self.screen = pygame.display.set_mode((self.screen_w, self.screen_h),
                                               pygame.RESIZABLE)
        pygame.display.set_caption("Raycaster 地图编辑器  -  S 保存 / L 加载 / E 导出 / N 新建 / C 清空 / R 重置视图")
        self.clock = pygame.time.Clock()
        # 使用支持中文的字体 (微软雅黑), consolas 无中文字形会导致问号
        self.font = pygame.font.SysFont("microsoftyahei,msyh,consolas", 14)
        self.font_big = pygame.font.SysFont("microsoftyahei,msyh,consolas", 18, bold=True)

        # 多地图数据: 启动时优先从共享 map.json 加载
        self.maps = self._load_maps(MAP_FILE)
        self.current_map_idx = 0
        self.selected_tile = 1
        self.spawn_mode = False          # P 键切换: 出生点放置模式
        self.door_mode = False           # D 键切换: 门扉放置模式
        self.door_dir = "h"             # "h"=横向门(5), "v"=纵向门(6)
        self.enemy_mode = False          # G 键切换: 敌人放置模式
        self.enemy_kind = "grunt"       # 当前敌种: grunt/sprite/brute
        self.transition_mode = False    # T 键切换: 传送门放置模式
        self._last_enemy_cell = None     # 拖拽放置时避免同一格重复放置
        self._last_transition_cell = None

        # 视图
        self.tile_size = 48
        self.view_x = 0  # 视图左上角在"世界"(地图)中的像素坐标 (负数表示地图右移)
        self.view_y = 0
        self._center_map()

        # 编辑状态
        self.drawing = False          # 左键按住绘制
        self.erasing = False          # 右键按住擦除
        self.panning = False
        self.pan_button = None        # 2=中键, 1=空格+左键
        self.last_mouse = (0, 0)
        self.hover_cell = None        # (mx, my) 当前鼠标下的地图格

        # 文件名
        self.current_file = None
        self.export_counter = 0

        # 按钮
        self.buttons = []
        self._rebuild_buttons()

    # ------------------------------------------------------------------
    # 视图辅助
    # ------------------------------------------------------------------
    @property
    def current_map(self):
        return self.maps[self.current_map_idx]

    @property
    def map_data(self):
        return self.current_map["map"]

    @map_data.setter
    def map_data(self, value):
        self.current_map["map"] = value

    @property
    def map_rows(self):
        return len(self.map_data)

    @property
    def map_cols(self):
        return len(self.map_data[0]) if self.map_data else 0

    @property
    def spawn_point(self):
        sp = self.current_map.get("spawn")
        if sp and isinstance(sp, dict) and "x" in sp and "y" in sp:
            return (sp["x"], sp["y"])
        return None

    @spawn_point.setter
    def spawn_point(self, value):
        if value is None:
            self.current_map.pop("spawn", None)
        else:
            self.current_map["spawn"] = {"x": value[0], "y": value[1]}

    @property
    def enemies(self):
        return self.current_map.setdefault("enemies", [])

    @enemies.setter
    def enemies(self, value):
        self.current_map["enemies"] = value

    @property
    def transitions(self):
        return self.current_map.setdefault("transitions", [])

    @transitions.setter
    def transitions(self, value):
        self.current_map["transitions"] = value

    def _center_map(self):
        mw = self.map_cols * self.tile_size
        mh = self.map_rows * self.tile_size
        area_x = PALETTE_W
        area_y = UI_TOP_H
        area_w = self.screen_w - PALETTE_W
        area_h = self.screen_h - UI_TOP_H - UI_BOTTOM_H
        self.view_x = (area_w - mw) / 2 - area_x
        self.view_y = (area_h - mh) / 2 - area_y

    def screen_to_map(self, sx, sy):
        mx = (sx - self.view_x) / self.tile_size
        my = (sy - self.view_y) / self.tile_size
        return mx, my

    def in_bounds(self, mx, my):
        return 0 <= mx < self.map_cols and 0 <= my < self.map_rows

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _rebuild_buttons(self):
        h = 34
        y = 12
        x = 10 + PALETTE_W + 8
        w = 110

        self.buttons = []

        def mkbtn(label, cb, pos_idx=0):
            nonlocal x, y
            rect = (x + pos_idx * (w + 10), y, w, h)
            self.buttons.append(Button(rect, label, cb))

        mkbtn("新建 (N)", self.action_new, 0)
        mkbtn("清空 (C)", self.action_clear, 1)
        mkbtn("重置视图 (R)", self.action_reset_view, 2)
        mkbtn("保存 (S)", self.action_save, 3)
        mkbtn("加载 (L)", self.action_load, 4)
        mkbtn("导出 (E)", self.action_export, 5)
        mkbtn("退出 (Esc)", self.action_quit, 6)

    def _draw_palette(self, surf):
        rect = pygame.Rect(0, 0, PALETTE_W, self.screen_h)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (PALETTE_W - 1, 0),
                         (PALETTE_W - 1, self.screen_h), 1)

        title = self.font_big.render("调色板", True, TEXT_COLOR)
        surf.blit(title, (14, 8))

        # 紧凑布局: 缩小色块和间距, 避免提示区与条目重叠
        y = 34
        tile_size = 28
        item_h = 38
        gap = 3
        item_w = PALETTE_W - 20

        for tid in (0, 1, 2, 3, 4):
            item_rect = pygame.Rect(10, y, item_w, item_h)
            if tid == self.selected_tile and not self.spawn_mode:
                pygame.draw.rect(surf, PANEL_HL, item_rect, border_radius=4)
                pygame.draw.rect(surf, ACCENT, item_rect, 2, border_radius=4)
            swatch = pygame.Rect(item_rect.x + 5, item_rect.y + 5,
                                 tile_size, tile_size)
            pygame.draw.rect(surf, TILE_COLORS[tid], swatch, border_radius=3)
            pygame.draw.rect(surf, BORDER_COLOR, swatch, 1, border_radius=3)
            label = self.font.render(TILE_LABELS[tid], True, TEXT_COLOR)
            surf.blit(label, (swatch.right + 8, swatch.y + 1))
            key_hint = self.font.render(f"按 {tid}", True, TEXT_DIM)
            surf.blit(key_hint, (swatch.right + 8, swatch.y + 17))
            y += item_h + gap

        # 出生点条目
        spawn_rect = pygame.Rect(10, y, item_w, item_h)
        if self.spawn_mode:
            pygame.draw.rect(surf, PANEL_HL, spawn_rect, border_radius=4)
            pygame.draw.rect(surf, (255, 220, 80), spawn_rect, 2, border_radius=4)
        spawn_swatch = pygame.Rect(spawn_rect.x + 5, spawn_rect.y + 5,
                                   tile_size, tile_size)
        pygame.draw.rect(surf, (40, 40, 50), spawn_swatch, border_radius=3)
        pygame.draw.circle(surf, (255, 220, 80),
                           spawn_swatch.center, tile_size // 2 - 3)
        pygame.draw.circle(surf, (180, 150, 30),
                           spawn_swatch.center, tile_size // 2 - 3, 2)
        sp_label = self.font.render("玩家出生点", True, TEXT_COLOR)
        surf.blit(sp_label, (spawn_swatch.right + 8, spawn_swatch.y + 1))
        sp_hint = self.font.render("按 P 切换", True, TEXT_DIM)
        surf.blit(sp_hint, (spawn_swatch.right + 8, spawn_swatch.y + 17))
        y += item_h + gap

        # 门扉条目
        door_rect = pygame.Rect(10, y, item_w, item_h)
        if self.door_mode:
            pygame.draw.rect(surf, PANEL_HL, door_rect, border_radius=4)
            pygame.draw.rect(surf, DOOR_COLOR, door_rect, 2, border_radius=4)
        door_swatch = pygame.Rect(door_rect.x + 5, door_rect.y + 5,
                                  tile_size, tile_size)
        pygame.draw.rect(surf, (40, 40, 50), door_swatch, border_radius=3)
        dc = DOOR_COLOR
        if self.door_dir == "h":
            pygame.draw.line(surf, dc, (door_swatch.x + 4, door_swatch.centery),
                             (door_swatch.right - 4, door_swatch.centery), 2)
            pygame.draw.polygon(surf, dc,
                                [(door_swatch.right - 3, door_swatch.centery),
                                 (door_swatch.right - 8, door_swatch.centery - 4),
                                 (door_swatch.right - 8, door_swatch.centery + 4)])
        else:
            pygame.draw.line(surf, dc, (door_swatch.centerx, door_swatch.y + 4),
                             (door_swatch.centerx, door_swatch.bottom - 4), 2)
            pygame.draw.polygon(surf, dc,
                                [(door_swatch.centerx, door_swatch.bottom - 3),
                                 (door_swatch.centerx - 4, door_swatch.bottom - 8),
                                 (door_swatch.centerx + 4, door_swatch.bottom - 8)])
        d_label = self.font.render("门扉 (滑动)", True, TEXT_COLOR)
        surf.blit(d_label, (door_swatch.right + 8, door_swatch.y + 1))
        d_hint = self.font.render("D 切换 H/V", True, TEXT_DIM)
        surf.blit(d_hint, (door_swatch.right + 8, door_swatch.y + 17))
        y += item_h + gap

        # 敌人条目
        enemy_rect = pygame.Rect(10, y, item_w, item_h)
        if self.enemy_mode:
            pygame.draw.rect(surf, PANEL_HL, enemy_rect, border_radius=4)
            ecol = ENEMY_KINDS[self.enemy_kind]["color"]
            pygame.draw.rect(surf, ecol, enemy_rect, 2, border_radius=4)
        enemy_swatch = pygame.Rect(enemy_rect.x + 5, enemy_rect.y + 5,
                                   tile_size, tile_size)
        pygame.draw.rect(surf, (40, 40, 50), enemy_swatch, border_radius=3)
        ek_col = ENEMY_KINDS[self.enemy_kind]["color"]
        pygame.draw.circle(surf, ek_col, enemy_swatch.center, tile_size // 2 - 3)
        pygame.draw.circle(surf, BORDER_COLOR, enemy_swatch.center, tile_size // 2 - 3, 1)
        init_char = self.enemy_kind[0].upper()
        char_surf = self.font.render(init_char, True, (250, 250, 250))
        surf.blit(char_surf, char_surf.get_rect(center=enemy_swatch.center))
        e_label = self.font.render(f"敌人 ({self.enemy_kind})", True, TEXT_COLOR)
        surf.blit(e_label, (enemy_swatch.right + 8, enemy_swatch.y + 1))
        e_hint = self.font.render(f"G 切换 H/J/K", True, TEXT_DIM)
        surf.blit(e_hint, (enemy_swatch.right + 8, enemy_swatch.y + 17))
        y += item_h + gap

        # 传送门条目
        portal_rect = pygame.Rect(10, y, item_w, item_h)
        if self.transition_mode:
            pygame.draw.rect(surf, PANEL_HL, portal_rect, border_radius=4)
            pygame.draw.rect(surf, PORTAL_COLOR, portal_rect, 2, border_radius=4)
        portal_swatch = pygame.Rect(portal_rect.x + 5, portal_rect.y + 5,
                                    tile_size, tile_size)
        pygame.draw.rect(surf, (40, 40, 50), portal_swatch, border_radius=3)
        pygame.draw.circle(surf, PORTAL_GLOW, portal_swatch.center, tile_size // 2 - 2, 2)
        pygame.draw.circle(surf, PORTAL_COLOR, portal_swatch.center, tile_size // 2 - 4)
        p_label = self.font.render("传送门", True, TEXT_COLOR)
        surf.blit(p_label, (portal_swatch.right + 8, portal_swatch.y + 1))
        p_hint = self.font.render("T 切换 [/]目标", True, TEXT_DIM)
        surf.blit(p_hint, (portal_swatch.right + 8, portal_swatch.y + 17))
        y += item_h + gap

        # 分隔线 + 提示信息 (紧接在条目下方, 不再重叠)
        y += 4
        pygame.draw.line(surf, BORDER_COLOR, (10, y), (PALETTE_W - 10, y), 1)
        y += 4

        hint_lines = [
            ("操作:", TEXT_COLOR),
            ("左键绘制 / 右键删除", TEXT_DIM),
            ("滚轮缩放 / 中键平移", TEXT_DIM),
            ("0~4 瓦片 / P 出生", TEXT_DIM),
            ("D 门 / G 敌 / T 传送", TEXT_DIM),
            ("敌人: H/J/K 切种", TEXT_DIM),
            ("传送: [/]目标 ↑↓←→微调", TEXT_DIM),
            ("(放置即自动双向配对)", TEXT_DIM),
            ("Backspace 清空 / Ctrl+Z", TEXT_DIM),
            ("M 加图 / X 删图 / PgUp↓", TEXT_DIM),
            ("", TEXT_DIM),
            (f"地图: {self.current_map_idx + 1}/{len(self.maps)}", ACCENT),
            (f"尺寸 {self.map_cols}x{self.map_rows}", TEXT_DIM),
            (f"格 {self.hover_cell}" if self.hover_cell else "当前格 --", TEXT_DIM),
            (f"出生 ({self.spawn_point[0]:.1f},{self.spawn_point[1]:.1f})"
             if self.spawn_point else "出生点 未设置", TEXT_DIM),
            (f"门: {'横←→' if self.door_dir == 'h' else '纵↑↓'}"
             if self.door_mode else "", TEXT_DIM),
            (f"种: {ENEMY_KINDS[self.enemy_kind]['label'].split(' ')[0]}"
             if self.enemy_mode else "", TEXT_DIM),
            (f"敌人: {len(self.enemies)} 个", TEXT_DIM),
            (f"传送门: {len(self.transitions)} 个", TEXT_DIM),
        ]
        # 传送门模式: 显示光标处传送门的目标信息
        ht = self._get_hovered_transition()
        if ht:
            hint_lines.append(("", TEXT_DIM))
            hint_lines.append(("→ 传送门目标:", ACCENT))
            hint_lines.append((f"  地图{ht['target_map'] + 1} "
                                f"({ht['target_x']:.1f},{ht['target_y']:.1f})",
                                TEXT_DIM))
        for text, col in hint_lines:
            if text:
                surf.blit(self.font.render(text, True, col), (12, y))
            y += 14

    def _draw_topbar(self, surf):
        rect = pygame.Rect(PALETTE_W, 0, self.screen_w - PALETTE_W, UI_TOP_H)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (PALETTE_W, UI_TOP_H - 1),
                         (self.screen_w, UI_TOP_H - 1), 1)
        for b in self.buttons:
            b.draw(surf, self.font)

    def _draw_bottombar(self, surf):
        y0 = self.screen_h - UI_BOTTOM_H
        rect = pygame.Rect(PALETTE_W, y0, self.screen_w - PALETTE_W, UI_BOTTOM_H)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (PALETTE_W, y0),
                         (self.screen_w, y0), 1)

        parts = []
        map_name = self.current_map.get("name", f"地图 {self.current_map_idx + 1}")
        parts.append((f"地图 {self.current_map_idx + 1}/{len(self.maps)}: {map_name}",
                      ACCENT))
        parts.append((f"  |  瓦片: {self.selected_tile} {TILE_LABELS[self.selected_tile]}",
                      TEXT_COLOR))
        parts.append((f"  |  视图: 缩放={self.tile_size}  "
                      f"平移=({self.view_x:.0f},{self.view_y:.0f})", TEXT_DIM))
        if self.current_file:
            parts.append((f"  |  文件: {self.current_file.name}", ACCENT))
        else:
            parts.append(("  |  文件: map.json (未保存)", TEXT_DIM))
        x = PALETTE_W + 12
        for text, col in parts:
            t = self.font.render(text, True, col)
            surf.blit(t, (x, y0 + (UI_BOTTOM_H - t.get_height()) // 2))
            x += t.get_width()

    def _draw_grid(self, surf):
        # 绘制编辑区域背景
        area = pygame.Rect(PALETTE_W, UI_TOP_H,
                           self.screen_w - PALETTE_W,
                           self.screen_h - UI_TOP_H - UI_BOTTOM_H)
        # 棋盘式背景花纹 (淡)
        tile = 16
        for gy in range(area.y, area.bottom, tile):
            for gx in range(area.x, area.right, tile):
                c = 23 if ((gx // tile + gy // tile) & 1) == 0 else 20
                pygame.draw.rect(surf, (c, c, c + 2), (gx, gy, tile, tile))

        # 绘制地图格
        ts = self.tile_size
        mx0, my0 = self.screen_to_map(area.x, area.y)
        mx1, my1 = self.screen_to_map(area.right, area.bottom)
        mx0 = max(0, int(math.floor(mx0)) - 1)
        my0 = max(0, int(math.floor(my0)) - 1)
        mx1 = min(self.map_cols, int(math.ceil(mx1)) + 1)
        my1 = min(self.map_rows, int(math.ceil(my1)) + 1)

        for my in range(my0, my1):
            for mx in range(mx0, mx1):
                val = self.map_data[my][mx]
                sx = int(mx * ts + self.view_x)
                sy = int(my * ts + self.view_y)
                rect = pygame.Rect(sx, sy, ts, ts)
                pygame.draw.rect(surf, TILE_COLORS.get(val, (128, 128, 128)), rect)
                pygame.draw.rect(surf, GRID_LINE_COLOR, rect, 1)
                # 在小比例时不画数字, 否则每个格内标数字
                if ts >= 26:
                    num = self.font.render(str(val), True,
                                           darken(TILE_COLORS.get(val, (128, 128, 128)), 0.2)
                                           if val != 0 else (90, 90, 110))
                    nr = num.get_rect(center=rect.center)
                    surf.blit(num, nr)
                # 门扉方向箭头
                if val in (5, 6):
                    cx, cy = rect.center
                    arrow_col = lighten(TILE_COLORS[val], 1.4)
                    if val == 5:  # 横向, 箭头朝右
                        ax = cx + ts // 4
                        pygame.draw.line(surf, arrow_col,
                                         (cx - ts // 4, cy), (ax, cy), 2)
                        pygame.draw.polygon(surf, arrow_col,
                                            [(ax + 5, cy), (ax - 2, cy - 4),
                                             (ax - 2, cy + 4)])
                    else:         # 纵向, 箭头朝下
                        ay = cy + ts // 4
                        pygame.draw.line(surf, arrow_col,
                                         (cx, cy - ts // 4), (cx, ay), 2)
                        pygame.draw.polygon(surf, arrow_col,
                                            [(cx, ay + 5), (cx - 4, ay - 2),
                                             (cx + 4, ay - 2)])

        # 地图整体外框
        outer = pygame.Rect(int(self.view_x), int(self.view_y),
                            self.map_cols * ts, self.map_rows * ts)
        pygame.draw.rect(surf, ACCENT, outer, 2)

        # 出生点标记
        if self.spawn_point:
            spx = int(self.spawn_point[0] * ts + self.view_x)
            spy = int(self.spawn_point[1] * ts + self.view_y)
            r = max(6, ts // 3)
            # 外圈光晕
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 220, 80, 60), (r * 2, r * 2), r * 2)
            surf.blit(glow, (spx - r * 2, spy - r * 2))
            # 主体圆
            pygame.draw.circle(surf, (255, 220, 80), (spx, spy), r)
            pygame.draw.circle(surf, (180, 150, 30), (spx, spy), r, 2)
            # 方向箭头 (朝东)
            arrow_end = (spx + r + 8, spy)
            pygame.draw.line(surf, (255, 220, 80), (spx, spy), arrow_end, 3)
            pygame.draw.polygon(surf, (255, 220, 80),
                                [(arrow_end[0] + 6, spy),
                                 (arrow_end[0], spy - 5),
                                 (arrow_end[0], spy + 5)])

        # 敌人标记 (彩色圆点 + 首字母)
        for e in self.enemies:
            ex = int(e["x"] * ts + self.view_x)
            ey = int(e["y"] * ts + self.view_y)
            r = max(5, ts // 3)
            col = ENEMY_KINDS[e["kind"]]["color"]
            # 阴影
            pygame.draw.circle(surf, (0, 0, 0), (ex + 2, ey + 2), r + 1)
            # 主体
            pygame.draw.circle(surf, col, (ex, ey), r)
            outline = tuple(max(0, c - 80) for c in col)
            pygame.draw.circle(surf, outline, (ex, ey), r, 2)
            # 首字母
            char = self.font.render(e["kind"][0].upper(), True, (250, 250, 250))
            surf.blit(char, char.get_rect(center=(ex, ey)))

        # 传送门标记 (蓝色光圈 + 目标编号)
        for t in self.transitions:
            tx = int(t["x"] * ts + self.view_x)
            ty = int(t["y"] * ts + self.view_y)
            r = max(6, ts // 3)
            # 光晕
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*PORTAL_COLOR, 50), (r * 2, r * 2), r * 2)
            surf.blit(glow, (tx - r * 2, ty - r * 2))
            # 外圈
            pygame.draw.circle(surf, PORTAL_GLOW, (tx, ty), r + 2, 2)
            # 内圈
            pygame.draw.circle(surf, PORTAL_COLOR, (tx, ty), r)
            pygame.draw.circle(surf, (220, 240, 255), (tx, ty), r, 2)
            # 目标地图编号
            tgt = t.get("target_map", 0)
            num = self.font_big.render(str(tgt + 1), True, (20, 40, 80))
            surf.blit(num, num.get_rect(center=(tx, ty)))

        # 鼠标悬停高亮
        if self.hover_cell and self.in_bounds(*self.hover_cell):
            hx, hy = self.hover_cell
            rect = pygame.Rect(int(hx * ts + self.view_x),
                               int(hy * ts + self.view_y),
                               ts, ts)
            hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            hl.fill((255, 255, 255, 55))
            surf.blit(hl, rect)
            pygame.draw.rect(surf, (255, 230, 120), rect, 2)

        # 裁剪 (地图内容不覆盖到 palette / topbar / bottombar)
        # 上面绘制前可以用 clip, 简单起见我们在最后画覆盖条
        # (这里我们只画 area 内, 因此 palette / bars 在上方重绘即可)

    # ------------------------------------------------------------------
    # 绘制总入口
    # ------------------------------------------------------------------
    def draw(self):
        self.screen.fill(BG_COLOR)
        self._draw_grid(self.screen)
        self._draw_palette(self.screen)
        self._draw_topbar(self.screen)
        self._draw_bottombar(self.screen)
        pygame.display.flip()

    # ------------------------------------------------------------------
    # 编辑操作
    # ------------------------------------------------------------------
    def paint_cell(self, sx, sy, value):
        mx, my = self.screen_to_map(sx, sy)
        imx, imy = int(mx), int(my)
        if not self.in_bounds(imx, imy):
            return
        if 0 <= (mx - imx) <= 1 and 0 <= (my - imy) <= 1:
            self.map_data[imy][imx] = value

    # ------------------------------------------------------------------
    # 动作: 按钮功能
    # ------------------------------------------------------------------
    def action_new(self):
        # 新建默认 16x13 地图 (重置当前地图槽位)
        self.current_map["map"] = make_default_map(16, 13)
        self.current_map.pop("spawn", None)
        self.current_map["enemies"] = []
        self.current_map["transitions"] = []
        self.current_file = None
        self._center_map()

    def action_add_map(self):
        # 添加一张新地图到列表末尾, 并切换过去
        idx = len(self.maps)
        self.maps.append({
            "name": f"地图 {idx + 1}",
            "map": make_default_map(16, 13),
        })
        self.current_map_idx = idx
        self._center_map()
        print(f"已添加新地图 (当前共 {len(self.maps)} 张)")

    def action_del_map(self):
        # 删除当前地图 (至少保留 1 张)
        if len(self.maps) <= 1:
            print("至少需要保留 1 张地图")
            return
        del self.maps[self.current_map_idx]
        # 修正所有指向被删地图的传送门
        for m in self.maps:
            m.pop("transitions", None)
        self.current_map_idx = max(0, self.current_map_idx - 1)
        self._center_map()

    def action_next_map(self):
        if len(self.maps) > 1:
            self.current_map_idx = (self.current_map_idx + 1) % len(self.maps)
            self._center_map()

    def action_prev_map(self):
        if len(self.maps) > 1:
            self.current_map_idx = (self.current_map_idx - 1) % len(self.maps)
            self._center_map()

    def action_clear(self):
        # 清空地图内部为 0, 保留外围墙
        for my in range(self.map_rows):
            for mx in range(self.map_cols):
                if mx == 0 or my == 0 or mx == self.map_cols - 1 or my == self.map_rows - 1:
                    self.map_data[my][mx] = 1
                else:
                    self.map_data[my][mx] = 0
        # 同步清空敌人和传送门
        self.enemies = []
        self.transitions = []
        # 出生点若在墙内也清除
        if self.spawn_point:
            sx, sy = int(self.spawn_point[0]), int(self.spawn_point[1])
            if not self.in_bounds(sx, sy) or self.map_data[sy][sx] != 0:
                self.spawn_point = None

    def action_reset_view(self):
        self._center_map()

    def _parse_map_dict(self, data, idx=0):
        """从 JSON dict 解析单张地图, 失败返回 None。"""
        if isinstance(data, dict) and "map" in data:
            m = data["map"]
        elif isinstance(data, list):
            m = data
        else:
            return None
        if not m or not all(isinstance(row, list) for row in m):
            return None
        row_len = len(m[0])
        if not all(len(r) == row_len for r in m):
            return None
        result = {"name": data.get("name", f"地图 {idx + 1}") if isinstance(data, dict) else f"地图 {idx + 1}",
                  "map": m}
        if isinstance(data, dict):
            if "spawn" in data:
                result["spawn"] = data["spawn"]
            if "enemies" in data:
                result["enemies"] = data["enemies"]
            if "transitions" in data:
                result["transitions"] = data["transitions"]
        return result

    def _load_maps(self, path):
        """从 JSON 文件加载多地图列表; 向后兼容单地图格式。"""
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # 多地图格式
                if isinstance(data, dict) and "maps" in data:
                    raw_maps = data["maps"]
                    if isinstance(raw_maps, list) and raw_maps:
                        result = []
                        for i, m in enumerate(raw_maps):
                            parsed = self._parse_map_dict(m, i)
                            if parsed:
                                result.append(parsed)
                        if result:
                            return result
                # 单地图格式 (向后兼容)
                single = self._parse_map_dict(data)
                if single:
                    return [single]
        except Exception:
            pass
        return [{"name": "地图 1", "map": make_default_map(16, 13)}]

    def action_save(self):
        # 保存所有地图到共享 map.json (多地图格式)
        self._sync_transitions()
        path = MAP_FILE
        data = {"maps": self.maps}
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
            self.current_file = path
            print(f"已保存 {len(self.maps)} 张地图到 {path.name}")
        except Exception as exc:
            print("保存失败:", exc)

    def action_load(self):
        # 从共享 map.json 加载多地图
        path = MAP_FILE
        maps = self._load_maps(path)
        if maps:
            self.maps = maps
            self.current_map_idx = 0
            self.current_file = path
            self._sync_transitions()
            self._center_map()
            print(f"已加载 {len(self.maps)} 张地图")
        else:
            print(f"未找到或无法读取 {path.name}")

    def action_export(self):
        """导出为 raycasting_demo.py 可直接粘贴的 Python MAP 列表代码。"""
        lines = ["MAP = ["]
        for row in self.map_data:
            lines.append("    [" + ", ".join(str(v) for v in row) + "],")
        lines.append("]")
        code = "\n".join(lines)
        self.export_counter += 1
        out_path = MAPS_DIR / f"export_{self.export_counter:02d}.py"
        out_path.write_text("# 粘贴到 raycasting_demo.py 中替换 MAP 常量\n\n"
                            + code + "\n", encoding="utf-8")
        last_path = MAPS_DIR / "last_export.py"
        last_path.write_text(("# 粘贴到 raycasting_demo.py 中替换 MAP 常量\n\n"
                              + code + "\n"), encoding="utf-8")
        # 尝试复制到系统剪贴板
        try:
            pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT, code.encode("utf-8"))
            extra = " (已复制到剪贴板)"
        except Exception:
            extra = ""
        print(f"已导出到: {out_path}{extra}")
        print(code)

    def action_quit(self):
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def handle_event(self, ev):
        # 先让按钮处理
        if ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            for b in self.buttons:
                if b.handle_event(ev):
                    return

        if ev.type == pygame.QUIT:
            pygame.quit()
            sys.exit(0)

        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit(0)
            elif ev.key in (pygame.K_0, pygame.K_KP0):
                self.selected_tile = 0
                self.spawn_mode = False
                self.door_mode = False
                self.enemy_mode = False
                self.transition_mode = False
            elif ev.key in (pygame.K_1, pygame.K_KP1):
                self.selected_tile = 1
                self.spawn_mode = False
                self.door_mode = False
                self.enemy_mode = False
                self.transition_mode = False
            elif ev.key in (pygame.K_2, pygame.K_KP2):
                self.selected_tile = 2
                self.spawn_mode = False
                self.door_mode = False
                self.enemy_mode = False
                self.transition_mode = False
            elif ev.key in (pygame.K_3, pygame.K_KP3):
                self.selected_tile = 3
                self.spawn_mode = False
                self.door_mode = False
                self.enemy_mode = False
                self.transition_mode = False
            elif ev.key in (pygame.K_4, pygame.K_KP4):
                self.selected_tile = 4
                self.spawn_mode = False
                self.door_mode = False
                self.enemy_mode = False
                self.transition_mode = False
            elif ev.key == pygame.K_p:
                self.spawn_mode = not self.spawn_mode
                if self.spawn_mode:
                    self.door_mode = False
                    self.enemy_mode = False
                    self.transition_mode = False
            elif ev.key == pygame.K_d:
                self.door_mode = not self.door_mode
                if self.door_mode:
                    self.spawn_mode = False
                    self.enemy_mode = False
                    self.transition_mode = False
            elif ev.key == pygame.K_g:
                self.enemy_mode = not self.enemy_mode
                if self.enemy_mode:
                    self.spawn_mode = False
                    self.door_mode = False
                    self.transition_mode = False
            elif ev.key == pygame.K_t:
                self.transition_mode = not self.transition_mode
                if self.transition_mode:
                    self.spawn_mode = False
                    self.door_mode = False
                    self.enemy_mode = False
            elif ev.key == pygame.K_h:
                # 门扉模式下 H=横向门; 敌人模式下 H=grunt
                if self.enemy_mode:
                    self.enemy_kind = "grunt"
                else:
                    self.door_dir = "h"
            elif ev.key == pygame.K_v:
                self.door_dir = "v"
            elif ev.key == pygame.K_j and self.enemy_mode:
                self.enemy_kind = "sprite"
            elif ev.key == pygame.K_k and self.enemy_mode:
                self.enemy_kind = "brute"
            elif ev.key == pygame.K_m:
                self.action_add_map()
            elif ev.key == pygame.K_x:
                self.action_del_map()
            elif ev.key == pygame.K_PAGEUP:
                self.action_prev_map()
            elif ev.key == pygame.K_PAGEDOWN:
                self.action_next_map()
            elif ev.key == pygame.K_LEFTBRACKET:
                # 传送门模式: 切换光标处传送门的目标地图 (向前)
                self._cycle_transition_target(-1)
            elif ev.key == pygame.K_RIGHTBRACKET:
                # 传送门模式: 切换光标处传送门的目标地图 (向后)
                self._cycle_transition_target(1)
            elif ev.key == pygame.K_UP and self.transition_mode:
                self._adjust_transition_target_pos(0, -1)
            elif ev.key == pygame.K_DOWN and self.transition_mode:
                self._adjust_transition_target_pos(0, 1)
            elif ev.key == pygame.K_LEFT and self.transition_mode:
                self._adjust_transition_target_pos(-1, 0)
            elif ev.key == pygame.K_RIGHT and self.transition_mode:
                self._adjust_transition_target_pos(1, 0)
            elif ev.key == pygame.K_BACKSPACE:
                # 当前模式下清空所有放置物
                if self.enemy_mode and self.enemies:
                    n = len(self.enemies)
                    self.enemies = []
                    print(f"已清空 {n} 个敌人")
                elif self.transition_mode and self.transitions:
                    n = len(self.transitions)
                    self.transitions = []
                    print(f"已清空 {n} 个传送门")
            elif ev.key == pygame.K_z and (ev.mod & pygame.KMOD_CTRL):
                # Ctrl+Z: 撤销最后一次放置 (当前模式)
                if self.enemy_mode and self.enemies:
                    self.enemies.pop()
                    print("撤销最后一个敌人")
                elif self.transition_mode and self.transitions:
                    self.transitions.pop()
                    print("撤销最后一个传送门")
            elif ev.key == pygame.K_c:
                self.action_clear()
            elif ev.key == pygame.K_n:
                self.action_new()
            elif ev.key == pygame.K_s:
                self.action_save()
            elif ev.key == pygame.K_l:
                self.action_load()
            elif ev.key == pygame.K_e:
                self.action_export()
            elif ev.key == pygame.K_r:
                self.action_reset_view()

        elif ev.type == pygame.MOUSEWHEEL:
            # 以鼠标位置为锚点缩放
            old_ts = self.tile_size
            new_ts = max(12, min(160, old_ts + (8 if ev.y > 0 else -8)))
            if new_ts == old_ts:
                return
            # 计算锚点: 鼠标屏幕坐标
            mx, my = pygame.mouse.get_pos()
            # 锚点在世界坐标系 (地图像素) 中的位置不变
            wx = (mx - self.view_x) / old_ts
            wy = (my - self.view_y) / old_ts
            self.tile_size = new_ts
            self.view_x = mx - wx * new_ts
            self.view_y = my - wy * new_ts

        elif ev.type == pygame.VIDEORESIZE:
            self.screen_w, self.screen_h = ev.w, ev.h
            self.screen = pygame.display.set_mode((self.screen_w, self.screen_h),
                                                   pygame.RESIZABLE)
            self._rebuild_buttons()

        elif ev.type == pygame.MOUSEBUTTONDOWN:
            sx, sy = ev.pos
            self.last_mouse = (sx, sy)
            if ev.button == 1:
                # 是否在可编辑区域
                area = pygame.Rect(PALETTE_W, UI_TOP_H,
                                   self.screen_w - PALETTE_W,
                                   self.screen_h - UI_TOP_H - UI_BOTTOM_H)
                space_down = pygame.key.get_pressed()[pygame.K_SPACE]
                if area.collidepoint(sx, sy):
                    if space_down:
                        self.panning = True
                        self.pan_button = 1
                    elif self.spawn_mode:
                        # 出生点模式: 点击放置, 不进入拖拽绘制
                        mx, my = self.screen_to_map(sx, sy)
                        imx, imy = int(mx), int(my)
                        if self.in_bounds(imx, imy):
                            self.spawn_point = (imx + 0.5, imy + 0.5)
                    elif self.door_mode:
                        # 门扉模式: 放置门扉瓦片 (5=横向, 6=纵向)
                        door_tile = 5 if self.door_dir == "h" else 6
                        self.paint_cell(sx, sy, door_tile)
                        self.drawing = True  # 允许拖拽连续放置
                    elif self.enemy_mode:
                        # 敌人模式: 左键放置 (格中心), 拖拽时同格不重复
                        mx, my = self.screen_to_map(sx, sy)
                        imx, imy = int(mx), int(my)
                        if self.in_bounds(imx, imy) and self.map_data[imy][imx] == 0:
                            cell = (imx, imy)
                            if cell != self._last_enemy_cell:
                                self.enemies.append({
                                    "x": imx + 0.5, "y": imy + 0.5,
                                    "kind": self.enemy_kind,
                                })
                                self._last_enemy_cell = cell
                            self.drawing = True
                    elif self.transition_mode:
                        # 传送门模式: 左键放置 (格中心), 拖拽时同格不重复
                        mx, my = self.screen_to_map(sx, sy)
                        imx, imy = int(mx), int(my)
                        if self.in_bounds(imx, imy) and self.map_data[imy][imx] == 0:
                            cell = (imx, imy)
                            if cell != self._last_transition_cell:
                                tgt = (self.current_map_idx + 1) % len(self.maps)
                                tx, ty = self._default_target_pos(tgt)
                                self.transitions.append({
                                    "x": imx + 0.5, "y": imy + 0.5,
                                    "target_map": tgt,
                                    "target_x": tx, "target_y": ty,
                                })
                                self._last_transition_cell = cell
                                self._sync_transitions()
                            self.drawing = True
                    else:
                        self.drawing = True
                        self.paint_cell(sx, sy, self.selected_tile)
            elif ev.button == 3:
                mx, my = self.screen_to_map(sx, sy)
                # 任何模式下: 右键优先删除附近的敌人/传送门, 其次擦除瓦片
                if self._remove_nearest_enemy(mx, my, 0.7):
                    pass
                elif self._remove_nearest_transition(mx, my, 0.7):
                    pass
                elif not (self.enemy_mode or self.transition_mode
                          or self.spawn_mode or self.door_mode):
                    self.erasing = True
                    self.paint_cell(sx, sy, 0)
            elif ev.button == 2:
                self.panning = True
                self.pan_button = 2

        elif ev.type == pygame.MOUSEBUTTONUP:
            if ev.button == 1:
                self.drawing = False
                if self.pan_button == 1:
                    self.panning = False
                    self.pan_button = None
            elif ev.button == 3:
                self.erasing = False
            elif ev.button == 2:
                if self.pan_button == 2:
                    self.panning = False
                    self.pan_button = None
            # 任何鼠标键松开都重置拖拽去重
            self._last_enemy_cell = None
            self._last_transition_cell = None

        elif ev.type == pygame.MOUSEMOTION:
            sx, sy = ev.pos
            if self.panning:
                dx = sx - self.last_mouse[0]
                dy = sy - self.last_mouse[1]
                self.view_x += dx
                self.view_y += dy
                self.last_mouse = (sx, sy)
                return
            self.last_mouse = (sx, sy)
            # 计算悬停格
            area = pygame.Rect(PALETTE_W, UI_TOP_H,
                               self.screen_w - PALETTE_W,
                               self.screen_h - UI_TOP_H - UI_BOTTOM_H)
            if area.collidepoint(sx, sy):
                mx, my = self.screen_to_map(sx, sy)
                imx, imy = int(mx), int(my)
                if self.in_bounds(imx, imy) and 0 <= mx - imx < 1 and 0 <= my - imy < 1:
                    self.hover_cell = (imx, imy)
                else:
                    self.hover_cell = None
            else:
                self.hover_cell = None
            if self.drawing:
                if self.door_mode:
                    self.paint_cell(sx, sy, 5 if self.door_dir == "h" else 6)
                elif self.enemy_mode:
                    # 敌人拖拽放置: 每格最多一个
                    mx, my = self.screen_to_map(sx, sy)
                    imx, imy = int(mx), int(my)
                    if self.in_bounds(imx, imy) and self.map_data[imy][imx] == 0:
                        cell = (imx, imy)
                        if cell != self._last_enemy_cell:
                            self.enemies.append({
                                "x": imx + 0.5, "y": imy + 0.5,
                                "kind": self.enemy_kind,
                            })
                            self._last_enemy_cell = cell
                elif self.transition_mode:
                    # 传送门拖拽放置: 每格最多一个
                    mx, my = self.screen_to_map(sx, sy)
                    imx, imy = int(mx), int(my)
                    if self.in_bounds(imx, imy) and self.map_data[imy][imx] == 0:
                        cell = (imx, imy)
                        if cell != self._last_transition_cell:
                            tgt = (self.current_map_idx + 1) % len(self.maps)
                            tx, ty = self._default_target_pos(tgt)
                            self.transitions.append({
                                "x": imx + 0.5, "y": imy + 0.5,
                                "target_map": tgt,
                                "target_x": tx, "target_y": ty,
                            })
                            self._last_transition_cell = cell
                            self._sync_transitions()
                else:
                    self.paint_cell(sx, sy, self.selected_tile)
            elif self.erasing:
                # 特殊模式下不擦除瓦片 (右键拖拽仅用于删除放置物)
                if not (self.enemy_mode or self.transition_mode
                        or self.spawn_mode or self.door_mode):
                    self.paint_cell(sx, sy, 0)

    def _remove_nearest_enemy(self, mx, my, max_dist=0.7):
        """删除距离 (mx,my) 最近的敌人; 距离超过 max_dist 不删。返回是否删除。"""
        if not self.enemies:
            return False
        best_i, best_d = -1, 1e9
        for i, e in enumerate(self.enemies):
            d = (e["x"] - mx) ** 2 + (e["y"] - my) ** 2
            if d < best_d:
                best_d, best_i = d, i
        if best_i >= 0 and best_d <= max_dist * max_dist:
            del self.enemies[best_i]
            return True
        return False

    def _remove_nearest_transition(self, mx, my, max_dist=0.7):
        """删除距离 (mx,my) 最近的传送门; 距离超过 max_dist 不删。返回是否删除。"""
        if not self.transitions:
            return False
        best_i, best_d = -1, 1e9
        for i, t in enumerate(self.transitions):
            d = (t["x"] - mx) ** 2 + (t["y"] - my) ** 2
            if d < best_d:
                best_d, best_i = d, i
        if best_i >= 0 and best_d <= max_dist * max_dist:
            del self.transitions[best_i]
            return True
        return False

    def _cycle_transition_target(self, delta):
        """切换光标处 (或最近) 传送门的目标地图索引。"""
        if not self.transitions or not self.hover_cell:
            return
        hx, hy = self.hover_cell
        for t in self.transitions:
            if int(t["x"]) == hx and int(t["y"]) == hy:
                n = len(self.maps)
                t["target_map"] = (t["target_map"] + delta) % n
                # 同步目标坐标到新目标地图的出生点 (若有)
                tgt_map = self.maps[t["target_map"]]
                sp = tgt_map.get("spawn")
                if sp:
                    t["target_x"] = float(sp["x"])
                    t["target_y"] = float(sp["y"])
                return

    def _default_target_pos(self, target_idx):
        """获取目标地图的默认到达位置: 优先出生点, 否则 (1.5, 1.5)。"""
        tgt = self.maps[target_idx]
        sp = tgt.get("spawn")
        if sp and isinstance(sp, dict) and "x" in sp and "y" in sp:
            return float(sp["x"]), float(sp["y"])
        return 1.5, 1.5

    def _adjust_transition_target_pos(self, dx, dy):
        """用方向键微调光标处传送门的目标到达位置 (每次 0.5 格)。"""
        if not self.transitions or not self.hover_cell:
            return
        hx, hy = self.hover_cell
        for t in self.transitions:
            if int(t["x"]) == hx and int(t["y"]) == hy:
                t["target_x"] = round(t["target_x"] + dx * 0.5, 1)
                t["target_y"] = round(t["target_y"] + dy * 0.5, 1)
                # 钳制到目标地图范围内
                tgt = self.maps[t["target_map"]]
                mw = len(tgt["map"][0])
                mh = len(tgt["map"])
                t["target_x"] = max(0.5, min(mw - 0.5, t["target_x"]))
                t["target_y"] = max(0.5, min(mh - 0.5, t["target_y"]))
                return

    def _get_hovered_transition(self):
        """返回光标所在格上的传送门 dict, 没有则 None。"""
        if not self.transitions or not self.hover_cell:
            return None
        hx, hy = self.hover_cell
        for t in self.transitions:
            if int(t["x"]) == hx and int(t["y"]) == hy:
                return t
        return None

    def _sync_transitions(self):
        """自动配对双向传送门:
        地图A的传送门指向地图B时, 若地图B有传送门指回地图A,
        则互相设定到达点为对方传送门的位置。"""
        for i, map_a in enumerate(self.maps):
            for p1 in map_a.get("transitions", []):
                tb = p1.get("target_map", 0)
                if tb == i or tb >= len(self.maps):
                    continue
                # 在目标地图寻找指回当前地图的最近传送门
                best_p2, best_d = None, 1e9
                for p2 in self.maps[tb].get("transitions", []):
                    if p2.get("target_map") == i:
                        d = (p2["x"] - p1["x"]) ** 2 + (p2["y"] - p1["y"]) ** 2
                        if d < best_d:
                            best_d, best_p2 = d, p2
                if best_p2:
                    p1["target_x"] = best_p2["x"]
                    p1["target_y"] = best_p2["y"]
                    best_p2["target_x"] = p1["x"]
                    best_p2["target_y"] = p1["y"]

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self):
        while True:
            for ev in pygame.event.get():
                self.handle_event(ev)
            self.draw()
            self.clock.tick(FPS)


def main():
    MapEditor().run()


if __name__ == "__main__":
    main()
