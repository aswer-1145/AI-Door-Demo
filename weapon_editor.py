"""
光线投射 Demo - 武器编辑器
编辑 weapons.json, 游戏本体 raycasting_demo.py 启动时自动读取。

操作:
  左键点击武器列表    - 选中武器
  左键拖动滑块        - 调整数值
  滚轮在字段上        - 微调数值
  N                  - 新建武器 (默认飞弹)
  C                  - 复制当前武器
  Delete             - 删除当前武器 (至少保留 1 个)
  S                  - 保存到 weapons.json
  L                  - 从 weapons.json 加载
  1 / 2              - 切换武器类型 (1=近战 melee, 2=飞弹 projectile)
  Tab                - 切换字段聚焦
  ESC                - 退出 (编辑名称时按 ESC 取消编辑)
"""

import copy
import json
import sys
from pathlib import Path

import pygame


# ---------------------------------------------------------------------------
# 视觉常量 (与 map_editor.py 保持一致)
# ---------------------------------------------------------------------------
BG_COLOR = (18, 18, 28)
PANEL_COLOR = (28, 30, 44)
PANEL_HL = (46, 48, 70)
BORDER_COLOR = (90, 95, 140)
TEXT_COLOR = (230, 230, 240)
TEXT_DIM = (150, 150, 170)
ACCENT = (120, 180, 255)
WARN = (255, 120, 80)
MELEE_COL = (220, 200, 80)
PROJ_COL = (255, 120, 80)

LIST_W = 240
UI_TOP_H = 60
UI_BOTTOM_H = 40
FPS = 60

SCRIPT_DIR = Path(__file__).parent
WEAPONS_FILE = SCRIPT_DIR / "weapons.json"


# ---------------------------------------------------------------------------
# 字段定义
#   (key, label, vmin, vmax, step, kind, ftype)
#   kind:  None=所有武器 / "melee" / "projectile"
#   ftype: "number" / "color" / "text"
# ---------------------------------------------------------------------------
FIELDS = [
    ("name",     "名称",            None,  None,  None,  None,         "text"),
    ("damage",   "伤害",            1,     20,    1,     None,         "number"),
    ("range",    "射程/距离(格)",   0.5,   20.0,  0.1,   None,         "number"),
    ("color",    "颜色 RGB",        None,  None,  None,  None,         "color"),
    # 近战专属
    ("arc_deg",       "半锥角(度)",     5,    90,    1,    "melee",     "number"),
    ("swing_time",    "挥击耗时(秒)",   0.1,  1.5,   0.05, "melee",     "number"),
    ("impact_t",      "命中时机(0~1)",  0.1,  0.9,   0.05, "melee",     "number"),
    ("knockback",     "击退系数",       0.0,  3.0,   0.1,  "melee",     "number"),
    # 飞弹专属
    ("speed",         "飞行速度",       1.0,  20.0,  0.5,  "projectile", "number"),
    ("radius",        "碰撞半径",       0.05, 1.0,   0.05, "projectile", "number"),
    ("cooldown",      "冷却(秒)",       0.0,  3.0,   0.05, "projectile", "number"),
    ("splash_radius", "溅射半径",       0.0,  5.0,   0.1,  "projectile", "number"),
]


DEFAULT_MELEE = {
    "id": "hammer",
    "name": "铁锤",
    "type": "melee",
    "damage": 1,
    "range": 2.0,
    "arc_deg": 35,
    "swing_time": 0.35,
    "impact_t": 0.45,
    "knockback": 1.0,
    "color": [220, 200, 80],
}

DEFAULT_PROJECTILE = {
    "id": "fireball",
    "name": "火球",
    "type": "projectile",
    "damage": 2,
    "range": 12.0,
    "speed": 6.0,
    "radius": 0.3,
    "cooldown": 0.6,
    "splash_radius": 1.5,
    "color": [255, 120, 40],
}


def default_data():
    return {
        "selected": "hammer",
        "weapons": [copy.deepcopy(DEFAULT_MELEE), copy.deepcopy(DEFAULT_PROJECTILE)],
    }


def load_data():
    if not WEAPONS_FILE.exists():
        return default_data()
    try:
        data = json.loads(WEAPONS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("weapons"), list):
            return default_data()
        if not data["weapons"]:
            return default_data()
        return data
    except Exception:
        return default_data()


def save_data(data):
    WEAPONS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")


# ---------------------------------------------------------------------------
# 颜色辅助
# ---------------------------------------------------------------------------
def darken(c, f=0.6):
    return tuple(max(0, min(255, int(x * f))) for x in c)


def lighten(c, f=1.3):
    return tuple(max(0, min(255, int(x * f))) for x in c)


def to_tuple(c):
    return tuple(int(x) for x in c)


# ---------------------------------------------------------------------------
# 按钮
# ---------------------------------------------------------------------------
class Button:
    def __init__(self, rect, label, on_click=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.hover = False

    def draw(self, surf, font):
        c = lighten(PANEL_COLOR, 1.15) if self.hover else PANEL_COLOR
        pygame.draw.rect(surf, c, self.rect, border_radius=4)
        pygame.draw.rect(surf, BORDER_COLOR, self.rect, 1, border_radius=4)
        txt = font.render(self.label, True, TEXT_COLOR)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos) and self.on_click:
                self.on_click()
                return True
        return False


# ---------------------------------------------------------------------------
# 字段控件 (统一处理 text / number / color)
# ---------------------------------------------------------------------------
class Field:
    def __init__(self, key, label, vmin, vmax, step, kind, ftype):
        self.key = key
        self.label = label
        self.vmin = vmin
        self.vmax = vmax
        self.step = step
        self.kind = kind          # 武器类型过滤
        self.ftype = ftype        # "number" / "color" / "text"
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.slider_rect = pygame.Rect(0, 0, 0, 0)
        self.color_sliders = [pygame.Rect(0, 0, 0, 0) for _ in range(3)]
        self.dragging = -1        # -1 / "main" / 0,1,2 颜色通道
        self.decimals = 2 if (isinstance(step, float) and step < 1) else 0

    def applies(self, wtype):
        return self.kind is None or self.kind == wtype

    def get_value(self, weapon):
        return weapon.get(self.key, 0)

    def format(self, v):
        if self.decimals > 0:
            return f"{v:.2f}"
        return str(int(v))

    # ---------- 绘制 ----------
    def draw(self, surf, font, font_small, weapon, selected):
        bg = PANEL_HL if selected else PANEL_COLOR
        pygame.draw.rect(surf, bg, self.rect, border_radius=3)
        pygame.draw.rect(surf, BORDER_COLOR, self.rect, 1, border_radius=3)
        lbl = font_small.render(self.label, True, TEXT_COLOR)
        surf.blit(lbl, (self.rect.x + 8, self.rect.y + 4))

        if self.ftype == "text":
            v = weapon.get(self.key, "")
            t = font.render(v, True, ACCENT)
            surf.blit(t, (self.rect.x + 8, self.rect.y + 26))
            return

        if self.ftype == "color":
            self._draw_color(surf, font, font_small, weapon)
            return

        # number
        v = self.get_value(weapon)
        vtext = font.render(self.format(v), True, ACCENT)
        surf.blit(vtext, (self.rect.right - vtext.get_width() - 8, self.rect.y + 4))
        pygame.draw.rect(surf, (15, 15, 25), self.slider_rect, border_radius=2)
        t = (v - self.vmin) / (self.vmax - self.vmin)
        t = max(0, min(1, t))
        fill = self.slider_rect.copy()
        fill.width = int(self.slider_rect.width * t)
        pygame.draw.rect(surf, ACCENT, fill, border_radius=2)
        hx = self.slider_rect.x + int(self.slider_rect.width * t)
        pygame.draw.circle(surf, (240, 240, 250), (hx, self.slider_rect.centery), 6)
        pygame.draw.circle(surf, BORDER_COLOR, (hx, self.slider_rect.centery), 6, 1)

    def _draw_color(self, surf, font, font_small, weapon):
        col = weapon.get(self.key, [200, 200, 200])
        col_t = to_tuple(col)
        # 颜色预览块
        prev_rect = pygame.Rect(self.rect.right - 36, self.rect.y + 6, 28, 18)
        pygame.draw.rect(surf, col_t, prev_rect, border_radius=2)
        pygame.draw.rect(surf, BORDER_COLOR, prev_rect, 1, border_radius=2)
        # 三条 RGB 滑块
        names = ["R", "G", "B"]
        cols = [(255, 80, 80), (80, 255, 80), (80, 120, 255)]
        for i, sl in enumerate(self.color_sliders):
            nlbl = font_small.render(f"{names[i]} {col[i]}", True, TEXT_DIM)
            surf.blit(nlbl, (sl.x, sl.y - 14))
            pygame.draw.rect(surf, (15, 15, 25), sl, border_radius=2)
            t = col[i] / 255
            fill = sl.copy()
            fill.width = int(sl.width * t)
            pygame.draw.rect(surf, cols[i], fill, border_radius=2)
            hx = sl.x + int(sl.width * t)
            pygame.draw.circle(surf, (240, 240, 250), (hx, sl.centery), 5)
            pygame.draw.circle(surf, BORDER_COLOR, (hx, sl.centery), 5, 1)

    # ---------- 事件 ----------
    def handle_event(self, ev, weapon):
        if self.ftype == "color":
            return self._handle_color(ev, weapon)
        if self.ftype == "text":
            return False  # 由编辑器主类处理
        # number
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.slider_rect.collidepoint(ev.pos):
                self.dragging = "main"
                self._set_num_from_x(ev.pos[0], weapon)
                return True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.dragging == "main":
                self.dragging = -1
        elif ev.type == pygame.MOUSEMOTION and self.dragging == "main":
            self._set_num_from_x(ev.pos[0], weapon)
            return True
        elif ev.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                v = self.get_value(weapon)
                v += ev.y * self.step
                v = max(self.vmin, min(self.vmax, v))
                weapon[self.key] = round(v, 3)
                return True
        return False

    def _handle_color(self, ev, weapon):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, sl in enumerate(self.color_sliders):
                if sl.collidepoint(ev.pos):
                    self.dragging = i
                    self._set_col_from_x(ev.pos[0], i, weapon)
                    return True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.dragging >= 0:
                self.dragging = -1
        elif ev.type == pygame.MOUSEMOTION and self.dragging >= 0:
            self._set_col_from_x(ev.pos[0], self.dragging, weapon)
            return True
        elif ev.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                col = list(weapon.get(self.key, [200, 200, 200]))
                # 调整最接近鼠标的通道
                mx, my = pygame.mouse.get_pos()
                nearest, best_d = 0, 1e9
                for i, sl in enumerate(self.color_sliders):
                    d = abs(sl.centery - my)
                    if d < best_d:
                        best_d, nearest = d, i
                col[nearest] = max(0, min(255, col[nearest] + ev.y * 5))
                weapon[self.key] = col
                return True
        return False

    def _set_num_from_x(self, mx, weapon):
        t = (mx - self.slider_rect.x) / max(1, self.slider_rect.width)
        t = max(0, min(1, t))
        v = self.vmin + t * (self.vmax - self.vmin)
        if self.step:
            v = round(v / self.step) * self.step
        weapon[self.key] = round(v, 3)

    def _set_col_from_x(self, mx, channel, weapon):
        sl = self.color_sliders[channel]
        t = (mx - sl.x) / max(1, sl.width)
        t = max(0, min(1, t))
        v = int(round(t * 255))
        col = list(weapon.get(self.key, [200, 200, 200]))
        col[channel] = v
        weapon[self.key] = col


# ---------------------------------------------------------------------------
# 编辑器主类
# ---------------------------------------------------------------------------
class WeaponEditor:
    def __init__(self):
        pygame.init()
        self.screen_w = 1100
        self.screen_h = 720
        self.screen = pygame.display.set_mode((self.screen_w, self.screen_h),
                                              pygame.RESIZABLE)
        pygame.display.set_caption("Raycaster 武器编辑器  -  S 保存 / L 加载 / N 新建 / C 复制 / Del 删除 / 1,2 类型")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("microsoftyahei,msyh,consolas", 14)
        self.font_big = pygame.font.SysFont("microsoftyahei,msyh,consolas", 18, bold=True)
        self.font_field = pygame.font.SysFont("microsoftyahei,msyh,consolas", 16, bold=True)

        self.data = load_data()
        self.selected_idx = 0
        sel_id = self.data.get("selected")
        if sel_id:
            for i, w in enumerate(self.data["weapons"]):
                if w.get("id") == sel_id:
                    self.selected_idx = i
                    break

        self.fields = [Field(*f) for f in FIELDS]
        self.focus_field = None
        self.name_editing = False
        self.name_buffer = ""

        self.action_buttons = []
        self.type_buttons = []   # [(rect, wtype, label)]
        self._rebuild_buttons()

    # ---------- 数据访问 ----------
    @property
    def weapons(self):
        return self.data["weapons"]

    @property
    def current(self):
        if 0 <= self.selected_idx < len(self.weapons):
            return self.weapons[self.selected_idx]
        return None

    # ---------- 按钮 ----------
    def _rebuild_buttons(self):
        h = 34
        y = 12
        x = LIST_W + 12
        w = 100
        self.action_buttons = []
        items = [
            ("新建 N", self.action_new),
            ("复制 C", self.action_dup),
            ("删除 Del", self.action_del),
            ("保存 S", self.action_save),
            ("加载 L", self.action_load),
            ("退出", self.action_quit),
        ]
        for i, (lbl, cb) in enumerate(items):
            self.action_buttons.append(Button((x + i * (w + 8), y, w, h), lbl, cb))

    # ---------- 动作 ----------
    def action_new(self):
        w = copy.deepcopy(DEFAULT_PROJECTILE)
        w["id"] = f"weapon_{len(self.weapons) + 1}"
        w["name"] = f"武器 {len(self.weapons) + 1}"
        self.weapons.append(w)
        self.selected_idx = len(self.weapons) - 1
        self.name_editing = False

    def action_dup(self):
        if not self.current:
            return
        w = copy.deepcopy(self.current)
        w["id"] = w.get("id", "weapon") + "_copy"
        w["name"] = w.get("name", "?") + " 副本"
        self.weapons.append(w)
        self.selected_idx = len(self.weapons) - 1

    def action_del(self):
        if len(self.weapons) <= 1:
            return
        del self.weapons[self.selected_idx]
        self.selected_idx = max(0, self.selected_idx - 1)

    def action_save(self):
        if self.current:
            self.data["selected"] = self.current.get("id")
        save_data(self.data)

    def action_load(self):
        self.data = load_data()
        self.selected_idx = 0
        sel_id = self.data.get("selected")
        if sel_id:
            for i, w in enumerate(self.data["weapons"]):
                if w.get("id") == sel_id:
                    self.selected_idx = i
                    break
        self.name_editing = False

    def action_quit(self):
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    def set_type(self, wtype):
        if not self.current or self.current.get("type") == wtype:
            return
        self.current["type"] = wtype
        if wtype == "melee":
            for k, v in DEFAULT_MELEE.items():
                if k not in self.current:
                    self.current[k] = copy.deepcopy(v)
            for k in ("speed", "radius", "cooldown", "splash_radius"):
                self.current.pop(k, None)
        else:
            for k, v in DEFAULT_PROJECTILE.items():
                if k not in self.current:
                    self.current[k] = copy.deepcopy(v)
            for k in ("arc_deg", "swing_time", "impact_t", "knockback"):
                self.current.pop(k, None)

    # ---------- 事件 ----------
    def handle_event(self, ev):
        # 顶部按钮
        if ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            for b in self.action_buttons:
                if b.handle_event(ev):
                    return
        # 类型按钮
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, wtype, _ in self.type_buttons:
                if rect.collidepoint(ev.pos):
                    self.set_type(wtype)
                    return

        if ev.type == pygame.QUIT:
            pygame.quit(); sys.exit(0)

        elif ev.type == pygame.KEYDOWN:
            if self.name_editing:
                # 名称编辑模式
                if ev.key == pygame.K_RETURN:
                    if self.current is not None:
                        self.current["name"] = self.name_buffer or "未命名"
                    self.name_editing = False
                elif ev.key == pygame.K_ESCAPE:
                    self.name_editing = False
                elif ev.key == pygame.K_BACKSPACE:
                    self.name_buffer = self.name_buffer[:-1]
                elif ev.unicode and ev.unicode.isprintable():
                    self.name_buffer += ev.unicode
                return

            if ev.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit(0)
            elif ev.key == pygame.K_n:
                self.action_new()
            elif ev.key == pygame.K_c:
                self.action_dup()
            elif ev.key == pygame.K_DELETE:
                self.action_del()
            elif ev.key == pygame.K_s:
                self.action_save()
            elif ev.key == pygame.K_l:
                self.action_load()
            elif ev.key == pygame.K_1:
                self.set_type("melee")
            elif ev.key == pygame.K_2:
                self.set_type("projectile")
            elif ev.key == pygame.K_TAB:
                visible = [i for i, f in enumerate(self.fields)
                           if self.current and f.applies(self.current.get("type"))]
                if visible:
                    if self.focus_field is None or self.focus_field not in visible:
                        self.focus_field = visible[0]
                    else:
                        idx = visible.index(self.focus_field)
                        self.focus_field = visible[(idx + 1) % len(visible)]

        elif ev.type == pygame.MOUSEWHEEL:
            if self.current is not None:
                for f in self.fields:
                    if f.handle_event(ev, self.current):
                        return

        elif ev.type == pygame.VIDEORESIZE:
            self.screen_w, self.screen_h = ev.w, ev.h
            self.screen = pygame.display.set_mode((self.screen_w, self.screen_h),
                                                  pygame.RESIZABLE)
            self._rebuild_buttons()

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # 武器列表点击
            list_rect = pygame.Rect(0, UI_TOP_H, LIST_W,
                                    self.screen_h - UI_TOP_H - UI_BOTTOM_H)
            if list_rect.collidepoint(ev.pos):
                item_h = 56
                idx = (ev.pos[1] - UI_TOP_H - 8) // item_h
                if 0 <= idx < len(self.weapons):
                    self.selected_idx = int(idx)
                    self.name_editing = False
                return
            if self.current is None:
                return
            # 字段点击
            for i, f in enumerate(self.fields):
                if f.rect.width == 0:
                    continue
                if f.rect.collidepoint(ev.pos):
                    self.focus_field = i
                    if f.ftype == "text":
                        self.name_editing = True
                        self.name_buffer = self.current.get("name", "")
                    if f.handle_event(ev, self.current):
                        return
                    return
            # 滑块拖动 (字段已布局)
            for f in self.fields:
                if f.handle_event(ev, self.current):
                    return

        elif ev.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if self.current is None:
                return
            for f in self.fields:
                if f.handle_event(ev, self.current):
                    return

    # ---------- 布局 ----------
    def _layout_fields(self):
        area_x = LIST_W + 12
        area_y = UI_TOP_H + 12
        area_w = self.screen_w - LIST_W - 24
        y = area_y + 110  # 顶部留给类型按钮+预览
        for f in self.fields:
            if not (self.current and f.applies(self.current.get("type"))):
                f.rect.size = (0, 0)
                f.slider_rect.size = (0, 0)
                for sl in f.color_sliders:
                    sl.size = (0, 0)
                continue
            if f.ftype == "color":
                f.rect = pygame.Rect(area_x, y, area_w, 80)
                sw = (area_w - 90) // 3
                for i in range(3):
                    f.color_sliders[i] = pygame.Rect(area_x + 80 + i * (sw + 8),
                                                    y + 36, sw, 12)
                y += 86
            elif f.ftype == "text":
                f.rect = pygame.Rect(area_x, y, area_w, 50)
                y += 56
            else:  # number
                f.rect = pygame.Rect(area_x, y, area_w, 50)
                f.slider_rect = pygame.Rect(area_x + 12, y + 30, area_w - 24, 10)
                y += 56

    # ---------- 绘制 ----------
    def _draw_topbar(self, surf):
        rect = pygame.Rect(LIST_W, 0, self.screen_w - LIST_W, UI_TOP_H)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (LIST_W, UI_TOP_H - 1),
                         (self.screen_w, UI_TOP_H - 1), 1)
        for b in self.action_buttons:
            b.draw(surf, self.font)

    def _draw_bottombar(self, surf):
        y0 = self.screen_h - UI_BOTTOM_H
        rect = pygame.Rect(LIST_W, y0, self.screen_w - LIST_W, UI_BOTTOM_H)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (LIST_W, y0), (self.screen_w, y0), 1)
        if self.current:
            cur = f"[{self.current.get('type','')}] {self.current.get('name','')}  |  "
        else:
            cur = ""
        info = (cur + f"武器 {self.selected_idx+1}/{len(self.weapons)}  |  "
                f"1=近战  2=飞弹  |  Tab=切字段  |  滚轮=微调  |  S保存 L加载")
        t = self.font.render(info, True, TEXT_DIM)
        surf.blit(t, (LIST_W + 12, y0 + (UI_BOTTOM_H - t.get_height()) // 2))

    def _draw_list(self, surf):
        rect = pygame.Rect(0, 0, LIST_W, self.screen_h)
        pygame.draw.rect(surf, PANEL_COLOR, rect)
        pygame.draw.line(surf, BORDER_COLOR, (LIST_W - 1, 0),
                         (LIST_W - 1, self.screen_h), 1)
        title = self.font_big.render("武器列表", True, TEXT_COLOR)
        surf.blit(title, (16, 18))
        hint = self.font.render("点击选中  N新建  Del删除", True, TEXT_DIM)
        surf.blit(hint, (16, 40))
        item_h = 56
        y = UI_TOP_H + 8
        for i, w in enumerate(self.weapons):
            r = pygame.Rect(8, y, LIST_W - 16, item_h - 6)
            bg = PANEL_HL if i == self.selected_idx else (
                PANEL_COLOR if i % 2 == 0 else (32, 34, 50))
            pygame.draw.rect(surf, bg, r, border_radius=4)
            if i == self.selected_idx:
                pygame.draw.rect(surf, ACCENT, r, 2, border_radius=4)
            # 颜色块
            col = to_tuple(w.get("color", [200, 200, 200]))
            pygame.draw.rect(surf, col, (r.x + 8, r.y + 8, 14, 14), border_radius=2)
            pygame.draw.rect(surf, BORDER_COLOR, (r.x + 8, r.y + 8, 14, 14), 1, border_radius=2)
            # 类型标签
            is_melee = w.get("type") == "melee"
            type_tag = "近战" if is_melee else "飞弹"
            tcol = MELEE_COL if is_melee else PROJ_COL
            ttag = self.font.render(type_tag, True, tcol)
            surf.blit(ttag, (r.right - ttag.get_width() - 8, r.y + 8))
            # 名称
            n = self.font_big.render(w.get("name", "?"), True, TEXT_COLOR)
            surf.blit(n, (r.x + 28, r.y + 6))
            # id + 伤害
            sub = self.font.render(f"id={w.get('id','?')}  伤={w.get('damage',0)}",
                                   True, TEXT_DIM)
            surf.blit(sub, (r.x + 28, r.y + 28))
            y += item_h

    def _draw_editor(self, surf):
        area_x = LIST_W + 12
        area_y = UI_TOP_H + 12
        area_w = self.screen_w - LIST_W - 24

        # 类型按钮
        self.type_buttons = []
        bw, bh = 150, 40
        for i, (wtype, label) in enumerate([("melee", "1 近战 (melee)"),
                                             ("projectile", "2 飞弹 (projectile)")]):
            r = pygame.Rect(area_x + i * (bw + 8), area_y, bw, bh)
            cur = self.current.get("type") == wtype
            bg = ACCENT if cur else PANEL_COLOR
            fg = (20, 20, 30) if cur else TEXT_COLOR
            pygame.draw.rect(surf, bg, r, border_radius=4)
            pygame.draw.rect(surf, BORDER_COLOR, r, 1, border_radius=4)
            t = self.font.render(label, True, fg)
            surf.blit(t, t.get_rect(center=r.center))
            self.type_buttons.append((r, wtype, label))

        # 颜色预览圆
        px = area_x + area_w - 40
        py = area_y + 22
        col = to_tuple(self.current.get("color", [200, 200, 200]))
        pygame.draw.circle(surf, darken(col, 0.5), (px, py), 22)
        pygame.draw.circle(surf, col, (px, py), 18)
        pygame.draw.circle(surf, lighten(col, 1.3), (px, py), 10)
        pygame.draw.circle(surf, BORDER_COLOR, (px, py), 22, 1)

        # 字段
        for i, f in enumerate(self.fields):
            if f.rect.width == 0:
                continue
            selected = (i == self.focus_field)
            if f.ftype == "text" and self.name_editing and selected:
                # 名称编辑态: 特殊绘制
                bg = PANEL_HL
                pygame.draw.rect(surf, bg, f.rect, border_radius=3)
                pygame.draw.rect(surf, WARN, f.rect, 2, border_radius=3)
                lbl = self.font.render("名称 (回车确认, ESC取消)", True, WARN)
                surf.blit(lbl, (f.rect.x + 8, f.rect.y + 4))
                t = self.font_field.render(self.name_buffer + "_", True, ACCENT)
                surf.blit(t, (f.rect.x + 8, f.rect.y + 26))
            else:
                f.draw(surf, self.font_field, self.font, self.current, selected)

    def draw(self):
        self.screen.fill(BG_COLOR)
        if self.current is None:
            t = self.font_big.render("没有武器, 按 N 新建", True, TEXT_DIM)
            self.screen.blit(t, (self.screen_w // 2 - t.get_width() // 2,
                                 self.screen_h // 2))
        else:
            self._layout_fields()
            self._draw_editor(self.screen)
        self._draw_list(self.screen)
        self._draw_topbar(self.screen)
        self._draw_bottombar(self.screen)
        pygame.display.flip()

    def run(self):
        while True:
            for ev in pygame.event.get():
                if self.current is None:
                    if ev.type == pygame.QUIT:
                        pygame.quit(); sys.exit(0)
                    elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE,
                                                                   pygame.K_n):
                        if ev.key == pygame.K_ESCAPE:
                            pygame.quit(); sys.exit(0)
                        else:
                            self.action_new()
                else:
                    self.handle_event(ev)
            self.draw()
            self.clock.tick(FPS)


def main():
    WeaponEditor().run()


if __name__ == "__main__":
    main()
