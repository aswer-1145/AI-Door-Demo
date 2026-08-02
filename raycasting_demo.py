"""
伪3D光线投射演示 (Raycasting Demo)
基于 DDA 算法，类似 Wolfenstein 3D 的渲染方式。
支持多地图: 走入传送门自动切换到目标地图。

控制方式:
  ↑ / ↓  - 前进 / 后退
  ← / →  - 右移 / 左移 (平移)
  A / D  - 右转 / 左转
  SPACE  - 范围内开门, 否则使用当前武器 (近战挥击 / 飞弹发射)
  1~9    - 切换武器 (按 weapons.json 中顺序)
  E      - 生成敌人
  ESC    - 退出
"""

import json
import math
import random
import sys
from pathlib import Path

import pygame

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
SCREEN_W = 960
SCREEN_H = 600
FPS = 60

# 共享地图文件 (与 map_editor.py 共用, 编辑器保存后游戏自动读取)
MAP_FILE = Path(__file__).parent / "map.json"

# 共享武器配置 (与 weapon_editor.py 共用)
WEAPONS_FILE = Path(__file__).parent / "weapons.json"


def _default_weapons():
    """weapons.json 缺失或损坏时的内置默认武器。"""
    return [
        {"id": "hammer", "name": "铁锤", "type": "melee", "damage": 1,
         "range": 2.0, "arc_deg": 35, "swing_time": 0.35, "impact_t": 0.45,
         "knockback": 1.0, "color": (220, 200, 80)},
        {"id": "fireball", "name": "火球", "type": "projectile", "damage": 2,
         "range": 12.0, "speed": 6.0, "radius": 0.3, "cooldown": 0.6,
         "splash_radius": 1.5, "color": (255, 120, 40)},
    ]


def load_weapons():
    """从 weapons.json 加载武器配置, 失败回退到内置默认。"""
    try:
        if not WEAPONS_FILE.exists():
            return _default_weapons()
        data = json.loads(WEAPONS_FILE.read_text(encoding="utf-8"))
        wlist = data.get("weapons") if isinstance(data, dict) else None
        if not isinstance(wlist, list) or not wlist:
            return _default_weapons()
        result = []
        for w in wlist:
            if not isinstance(w, dict) or "type" not in w:
                continue
            ww = dict(w)
            col = ww.get("color")
            if isinstance(col, list):
                ww["color"] = tuple(int(x) for x in col)
            result.append(ww)
        return result if result else _default_weapons()
    except Exception:
        return _default_weapons()


def load_selected_weapon_idx():
    """读取 weapons.json 的 selected 字段, 返回应在 WEAPONS 中选中的索引。"""
    try:
        if WEAPONS_FILE.exists():
            data = json.loads(WEAPONS_FILE.read_text(encoding="utf-8"))
            sel_id = data.get("selected") if isinstance(data, dict) else None
            if sel_id:
                for i, w in enumerate(WEAPONS):
                    if w.get("id") == sel_id:
                        return i
    except Exception:
        pass
    return 0


# 武器配置 (启动时加载, 后续游戏逻辑从这里取参数)
WEAPONS = load_weapons()

# 内置默认地图: 1=普通墙, 2=红墙, 3=绿墙, 4=蓝墙, 0=空地
# 仅在 map.json 不存在时作为回退使用
DEFAULT_MAP = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 1],
    [1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
]


def _parse_single_map(data):
    """从 JSON 数据解析单张地图, 返回 dict 或 None。"""
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
    result = {"name": data.get("name", "地图") if isinstance(data, dict) else "地图",
              "map": m}
    if isinstance(data, dict):
        for key in ("spawn", "enemies", "transitions"):
            if key in data:
                result[key] = data[key]
    return result


def load_all_maps():
    """从 map.json 加载所有地图; 向后兼容单地图格式。
    返回 [{"name","map","spawn"?,"enemies"?,"transitions"?}, ...]"""
    try:
        if MAP_FILE.exists():
            data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
            # 多地图格式
            if isinstance(data, dict) and "maps" in data:
                raw = data["maps"]
                if isinstance(raw, list) and raw:
                    result = []
                    for i, m in enumerate(raw):
                        parsed = _parse_single_map(m)
                        if parsed:
                            if "name" not in parsed or parsed["name"] == "地图":
                                parsed["name"] = f"地图 {i + 1}"
                            result.append(parsed)
                    if result:
                        print(f"已从 {MAP_FILE.name} 加载 {len(result)} 张地图")
                        return result
            # 单地图格式 (向后兼容)
            single = _parse_single_map(data)
            if single:
                print(f"已从 {MAP_FILE.name} 加载 1 张地图 (单地图格式)")
                return [single]
        else:
            print(f"未找到 {MAP_FILE.name}, 使用内置默认地图")
    except Exception as exc:
        print(f"加载地图失败 ({exc}), 使用内置默认地图")
    return [{"name": "地图 1", "map": DEFAULT_MAP}]


# 所有地图数据 (启动时加载)
ALL_MAPS = load_all_maps()
current_map_idx = 0

MAP = ALL_MAPS[0]["map"]
MAP_W = len(MAP[0])
MAP_H = len(MAP)


def load_spawn_from_map(map_data):
    """从指定地图 dict 读取玩家出生点; 不存在时返回 None。"""
    sp = map_data.get("spawn")
    if sp and isinstance(sp, dict) and "x" in sp and "y" in sp:
        x, y = float(sp["x"]), float(sp["y"])
        mw = len(map_data["map"][0])
        mh = len(map_data["map"])
        if 0 <= int(x) < mw and 0 <= int(y) < mh:
            if map_data["map"][int(y)][int(x)] == 0:
                return x, y
    return None


SPAWN_POINT = load_spawn_from_map(ALL_MAPS[0])


def load_enemies_from_map(map_data):
    """从指定地图 dict 读取敌人列表; 格式错时返回空列表。
    格式: [{"x":1.5,"y":1.5,"kind":"grunt"}, ...]"""
    raw = map_data.get("enemies")
    if not isinstance(raw, list):
        return []
    m = map_data["map"]
    mw = len(m[0])
    mh = len(m)
    result = []
    for e in raw:
        if (isinstance(e, dict) and "x" in e and "y" in e
                and e.get("kind") in ENEMY_TYPES):
            x, y = float(e["x"]), float(e["y"])
            if 0 <= int(x) < mw and 0 <= int(y) < mh and m[int(y)][int(x)] == 0:
                result.append((x, y, e["kind"]))
    return result


def load_transitions_from_map(map_data):
    """从指定地图 dict 读取传送门列表; 格式错时返回空列表。
    格式: [{"x":14.5,"y":6.5,"target_map":1,"target_x":1.5,"target_y":6.5}, ...]"""
    raw = map_data.get("transitions")
    if not isinstance(raw, list):
        return []
    result = []
    for t in raw:
        if (isinstance(t, dict) and "x" in t and "y" in t
                and "target_map" in t):
            result.append({
                "x": float(t["x"]), "y": float(t["y"]),
                "target_map": int(t["target_map"]),
                "target_x": float(t.get("target_x", t["x"])),
                "target_y": float(t.get("target_y", t["y"])),
            })
    return result


# 启动时从第一张地图加载传送门 (敌人需要在 ENEMY_TYPES 定义之后加载)
INITIAL_TRANSITIONS = load_transitions_from_map(ALL_MAPS[0])


def switch_map(idx, target_x, target_y):
    """切换到指定地图, 返回 (doors, enemies, transitions)。
    重新赋值 MAP/MAP_W/MAP_H 全局变量。"""
    global MAP, MAP_W, MAP_H, current_map_idx
    if idx < 0 or idx >= len(ALL_MAPS):
        return None, None, None
    current_map_idx = idx
    m = ALL_MAPS[idx]
    MAP = m["map"]
    MAP_W = len(MAP[0])
    MAP_H = len(MAP)
    doors = init_doors()
    enemies = []
    for ex, ey, ekind in load_enemies_from_map(m):
        if len(enemies) >= MAX_ENEMIES:
            break
        if math.hypot(ex - target_x, ey - target_y) < 1.5:
            continue
        enemies.append(make_enemy(ekind, ex, ey))
    transitions = load_transitions_from_map(m)
    print(f"切换到 {m.get('name', '地图 '+str(idx+1))} ({MAP_W}x{MAP_H}), "
          f"敌人 {len(enemies)}, 传送门 {len(transitions)}")
    return doors, enemies, transitions


def init_doors():
    """扫描 MAP, 为所有门扉瓦片(5/6)创建状态字典。
    返回 {(mx,my): {"type":5/6, "open":0.0, "want_open":False}}。
    want_open 由玩家在范围内按 SPACE 置 True; 玩家离开范围后自动关门。"""
    doors = {}
    for my in range(MAP_H):
        for mx in range(MAP_W):
            if MAP[my][mx] in DOOR_TILES:
                doors[(mx, my)] = {"type": MAP[my][mx], "open": 0.0, "want_open": False}
    return doors


def update_doors(doors, pos_x, pos_y, dt):
    """门扉动画: 不再按距离自动开门。玩家离开范围时自动关门, 在范围内按 SPACE 才开门 (want_open 由按键设置)。"""
    for (mx, my), d in doors.items():
        dist = math.hypot(mx + 0.5 - pos_x, my + 0.5 - pos_y)
        if dist >= DOOR_OPEN_DIST:
            d["want_open"] = False
        target = 1.0 if d["want_open"] else 0.0
        diff = target - d["open"]
        d["open"] += max(-DOOR_SPEED * dt, min(DOOR_SPEED * dt, diff))
        d["open"] = max(0.0, min(1.0, d["open"]))


def nearest_door_in_range(doors, pos_x, pos_y):
    """返回范围内、尚未请求开启的最近门扉 key (mx,my), 没有则返回 None。用于 SPACE 开门与提示。"""
    best_key = None
    best_dist = DOOR_OPEN_DIST
    for (mx, my), d in doors.items():
        if d["want_open"]:
            continue
        dist = math.hypot(mx + 0.5 - pos_x, my + 0.5 - pos_y)
        if dist < best_dist:
            best_dist = dist
            best_key = (mx, my)
    return best_key

# 墙壁颜色 (R, G, B)
WALL_COLORS = {
    1: (180, 180, 180),
    2: (200,  60,  60),
    3: ( 60, 200,  60),
    4: ( 60,  60, 200),
    5: (160, 110,  50),   # 横向门扉 (棕色)
    6: (110, 160,  50),   # 纵向门扉 (黄绿)
}

DOOR_TILES = {5, 6}       # 门扉瓦片类型
DOOR_OPEN_DIST = 2.5      # 门扉交互范围: 在此距离内按 SPACE 可开门, 离开后自动关门
DOOR_SPEED = 2.0          # 门扉开关速度 (open值每秒变化量)

# 玩家初始状态
POS_X, POS_Y = 3.5, 3.5
DIR_X, DIR_Y = 1.0, 0.0
PLANE_X, PLANE_Y = 0.0, 0.66

MOVE_SPEED = 3.5
ROT_SPEED = 2.2

# 小地图
MINIMAP_SCALE = 12
MINIMAP_X = 10
MINIMAP_Y = 10

# 锤子 / 战斗
HAMMER_SWING_TIME = 0.35       # 一次挥击耗时(秒)
HAMMER_IMPACT_T = 0.45         # 伤害判定时机 (0~1, 挥击进度)
ATTACK_RANGE = 2.0             # 攻击距离(格)
ATTACK_HALF_ANGLE = math.radians(35)  # 攻击半锥角

# 敌人种类配置
#   sight=True   需要视野(墙遮挡则丢失追击)
#   pathfind=True 长线追踪, 遇墙 BFS 绕路 (不会卡墙)
ENEMY_TYPES = {
    "grunt": {   # 普通红幽灵: 视野追击, 中速中血
        "hp": 3, "speed": 1.2,
        "color": (190, 50, 50), "outline": (120, 20, 20),
        "scale": 1.0, "knockback": 0.7, "score": 10,
        "sight": True, "pathfind": False,
    },
    "sprite": {  # 黄色快速小怪: 视野追击, 高速低血
        "hp": 1, "speed": 2.4,
        "color": (235, 205, 70), "outline": (160, 130, 20),
        "scale": 0.8, "knockback": 1.0, "score": 15,
        "sight": True, "pathfind": False,
    },
    "brute": {   # 紫色厚血大怪: 长线追踪+绕路, 慢速高血
        "hp": 6, "speed": 0.85,
        "color": (150, 70, 180), "outline": (90, 30, 110),
        "scale": 1.35, "knockback": 0.35, "score": 30,
        "sight": False, "pathfind": True,
    },
}
MAX_ENEMIES = 20
ENEMY_SIGHT_DIST = 8.0        # 视野型敌人最大视距
ENEMY_HIT_FLASH = 0.18        # 受击红闪时长(秒)
ENEMY_DEATH_TIME = 0.5        # 死亡淡出动画时长(秒)
ENEMY_REPATH_INTERVAL = 0.5   # 绕路型敌人重算路径间隔(秒)
ENEMY_KNOCKBACK_DECAY = 7.0   # 击退速度衰减(每秒)
HAMMER_DAMAGE = 1             # 锤子单次伤害

# 启动时从第一张地图加载预放置敌人 (必须在 ENEMY_TYPES 定义之后)
INITIAL_ENEMIES = load_enemies_from_map(ALL_MAPS[0])


# ---------------------------------------------------------------------------
# 资源预渲染
# ---------------------------------------------------------------------------
def make_enemy_sprite(kind="grunt", size=64):
    """生成敌人精灵表面。kind: grunt(红幽灵)/sprite(黄快速)/brute(紫厚血)。"""
    cfg = ENEMY_TYPES[kind]
    body = cfg["color"]
    outline = cfg["outline"]
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    if kind == "brute":
        # 厚血大怪: 更宽的椭圆 + 双角 + 凶恶眼神
        pygame.draw.ellipse(surf, body, (4, 14, size - 8, size - 18))
        pygame.draw.ellipse(surf, outline, (4, 14, size - 8, size - 18), 3)
        # 双角
        pygame.draw.polygon(surf, outline,
                            [(14, 16), (10, 2), (22, 14)])
        pygame.draw.polygon(surf, outline,
                            [(size - 14, 16), (size - 10, 2), (size - 22, 14)])
        # 底部波浪 (更大)
        for i in range(3):
            bx = 6 + i * 20
            pygame.draw.arc(surf, body, (bx, size - 22, 18, 18),
                            math.pi, 2 * math.pi, 0)
        # 眼睛 (发红)
        ey = size // 2 - 4
        pygame.draw.circle(surf, (255, 240, 200), (size // 2 - 11, ey), 7)
        pygame.draw.circle(surf, (255, 240, 200), (size // 2 + 11, ey), 7)
        pygame.draw.circle(surf, (255, 60, 40), (size // 2 - 9, ey), 4)
        pygame.draw.circle(surf, (255, 60, 40), (size // 2 + 13, ey), 4)
        # 獠牙
        pygame.draw.polygon(surf, (240, 240, 230),
                            [(size // 2 - 7, ey + 12), (size // 2 - 9, ey + 22), (size // 2 - 4, ey + 14)])
        pygame.draw.polygon(surf, (240, 240, 230),
                            [(size // 2 + 7, ey + 12), (size // 2 + 9, ey + 22), (size // 2 + 4, ey + 14)])
    elif kind == "sprite":
        # 快速小怪: 更小更窄, 尖顶, 黄色
        pygame.draw.ellipse(surf, body, (10, 12, size - 20, size - 16))
        pygame.draw.ellipse(surf, outline, (10, 12, size - 20, size - 16), 2)
        # 尹尖顶
        pygame.draw.polygon(surf, body,
                            [(size // 2, 4), (size // 2 - 8, 16), (size // 2 + 8, 16)])
        pygame.draw.polygon(surf, outline,
                            [(size // 2, 4), (size // 2 - 8, 16), (size // 2 + 8, 16)], 2)
        # 底部波浪 (细密)
        for i in range(4):
            bx = 10 + i * 12
            pygame.draw.arc(surf, body, (bx, size - 18, 12, 12),
                            math.pi, 2 * math.pi, 0)
        # 眼睛 (小, 斜视)
        ey = size // 2 - 4
        pygame.draw.circle(surf, (40, 30, 10), (size // 2 - 7, ey), 3)
        pygame.draw.circle(surf, (40, 30, 10), (size // 2 + 7, ey), 3)
        # 嘴 (尖牙)
        pygame.draw.polygon(surf, (40, 30, 10),
                            [(size // 2 - 5, ey + 8), (size // 2, ey + 14), (size // 2 + 5, ey + 8)])
    else:
        # grunt 普通红幽灵
        pygame.draw.ellipse(surf, body, (6, 10, size - 12, size - 16))
        pygame.draw.ellipse(surf, outline, (6, 10, size - 12, size - 16), 2)
        # 底部波浪
        for i in range(3):
            bx = 8 + i * 18
            pygame.draw.arc(surf, body, (bx, size - 20, 16, 16),
                            math.pi, 2 * math.pi, 0)
        # 眼睛
        ey = size // 2 - 6
        pygame.draw.circle(surf, (255, 255, 255), (size // 2 - 9, ey), 6)
        pygame.draw.circle(surf, (255, 255, 255), (size // 2 + 9, ey), 6)
        pygame.draw.circle(surf, (20, 20, 20), (size // 2 - 7, ey), 3)
        pygame.draw.circle(surf, (20, 20, 20), (size // 2 + 11, ey), 3)
        # 嘴巴
        pygame.draw.arc(surf, (20, 20, 20),
                        (size // 2 - 10, ey + 4, 20, 14),
                        math.pi, 2 * math.pi, 3)
    return surf


def make_enemy_sprites(size=64):
    """预渲染三种敌人精灵, 返回 {kind: Surface}。"""
    return {k: make_enemy_sprite(k, size) for k in ENEMY_TYPES}


def make_hammer_surface():
    """预渲染锤子图像。"""
    w, h = 70, 150
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    # 握柄
    pygame.draw.rect(surf, (150, 100, 55), (30, 35, 10, 115))
    pygame.draw.rect(surf, (95, 65, 30), (30, 35, 10, 115), 2)
    # 锤头
    pygame.draw.rect(surf, (175, 175, 185), (8, 8, 54, 30))
    pygame.draw.rect(surf, (100, 100, 115), (8, 8, 54, 30), 2)
    # 高光
    pygame.draw.line(surf, (215, 215, 225), (10, 10), (60, 10), 2)
    pygame.draw.line(surf, (215, 215, 225), (10, 10), (10, 34), 2)
    return surf


# ---------------------------------------------------------------------------
# 渲染: 墙壁
# ---------------------------------------------------------------------------
def cast_rays(surface, z_buffer, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y, doors=None):
    """对屏幕每一列发射射线，用 DDA 算法找到墙壁并绘制竖条，同时填充 z_buffer。
    支持门扉: 门扉瓦片(5/6)的墙壁在格子中心, 按open值滑动, 射线可穿过开启部分。"""
    for x in range(SCREEN_W):
        camera_x = 2.0 * x / SCREEN_W - 1.0
        ray_dx = dir_x + plane_x * camera_x
        ray_dy = dir_y + plane_y * camera_x

        map_x = int(pos_x)
        map_y = int(pos_y)

        delta_x = abs(1.0 / ray_dx) if ray_dx != 0 else 1e30
        delta_y = abs(1.0 / ray_dy) if ray_dy != 0 else 1e30

        if ray_dx < 0:
            step_x = -1
            side_dist_x = (pos_x - map_x) * delta_x
        else:
            step_x = 1
            side_dist_x = (map_x + 1.0 - pos_x) * delta_x

        if ray_dy < 0:
            step_y = -1
            side_dist_y = (pos_y - map_y) * delta_y
        else:
            step_y = 1
            side_dist_y = (map_y + 1.0 - pos_y) * delta_y

        hit = False
        side = 0
        door_hit = False
        perp_dist = 1e30

        while not hit:
            if side_dist_x < side_dist_y:
                side_dist_x += delta_x
                map_x += step_x
                side = 0
            else:
                side_dist_y += delta_y
                map_y += step_y
                side = 1
            if 0 <= map_x < MAP_W and 0 <= map_y < MAP_H:
                cell = MAP[map_y][map_x]

                # --- 门扉处理: 检查格子中心墙面 ---
                if cell in DOOR_TILES and doors is not None:
                    d = doors.get((map_x, map_y))
                    if d and d["open"] < 1.0:
                        if cell == 5 and ray_dy != 0:
                            # 横向门: 墙在 y = map_y + 0.5, 沿X滑动
                            t_center = (map_y + 0.5 - pos_y) / ray_dy
                            if t_center > 0:
                                wall_x = pos_x + t_center * ray_dx
                                if map_x - 0.01 <= wall_x < map_x + 1.01:
                                    frac = wall_x - map_x
                                    if frac >= d["open"]:
                                        perp_dist = t_center
                                        side = 1
                                        hit = True
                                        door_hit = True
                        elif cell == 6 and ray_dx != 0:
                            # 纵向门: 墙在 x = map_x + 0.5, 沿Y滑动
                            t_center = (map_x + 0.5 - pos_x) / ray_dx
                            if t_center > 0:
                                wall_y = pos_y + t_center * ray_dy
                                if map_y - 0.01 <= wall_y < map_y + 1.01:
                                    frac = wall_y - map_y
                                    if frac >= d["open"]:
                                        perp_dist = t_center
                                        side = 0
                                        hit = True
                                        door_hit = True
                    # 无论是否命中, 未命中则继续DDA穿过
                    if not hit:
                        continue

                elif cell > 0:
                    hit = True
            else:
                break

        if not hit:
            z_buffer[x] = 1e30
            continue

        # 普通墙壁: 计算垂直距离
        if not door_hit:
            if side == 0:
                perp_dist = side_dist_x - delta_x
            else:
                perp_dist = side_dist_y - delta_y

        if perp_dist <= 0.0001:
            perp_dist = 0.0001

        z_buffer[x] = perp_dist

        line_h = int(SCREEN_H / perp_dist)
        draw_start = max(0, -line_h // 2 + SCREEN_H // 2)
        draw_end = min(SCREEN_H - 1, line_h // 2 + SCREEN_H // 2)

        wall_type = MAP[map_y][map_x]
        base_color = WALL_COLORS.get(wall_type, (200, 200, 200))

        if side == 1:
            base_color = tuple(c // 2 for c in base_color)

        # 门扉: 根据开启程度变暗 (模拟滑动后的阴影)
        if door_hit and doors:
            d = doors.get((map_x, map_y))
            if d:
                dim = 1.0 - d["open"] * 0.4
                base_color = tuple(int(c * dim) for c in base_color)

        fog = max(0.15, 1.0 - perp_dist / 12.0)
        color = tuple(int(c * fog) for c in base_color)

        pygame.draw.line(surface, color, (x, draw_start), (x, draw_end))


# ---------------------------------------------------------------------------
# 渲染: 敌人精灵 (billboard)
# ---------------------------------------------------------------------------
def render_enemies(surface, enemies, z_buffer, pos_x, pos_y,
                   dir_x, dir_y, plane_x, plane_y, sprites):
    """渲染所有敌人精灵: 按敌种选图, 受击红闪, 死亡淡出下沉, 头顶血条。
    按距离远→近排序, 逐列 z-buffer 深度测试。"""
    ranked = []
    for e in enemies:
        dx = e["x"] - pos_x
        dy = e["y"] - pos_y
        ranked.append((dx * dx + dy * dy, e))
    ranked.sort(key=lambda t: t[0], reverse=True)

    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)

    for _, e in ranked:
        cfg = ENEMY_TYPES[e["kind"]]
        sx = e["x"] - pos_x
        sy = e["y"] - pos_y

        transform_x = inv_det * (dir_y * sx - dir_x * sy)
        transform_y = inv_det * (-plane_y * sx + plane_x * sy)

        if transform_y <= 0.1:
            continue  # 在玩家身后

        sprite_screen_x = int((SCREEN_W / 2) * (1 + transform_x / transform_y))

        scale = cfg["scale"]
        sprite_h = max(2, int(SCREEN_H / transform_y * scale))
        sprite_w = sprite_h  # 正方形精灵

        # 死亡: 下沉 + 淡出
        death = e["death_t"]
        sink_y = int(death * sprite_h * 0.35) if death is not None else 0

        # 垂直裁剪
        screen_y0 = -sprite_h // 2 + SCREEN_H // 2 + sink_y
        screen_y1 = sprite_h // 2 + SCREEN_H // 2 + sink_y
        draw_y0 = max(0, screen_y0)
        draw_y1 = min(SCREEN_H, screen_y1)
        tex_y0 = draw_y0 - screen_y0
        tex_h = draw_y1 - draw_y0
        if tex_h <= 0:
            continue

        # 水平裁剪
        screen_x0 = -sprite_w // 2 + sprite_screen_x
        screen_x1 = sprite_w // 2 + sprite_screen_x
        draw_x0 = max(0, screen_x0)
        draw_x1 = min(SCREEN_W, screen_x1)
        if draw_x1 <= draw_x0:
            continue

        # 缩放精灵 (按敌种)
        base = sprites[e["kind"]]
        scaled = pygame.transform.scale(base, (sprite_w, sprite_h))

        # 受击红闪: 整体加亮红
        if e["hit_flash"] > 0:
            fi = int(160 * (e["hit_flash"] / ENEMY_HIT_FLASH))
            scaled.fill((fi, fi // 2, fi // 2), special_flags=pygame.BLEND_RGB_ADD)

        # 距离雾化
        fog = max(0.25, 1.0 - transform_y / 14.0)
        fog_color = (int(255 * fog), int(255 * fog), int(255 * fog))
        scaled.fill(fog_color, special_flags=pygame.BLEND_MULT)

        # 死亡淡出 (雾化后再设, 避免被覆盖)
        if death is not None:
            scaled.set_alpha(int(255 * max(0.0, 1.0 - death)))

        # z-buffer 可见性检测
        fully_visible = True
        for col in range(draw_x0, draw_x1):
            if transform_y >= z_buffer[col]:
                fully_visible = False
                break

        if fully_visible:
            tex_x0 = draw_x0 - screen_x0
            tex_w = draw_x1 - draw_x0
            surface.blit(scaled, (draw_x0, draw_y0),
                         area=(tex_x0, tex_y0, tex_w, tex_h))
        else:
            # 逐列 blit, 被 wall 遮挡的列跳过
            for col in range(draw_x0, draw_x1):
                if transform_y < z_buffer[col]:
                    tex_x = col - screen_x0
                    if 0 <= tex_x < sprite_w:
                        surface.blit(scaled, (col, draw_y0),
                                     area=(tex_x, tex_y0, 1, tex_h))

        # 头顶血条 (仅存活且受过伤的敌人)
        if death is None and e["hp"] < e["max_hp"]:
            bar_w = max(14, sprite_w // 2)
            bar_h = max(3, sprite_h // 24)
            bar_x = sprite_screen_x - bar_w // 2
            bar_y = screen_y0 - bar_h - 4
            if 0 < bar_x < SCREEN_W and bar_y > 0:
                pygame.draw.rect(surface, (15, 15, 15),
                                 (bar_x - 1, bar_y - 1, bar_w + 2, bar_h + 2))
                pygame.draw.rect(surface, (80, 20, 20),
                                 (bar_x, bar_y, bar_w, bar_h))
                ratio = max(0.0, e["hp"] / e["max_hp"])
                pygame.draw.rect(surface, (60, 220, 70),
                                 (bar_x, bar_y, int(bar_w * ratio), bar_h))


# ---------------------------------------------------------------------------
# 渲染: 传送门
# ---------------------------------------------------------------------------
PORTAL_COLOR = (100, 200, 255)
PORTAL_GLOW = (60, 140, 200)


def make_portal_sprite(size=64):
    """生成传送门精灵表面: 蓝色光圈 + 中心漩涡。"""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size // 2
    r = size // 2 - 2
    # 外圈光晕 (多层渐变)
    for i in range(6, 0, -1):
        alpha = int(20 + 15 * i)
        rr = r + i
        pygame.draw.circle(surf, (*PORTAL_COLOR, alpha), (cx, cy), rr)
    # 外圈
    pygame.draw.circle(surf, PORTAL_GLOW, (cx, cy), r, 3)
    # 内圈
    pygame.draw.circle(surf, PORTAL_COLOR, (cx, cy), r - 4)
    pygame.draw.circle(surf, (220, 240, 255), (cx, cy), r - 4, 2)
    # 中心漩涡 (螺旋线)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + int(math.cos(rad) * (r - 8))
        y1 = cy + int(math.sin(rad) * (r - 8))
        x2 = cx + int(math.cos(rad) * (r - 16))
        y2 = cy + int(math.sin(rad) * (r - 16))
        pygame.draw.line(surf, (200, 230, 255), (x1, y1), (x2, y2), 2)
    # 中心亮点
    pygame.draw.circle(surf, (240, 250, 255), (cx, cy), 4)
    return surf


def render_portals(surface, portals, z_buffer, pos_x, pos_y,
                   dir_x, dir_y, plane_x, plane_y, portal_sprite):
    """渲染传送门精灵: billboard 投影 + z-buffer 深度测试 + 距离雾化。"""
    ranked = []
    for p in portals:
        dx = p["x"] - pos_x
        dy = p["y"] - pos_y
        ranked.append((dx * dx + dy * dy, p))
    ranked.sort(key=lambda t: t[0], reverse=True)

    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)

    for _, p in ranked:
        sx = p["x"] - pos_x
        sy = p["y"] - pos_y

        transform_x = inv_det * (dir_y * sx - dir_x * sy)
        transform_y = inv_det * (-plane_y * sx + plane_x * sy)

        if transform_y <= 0.1:
            continue

        sprite_screen_x = int((SCREEN_W / 2) * (1 + transform_x / transform_y))

        sprite_h = max(2, int(SCREEN_H / transform_y * 0.8))
        sprite_w = sprite_h

        screen_y0 = -sprite_h // 2 + SCREEN_H // 2
        screen_y1 = sprite_h // 2 + SCREEN_H // 2
        draw_y0 = max(0, screen_y0)
        draw_y1 = min(SCREEN_H, screen_y1)
        tex_y0 = draw_y0 - screen_y0
        tex_h = draw_y1 - draw_y0
        if tex_h <= 0:
            continue

        screen_x0 = -sprite_w // 2 + sprite_screen_x
        screen_x1 = sprite_w // 2 + sprite_screen_x
        draw_x0 = max(0, screen_x0)
        draw_x1 = min(SCREEN_W, screen_x1)
        if draw_x1 <= draw_x0:
            continue

        scaled = pygame.transform.scale(portal_sprite, (sprite_w, sprite_h))

        # 距离雾化
        fog = max(0.3, 1.0 - transform_y / 14.0)
        fog_color = (int(255 * fog), int(255 * fog), int(255 * fog))
        scaled.fill(fog_color, special_flags=pygame.BLEND_MULT)

        # z-buffer 可见性检测
        fully_visible = True
        for col in range(draw_x0, draw_x1):
            if transform_y >= z_buffer[col]:
                fully_visible = False
                break

        if fully_visible:
            tex_x0 = draw_x0 - screen_x0
            tex_w = draw_x1 - draw_x0
            surface.blit(scaled, (draw_x0, draw_y0),
                         area=(tex_x0, tex_y0, tex_w, tex_h))
        else:
            for col in range(draw_x0, draw_x1):
                if transform_y < z_buffer[col]:
                    tex_x = col - screen_x0
                    if 0 <= tex_x < sprite_w:
                        surface.blit(scaled, (col, draw_y0),
                                     area=(tex_x, tex_y0, 1, tex_h))


# ---------------------------------------------------------------------------
# 渲染: 锤子武器
# ---------------------------------------------------------------------------
def swing_lift(t):
    """挥击进度 t(0~1) → 抬起量(0~1)。三段: 快挥起 → 顶部停顿 → 慢收回。
    命中时机(0.45)落在停顿段, 让打击感更扎实。"""
    if t <= 0.0:
        return 0.0
    if t < 0.35:                      # 挥起 (快, smoothstep)
        k = t / 0.35
        return k * k * (3 - 2 * k)
    if t < 0.55:                      # 顶部停顿
        return 1.0
    if t < 1.0:                       # 收回 (慢, smoothstep)
        k = (t - 0.55) / 0.45
        return 1.0 - k * k * (3 - 2 * k)
    return 0.0


def draw_hammer(surface, hammer_surf, swing_t):
    """绘制锤子武器视图。swing_t: 0=空闲, 0~1=挥击进度(分段动画)。"""
    cx = SCREEN_W // 2
    ground_y = SCREEN_H

    if swing_t > 0:
        lift = swing_lift(swing_t)
        angle = 62 * lift
        offset_x = int((1 - lift) * 70 - 10)
        offset_y = int(-42 * lift)
    else:
        angle = 25
        offset_x = 70
        offset_y = 0

    rotated = pygame.transform.rotate(hammer_surf, angle)
    rect = rotated.get_rect(midbottom=(cx + offset_x, ground_y + offset_y))
    surface.blit(rotated, rect)


# ---------------------------------------------------------------------------
# 渲染: HUD / 小地图 / 准星
# ---------------------------------------------------------------------------
def draw_floor_ceiling(surface):
    pygame.draw.rect(surface, (40, 40, 50), (0, 0, SCREEN_W, SCREEN_H // 2))
    pygame.draw.rect(surface, (60, 50, 40), (0, SCREEN_H // 2, SCREEN_W, SCREEN_H // 2))


def draw_crosshair(surface, locked=False):
    """绘制中心准星。locked=True(对准敌人)时变红并加中心点。"""
    cx, cy = SCREEN_W // 2, SCREEN_H // 2
    color = (255, 70, 70) if locked else (255, 255, 255)
    gap = 5 if locked else 3
    pygame.draw.line(surface, color, (cx - 9, cy), (cx - gap, cy), 2)
    pygame.draw.line(surface, color, (cx + gap, cy), (cx + 9, cy), 2)
    pygame.draw.line(surface, color, (cx, cy - 9), (cx, cy - gap), 2)
    pygame.draw.line(surface, color, (cx, cy + gap), (cx, cy + 9), 2)
    if locked:
        pygame.draw.circle(surface, color, (cx, cy), 2)


# ---------------------------------------------------------------------------
# 飘字 (受击伤害数字 / 击杀提示)
# ---------------------------------------------------------------------------
FLOAT_TEXT_LIFE = 0.8   # 飘字存活秒数


def add_floating_texts(texts, hits):
    """把锤击命中信息转成飘字。hits=[(wx,wy,damage,killed)]。"""
    for (wx, wy, dmg, killed) in hits:
        text = "击杀!" if killed else str(dmg)
        color = (255, 80, 80) if killed else (255, 230, 120)
        texts.append({
            "wx": wx, "wy": wy, "text": text, "color": color,
            "age": 0.0, "life": FLOAT_TEXT_LIFE,
        })


def update_floating_texts(texts, dt):
    for t in texts:
        t["age"] += dt
    texts[:] = [t for t in texts if t["age"] < t["life"]]


def draw_floating_texts(surface, texts, z_buffer, pos_x, pos_y,
                        dir_x, dir_y, plane_x, plane_y, font):
    """世界坐标飘字投影到屏幕, 向上漂浮+淡出。被墙遮挡则不显示。"""
    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
    for t in texts:
        sx = t["wx"] - pos_x
        sy = t["wy"] - pos_y
        tx = inv_det * (dir_y * sx - dir_x * sy)
        ty = inv_det * (-plane_y * sx + plane_x * sy)
        if ty <= 0.1:
            continue
        screen_x = int((SCREEN_W / 2) * (1 + tx / ty))
        if not (0 <= screen_x < SCREEN_W):
            continue
        if ty >= z_buffer[screen_x]:
            continue  # 被墙遮挡
        prog = t["age"] / t["life"]
        rise = int(prog * 42)
        screen_y = SCREEN_H // 2 - rise
        alpha = int(255 * (1.0 - prog))
        s = font.render(t["text"], True, t["color"])
        s.set_alpha(alpha)
        surface.blit(s, s.get_rect(center=(screen_x, screen_y)))


def draw_minimap(surface, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y, enemies, doors=None, portals=None):
    bg_w = MAP_W * MINIMAP_SCALE + 4
    bg_h = MAP_H * MINIMAP_SCALE + 4
    pygame.draw.rect(surface, (20, 20, 20),
                     (MINIMAP_X - 2, MINIMAP_Y - 2, bg_w, bg_h))

    for my in range(MAP_H):
        for mx in range(MAP_W):
            cell = MAP[my][mx]
            if cell > 0:
                c = WALL_COLORS.get(cell, (160, 160, 160))
                # 门扉: 根据开启程度调整亮度
                if cell in DOOR_TILES and doors:
                    d = doors.get((mx, my))
                    if d:
                        dim = 1.0 - d["open"] * 0.5
                        c = tuple(int(ch * dim) for ch in c)
                pygame.draw.rect(
                    surface, c,
                    (MINIMAP_X + mx * MINIMAP_SCALE,
                     MINIMAP_Y + my * MINIMAP_SCALE,
                     MINIMAP_SCALE - 1, MINIMAP_SCALE - 1),
                )

    # 传送门 (蓝色光圈)
    if portals:
        for p in portals:
            px = MINIMAP_X + p["x"] * MINIMAP_SCALE
            py = MINIMAP_Y + p["y"] * MINIMAP_SCALE
            pygame.draw.circle(surface, PORTAL_COLOR, (int(px), int(py)), 4)
            pygame.draw.circle(surface, (220, 240, 255), (int(px), int(py)), 4, 1)

    # 敌人 (按敌种着色, 跳过死亡淡出中的)
    for e in enemies:
        if e["death_t"] is not None:
            continue
        ex = MINIMAP_X + e["x"] * MINIMAP_SCALE
        ey = MINIMAP_Y + e["y"] * MINIMAP_SCALE
        col = ENEMY_TYPES[e["kind"]]["color"]
        r = 4 if e["kind"] == "brute" else 3
        pygame.draw.circle(surface, col, (int(ex), int(ey)), r)

    px = MINIMAP_X + pos_x * MINIMAP_SCALE
    py = MINIMAP_Y + pos_y * MINIMAP_SCALE
    pygame.draw.circle(surface, (255, 255, 0), (int(px), int(py)), 3)

    for sign in (-1, 1):
        ex = px + (dir_x + plane_x * sign) * MINIMAP_SCALE * 3
        ey = py + (dir_y + plane_y * sign) * MINIMAP_SCALE * 3
        pygame.draw.line(surface, (255, 255, 0), (px, py), (ex, ey), 1)


def draw_hud(surface, font_big, font_small, enemies, kill_count, swing_t, swing_active,
             door_prompt=False, kill_flash=0.0, weapon=None, weapon_idx=0,
             cooldown_t=0.0, projectiles=None):
    """绘制底部 HUD 面板: 当前武器/状态 / 提示 / 存活-击杀-分种图例; 击杀屏幕边缘红光闪屏。"""
    bar_h = 56
    bar_y = SCREEN_H - bar_h
    # 半透明背景
    hud_bg = pygame.Surface((SCREEN_W, bar_h), pygame.SRCALPHA)
    hud_bg.fill((0, 0, 0, 140))
    surface.blit(hud_bg, (0, bar_y))
    pygame.draw.line(surface, (100, 100, 120), (0, bar_y), (SCREEN_W, bar_y), 2)

    # 左侧: 当前武器名 + 状态
    wname = weapon.get("name", "HAMMER") if weapon else "HAMMER"
    wcol = weapon.get("color", (220, 200, 80)) if weapon else (220, 200, 80)
    if isinstance(wcol, list):
        wcol = tuple(wcol)
    wlabel = font_big.render(f"[{weapon_idx+1}] {wname}", True, wcol)
    surface.blit(wlabel, (16, bar_y + 6))

    wtype = weapon.get("type", "melee") if weapon else "melee"
    if wtype == "melee":
        if swing_active:
            status_text, status_color = "挥击中...", (255, 180, 80)
        else:
            status_text, status_color = "就绪", (120, 255, 120)
        status = font_small.render(status_text, True, status_color)
        surface.blit(status, (16, bar_y + 32))
    else:  # projectile
        ready = cooldown_t <= 0
        if ready:
            status_text, status_color = "就绪", (120, 255, 120)
        else:
            status_text, status_color = f"冷却 {cooldown_t:.1f}s", (180, 180, 180)
        status = font_small.render(status_text, True, status_color)
        surface.blit(status, (16, bar_y + 28))
        # 冷却条
        cd_max = weapon.get("cooldown", 0.5)
        bar_w, bar_h2 = 120, 5
        pygame.draw.rect(surface, (40, 40, 40), (16, bar_y + 46, bar_w, bar_h2))
        if not ready and cd_max > 0:
            ratio = 1.0 - cooldown_t / cd_max
            pygame.draw.rect(surface, (120, 180, 255),
                             (16, bar_y + 46, int(bar_w * ratio), bar_h2))
        # 飞弹在场数量提示
        if projectiles is not None:
            ptxt = font_small.render(f"在场 {len(projectiles)}",
                                     True, (180, 180, 180))
            surface.blit(ptxt, (148, bar_y + 28))

    # 中间: 提示
    hint = font_small.render(
        "SPACE 开门/使用武器   1~9 切换武器   E 生成敌人   方向键移动   AD 转向   ESC 退出",
        True, (180, 180, 180),
    )
    hint_rect = hint.get_rect(center=(SCREEN_W // 2, bar_y + bar_h // 2))
    surface.blit(hint, hint_rect)

    # 武器栏 (HUD 上方一行)
    if WEAPONS:
        slot_w = 90
        total_w = slot_w * len(WEAPONS)
        sx0 = SCREEN_W // 2 - total_w // 2
        sy0 = bar_y - 26
        for i, w in enumerate(WEAPONS):
            r = pygame.Rect(sx0 + i * slot_w, sy0, slot_w - 6, 22)
            is_cur = (i == weapon_idx)
            bg = (60, 60, 80) if is_cur else (30, 30, 40)
            pygame.draw.rect(surface, bg, r, border_radius=3)
            border = w.get("color", (200, 200, 200)) if is_cur else (70, 70, 90)
            if isinstance(border, list):
                border = tuple(border)
            pygame.draw.rect(surface, border, r, 1, border_radius=3)
            tag = f"{i+1}:{w.get('name','?')[:6]}"
            tcol = (250, 250, 250) if is_cur else (160, 160, 170)
            t = font_small.render(tag, True, tcol)
            surface.blit(t, t.get_rect(center=r.center))

    # 门扉交互提示 (HUD 条上方)
    if door_prompt:
        prompt = font_small.render("按 SPACE 开门", True, (255, 230, 120))
        prect = prompt.get_rect(center=(SCREEN_W // 2, bar_y - 48))
        surface.blit(prompt, prect)

    # 右侧: 存活 / 击杀 / 分种图例
    alive = sum(1 for e in enemies if e["death_t"] is None)
    enemy_text = font_big.render(f"存活 {alive}", True, (255, 80, 80))
    surface.blit(enemy_text, (SCREEN_W - 180, bar_y + 4))
    kill_text = font_small.render(f"击杀 {kill_count}", True, (255, 200, 80))
    surface.blit(kill_text, (SCREEN_W - 180, bar_y + 30))

    counts = {"grunt": 0, "sprite": 0, "brute": 0}
    for e in enemies:
        if e["death_t"] is None:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    legend_x = SCREEN_W - 78
    legend_y = bar_y + 40
    for i, k in enumerate(("grunt", "sprite", "brute")):
        col = ENEMY_TYPES[k]["color"]
        cx_l = legend_x + i * 22
        pygame.draw.circle(surface, col, (cx_l, legend_y), 4)
        num = font_small.render(str(counts.get(k, 0)), True, (220, 220, 220))
        surface.blit(num, (cx_l + 7, legend_y - 8))

    # 击杀边缘红光闪屏
    if kill_flash > 0:
        a = int(110 * kill_flash)
        edge = 36
        flash = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        pygame.draw.rect(flash, (255, 40, 40, a), (0, 0, SCREEN_W, edge))
        pygame.draw.rect(flash, (255, 40, 40, a), (0, SCREEN_H - edge, SCREEN_W, edge))
        pygame.draw.rect(flash, (255, 40, 40, a), (0, 0, edge, SCREEN_H))
        pygame.draw.rect(flash, (255, 40, 40, a), (SCREEN_W - edge, 0, edge, SCREEN_H))
        surface.blit(flash, (0, 0))


# ---------------------------------------------------------------------------
# 游戏逻辑
# ---------------------------------------------------------------------------
def is_wall(x, y, doors=None):
    mx, my = int(x), int(y)
    if 0 <= mx < MAP_W and 0 <= my < MAP_H:
        cell = MAP[my][mx]
        if cell in DOOR_TILES and doors is not None:
            d = doors.get((mx, my))
            if d and d["open"] >= 0.8:
                return False
        return cell > 0
    return True


def try_move(pos_x, pos_y, dx, dy, doors=None):
    margin = 0.2
    new_x = pos_x + dx
    if not (is_wall(new_x + (margin if dx > 0 else -margin), pos_y, doors) or
            is_wall(new_x + (margin if dx > 0 else -margin), pos_y + margin, doors) or
            is_wall(new_x + (margin if dx > 0 else -margin), pos_y - margin, doors)):
        pos_x = new_x

    new_y = pos_y + dy
    if not (is_wall(pos_x, new_y + (margin if dy > 0 else -margin), doors) or
            is_wall(pos_x + margin, new_y + (margin if dy > 0 else -margin), doors) or
            is_wall(pos_x - margin, new_y + (margin if dy > 0 else -margin), doors)):
        pos_y = new_y

    return pos_x, pos_y


def make_enemy(kind, x, y):
    """创建一个敌人 dict, 含完整状态字段。"""
    cfg = ENEMY_TYPES[kind]
    return {
        "kind": kind,
        "x": x, "y": y,
        "hp": cfg["hp"], "max_hp": cfg["hp"],
        "hit_flash": 0.0,           # 受击红闪剩余秒数
        "kb_x": 0.0, "kb_y": 0.0,   # 击退速度(格/秒)
        "death_t": None,            # None=存活; 0~1=死亡淡出进度
        "ai_state": "idle",         # 视野型: idle/chase
        "last_seen": (x, y),        # 最后看到玩家的位置
        "path": [],                 # 绕路型当前路径(格子坐标列表)
        "repath_t": 0.0,            # 重算路径冷却
    }


def spawn_enemy(pos_x, pos_y, enemies, kind=None):
    """在随机空地生成敌人, 离玩家至少 4 格。kind=None 时随机选种(偏向普通)。"""
    if len(enemies) >= MAX_ENEMIES:
        return
    if kind is None:
        # 随机选种: grunt 60%, sprite 25%, brute 15%
        r = random.random()
        kind = "grunt" if r < 0.6 else ("sprite" if r < 0.85 else "brute")
    for _ in range(60):
        mx = random.randint(1, MAP_W - 2)
        my = random.randint(1, MAP_H - 2)
        if MAP[my][mx] > 0:
            continue
        ex, ey = mx + 0.5, my + 0.5
        if (ex - pos_x) ** 2 + (ey - pos_y) ** 2 < 16:  # 4格内不生成
            continue
        enemies.append(make_enemy(kind, ex, ey))
        return


def has_line_of_sight(x0, y0, x1, y1, doors=None):
    """DDA 线段穿墙检测: 从(x0,y0)到(x1,y1)是否被墙(含关闭的门)遮挡。"""
    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy)
    if dist < 0.0001:
        return True
    steps = int(dist * 4) + 1   # 每格采样4次
    inv = 1.0 / steps
    for i in range(1, steps + 1):
        t = i * inv
        cx = x0 + dx * t
        cy = y0 + dy * t
        if is_wall(cx, cy, doors):
            return False
    return True


def find_path(start_xy, goal_xy):
    """BFS 网格寻路: 从 start_xy 到 goal_xy 返回下一格坐标 (mx,my) 列表(不含起点)。
    只走空地(cell==0); 门视为阻挡。找不到返回空列表。"""
    sx, sy = int(start_xy[0]), int(start_xy[1])
    gx, gy = int(goal_xy[0]), int(goal_xy[1])
    if not (0 <= gx < MAP_W and 0 <= gy < MAP_H):
        return []
    if MAP[gy][gx] != 0:
        # 目标在墙里, 找最近空地
        return []
    if (sx, sy) == (gx, gy):
        return []
    from collections import deque
    q = deque([(sx, sy)])
    came = {(sx, sy): None}
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    found = False
    while q:
        cx, cy = q.popleft()
        if (cx, cy) == (gx, gy):
            found = True
            break
        for dx, dy in dirs:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < MAP_W and 0 <= ny < MAP_H and (nx, ny) not in came:
                if MAP[ny][nx] == 0:
                    came[(nx, ny)] = (cx, cy)
                    q.append((nx, ny))
    if not found:
        return []
    # 回溯路径
    path = []
    cur = (gx, gy)
    while cur != (sx, sy):
        path.append(cur)
        cur = came[cur]
    path.reverse()
    return path


def update_enemies(enemies, pos_x, pos_y, dt, doors=None):
    """敌人 AI + 物理更新。
    - 视野型(grunt/sprite): 看见玩家才追, 墙遮挡丢视野后回到 idle
    - 绕路型(brute): 长线追踪, BFS 绕墙, 永不卡墙
    - 击退位移优先, 死亡动画推进, 受击红闪衰减
    """
    for e in enemies:
        # 死亡淡出动画
        if e["death_t"] is not None:
            e["death_t"] += dt / ENEMY_DEATH_TIME
            continue

        # 受击红闪衰减
        if e["hit_flash"] > 0:
            e["hit_flash"] = max(0.0, e["hit_flash"] - dt)

        cfg = ENEMY_TYPES[e["kind"]]
        ex, ey = e["x"], e["y"]

        # --- 击退位移 (优先于 AI 移动) ---
        if abs(e["kb_x"]) > 0.001 or abs(e["kb_y"]) > 0.001:
            nx, ny = try_move(ex, ey, e["kb_x"] * dt, e["kb_y"] * dt, doors)
            e["x"], e["y"] = nx, ny
            decay = max(0.0, 1.0 - ENEMY_KNOCKBACK_DECAY * dt)
            e["kb_x"] *= decay
            e["kb_y"] *= decay
            continue  # 击退中不执行 AI 移动

        dx = pos_x - ex
        dy = pos_y - ey
        dist = math.hypot(dx, dy)
        can_see = (dist < ENEMY_SIGHT_DIST and
                   has_line_of_sight(ex, ey, pos_x, pos_y, doors))

        if cfg["sight"]:
            # 视野型
            if can_see:
                e["ai_state"] = "chase"
                e["last_seen"] = (pos_x, pos_y)
            # 丢失视野后保持 chase 但走向 last_seen, 到达后转 idle
            if e["ai_state"] == "chase":
                tx, ty = e["last_seen"]
                tdx = tx - ex
                tdy = ty - ey
                td = math.hypot(tdx, tdy)
                if td < 0.3:
                    e["ai_state"] = "idle"
                else:
                    mvx = (tdx / td) * cfg["speed"] * dt
                    mvy = (tdy / td) * cfg["speed"] * dt
                    e["x"], e["y"] = try_move(ex, ey, mvx, mvy, doors)
            # idle 状态不动
        elif cfg["pathfind"]:
            # 绕路型: 长线追踪, BFS 寻路
            e["repath_t"] -= dt
            # 视野内直接冲玩家; 否则走路径
            if can_see:
                e["path"] = []
                if dist > 0.01:
                    mvx = (dx / dist) * cfg["speed"] * dt
                    mvy = (dy / dist) * cfg["speed"] * dt
                    e["x"], e["y"] = try_move(ex, ey, mvx, mvy, doors)
            else:
                # 重算路径 (路径空了或冷却到时)
                if not e["path"] or e["repath_t"] <= 0:
                    e["path"] = find_path((ex, ey), (pos_x, pos_y))
                    e["repath_t"] = ENEMY_REPATH_INTERVAL
                if e["path"]:
                    tx, ty = e["path"][0]
                    cx, cy = tx + 0.5, ty + 0.5  # 格子中心
                    tdx = cx - ex
                    tdy = cy - ey
                    td = math.hypot(tdx, tdy)
                    if td < 0.15:
                        e["path"].pop(0)
                    else:
                        mvx = (tdx / td) * cfg["speed"] * dt
                        mvy = (tdy / td) * cfg["speed"] * dt
                        e["x"], e["y"] = try_move(ex, ey, mvx, mvy, doors)

    # 清理死亡动画结束的敌人
    enemies[:] = [e for e in enemies if not (e["death_t"] is not None and e["death_t"] >= 1.0)]


def hammer_attack(enemies, pos_x, pos_y, dir_x, dir_y, weapon):
    """近战武器攻击判定: 范围内且锥角内的敌人扣血, 受击红闪+击退; hp<=0 触发死亡动画。
    weapon: 当前近战武器 dict (含 damage/range/arc_deg/knockback)。
    返回 (kills, hits): kills=本次击杀数, hits=[(wx,wy,damage,killed)] 供飘字使用。"""
    kills = 0
    hits = []
    damage = weapon.get("damage", 1)
    atk_range = weapon.get("range", ATTACK_RANGE)
    half_angle = math.radians(weapon.get("arc_deg", 35))
    kb_base = weapon.get("knockback", 1.0)
    for e in enemies:
        if e["death_t"] is not None:
            continue  # 已经在死亡动画中, 不再受击
        dx = e["x"] - pos_x
        dy = e["y"] - pos_y
        dist = math.hypot(dx, dy)
        if dist > atk_range:
            continue
        # 角度: 玩家朝向与敌人方向的夹角
        if dist < 0.01:
            angle = 0.0
            nx, ny = dir_x, dir_y
        else:
            cos_a = (dir_x * dx + dir_y * dy) / dist
            cos_a = max(-1.0, min(1.0, cos_a))
            angle = math.acos(cos_a)
            nx, ny = dx / dist, dy / dist
        if angle >= half_angle:
            continue
        # 命中
        cfg = ENEMY_TYPES[e["kind"]]
        e["hp"] -= damage
        e["hit_flash"] = ENEMY_HIT_FLASH
        # 击退: 沿玩家→敌人方向
        kb = cfg["knockback"] * kb_base * 4.0
        e["kb_x"] = nx * kb
        e["kb_y"] = ny * kb
        killed = e["hp"] <= 0
        if killed:
            e["hp"] = 0
            e["death_t"] = 0.0
            e["kb_x"] *= 1.5  # 致命一击击退更强
            e["kb_y"] *= 1.5
            kills += 1
        hits.append((e["x"], e["y"], damage, killed))
    return kills, hits


# ---------------------------------------------------------------------------
# 飞弹 / 投射物系统
# ---------------------------------------------------------------------------
def make_projectile_sprite(color, size=32):
    """生成飞弹精灵: 发光球体 (外晕 + 内核)。"""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx, cy = size // 2, size // 2
    # 多层光晕 (从外到内)
    layers = [(size // 2 - 1, 50), (size // 3, 110), (size // 4, 180)]
    for r, alpha in layers:
        glow = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(glow, (color[0], color[1], color[2], alpha), (cx, cy), r)
        surf.blit(glow, (0, 0))
    # 内核 (更亮)
    core = tuple(min(255, c + 60) for c in color)
    pygame.draw.circle(surf, core, (cx, cy), max(2, size // 6))
    return surf


def spawn_projectile(projectiles, weapon, pos_x, pos_y, dir_x, dir_y):
    """从玩家位置发射一发飞弹。"""
    projectiles.append({
        "x": pos_x + dir_x * 0.3,
        "y": pos_y + dir_y * 0.3,
        "dx": dir_x,
        "dy": dir_y,
        "speed": weapon.get("speed", 6.0),
        "dist_left": weapon.get("range", 12.0),
        "damage": weapon.get("damage", 1),
        "radius": weapon.get("radius", 0.3),
        "splash": weapon.get("splash_radius", 0.0),
        "color": weapon.get("color", (255, 120, 40)),
        "alive": True,
    })


def damage_enemy(e, damage, dx_dir=0.0, dy_dir=0.0):
    """对单个敌人造成伤害, 返回 (kills, hits)。"""
    cfg = ENEMY_TYPES[e["kind"]]
    e["hp"] -= damage
    e["hit_flash"] = ENEMY_HIT_FLASH
    # 击退方向 (来自飞弹方向)
    if dx_dir != 0 or dy_dir != 0:
        kb = cfg["knockback"] * 2.5
        e["kb_x"] = dx_dir * kb
        e["kb_y"] = dy_dir * kb
    killed = e["hp"] <= 0
    if killed:
        e["hp"] = 0
        e["death_t"] = 0.0
        e["kb_x"] *= 1.5
        e["kb_y"] *= 1.5
        return 1, [(e["x"], e["y"], damage, True)]
    return 0, [(e["x"], e["y"], damage, False)]


def splash_damage(enemies, cx, cy, radius, damage, exclude=None):
    """圆形范围伤害, 距离衰减; 返回 (kills, hits)。"""
    kills = 0
    hits = []
    for e in enemies:
        if e["death_t"] is not None or e is exclude:
            continue
        ddx = e["x"] - cx
        ddy = e["y"] - cy
        d2 = ddx * ddx + ddy * ddy
        if d2 > radius * radius:
            continue
        d = math.sqrt(d2)
        falloff = max(0.3, 1.0 - d / radius) if radius > 0 else 1.0
        dmg = max(1, int(damage * falloff))
        # 击退方向: 爆炸中心 → 敌人
        if d < 0.01:
            dx_dir, dy_dir = 0.0, 0.0
        else:
            dx_dir = ddx / d
            dy_dir = ddy / d
        k, h = damage_enemy(e, dmg, dx_dir, dy_dir)
        kills += k
        hits.extend(h)
    return kills, hits


def update_projectiles(projectiles, enemies, doors, dt):
    """飞弹移动 + 碰撞(墙/敌人) + 溅射伤害。
    返回 (kills, hits) 本帧造成的击杀与命中 (供飘字)。"""
    kills = 0
    hits = []
    for p in projectiles:
        if not p["alive"]:
            continue
        step = p["speed"] * dt
        # 子步长避免穿透 (每子步 ≤ 0.1 格)
        substeps = max(1, int(step / 0.1) + 1)
        sub = step / substeps
        for _ in range(substeps):
            if not p["alive"]:
                break
            nx = p["x"] + p["dx"] * sub
            ny = p["y"] + p["dy"] * sub
            # 撞墙 → 爆炸终止
            if is_wall(nx, ny, doors):
                p["alive"] = False
                if p["splash"] > 0:
                    k, h = splash_damage(enemies, p["x"], p["y"], p["splash"],
                                         p["damage"])
                    kills += k
                    hits.extend(h)
                break
            p["x"] = nx
            p["y"] = ny
            p["dist_left"] -= sub
            if p["dist_left"] <= 0:
                p["alive"] = False
                break
            # 撞敌人 → 直接伤害 + 溅射
            for e in enemies:
                if e["death_t"] is not None:
                    continue
                ex_dx = e["x"] - p["x"]
                ex_dy = e["y"] - p["y"]
                if ex_dx * ex_dx + ex_dy * ex_dy < (p["radius"] + 0.4) ** 2:
                    p["alive"] = False
                    k, h = damage_enemy(e, p["damage"], p["dx"], p["dy"])
                    kills += k
                    hits.extend(h)
                    if p["splash"] > 0:
                        k2, h2 = splash_damage(enemies, p["x"], p["y"],
                                               p["splash"], p["damage"],
                                               exclude=e)
                        kills += k2
                        hits.extend(h2)
                    break
    # 清理死飞弹
    projectiles[:] = [p for p in projectiles if p["alive"]]
    return kills, hits


def render_projectiles(surface, projectiles, z_buffer, pos_x, pos_y,
                       dir_x, dir_y, plane_x, plane_y, sprites):
    """渲染飞弹精灵: billboard 投影 + z-buffer 深度遮挡 (复用敌人精灵投影逻辑)。"""
    ranked = []
    for p in projectiles:
        if not p["alive"]:
            continue
        dx = p["x"] - pos_x
        dy = p["y"] - pos_y
        ranked.append((dx * dx + dy * dy, p))
    ranked.sort(key=lambda t: t[0], reverse=True)

    inv_det = 1.0 / (plane_x * dir_y - dir_x * plane_y)
    for _, p in ranked:
        sx = p["x"] - pos_x
        sy = p["y"] - pos_y
        transform_x = inv_det * (dir_y * sx - dir_x * sy)
        transform_y = inv_det * (-plane_y * sx + plane_x * sy)
        if transform_y <= 0.1:
            continue
        sprite_screen_x = int((SCREEN_W / 2) * (1 + transform_x / transform_y))
        # 飞弹大小: 较小, 视距离缩放
        sprite_h = max(8, int(SCREEN_H / transform_y * 0.3))
        sprite_w = sprite_h

        screen_y0 = -sprite_h // 2 + SCREEN_H // 2
        screen_y1 = sprite_h // 2 + SCREEN_H // 2
        draw_y0 = max(0, screen_y0)
        draw_y1 = min(SCREEN_H, screen_y1)
        tex_y0 = draw_y0 - screen_y0
        tex_h = draw_y1 - draw_y0
        if tex_h <= 0:
            continue
        screen_x0 = -sprite_w // 2 + sprite_screen_x
        screen_x1 = sprite_w // 2 + sprite_screen_x
        draw_x0 = max(0, screen_x0)
        draw_x1 = min(SCREEN_W, screen_x1)
        if draw_x1 <= draw_x0:
            continue

        col = p["color"]
        base = sprites.get(col) or sprites.get((255, 120, 40))
        if base is None:
            continue
        scaled = pygame.transform.scale(base, (sprite_w, sprite_h))

        # 距离雾化
        fog = max(0.4, 1.0 - transform_y / 14.0)
        fog_color = (int(255 * fog), int(255 * fog), int(255 * fog))
        scaled.fill(fog_color, special_flags=pygame.BLEND_MULT)

        # z-buffer 测试
        fully_visible = True
        for col_idx in range(draw_x0, draw_x1):
            if transform_y >= z_buffer[col_idx]:
                fully_visible = False
                break
        if fully_visible:
            tex_x0 = draw_x0 - screen_x0
            tex_w = draw_x1 - draw_x0
            surface.blit(scaled, (draw_x0, draw_y0),
                         area=(tex_x0, tex_y0, tex_w, tex_h))
        else:
            for col_idx in range(draw_x0, draw_x1):
                if transform_y < z_buffer[col_idx]:
                    tex_x = col_idx - screen_x0
                    if 0 <= tex_x < sprite_w:
                        surface.blit(scaled, (col_idx, draw_y0),
                                     area=(tex_x, tex_y0, 1, tex_h))


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("伪3D光线投射 Demo  -  方向键移动 / AD转向 / SPACE开门/使用武器 / 1~9切换武器 / E生成敌人")
    clock = pygame.time.Clock()
    # 使用支持中文的字体 (微软雅黑), consolas 无中文字形会导致问号
    font_big = pygame.font.SysFont("microsoftyahei,msyh,consolas", 20, bold=True)
    font_small = pygame.font.SysFont("microsoftyahei,msyh,consolas", 14)

    # 预渲染资源
    enemy_sprites = make_enemy_sprites(64)
    portal_sprite = make_portal_sprite(64)
    hammer_surf = make_hammer_surface()
    # 飞弹精灵 (按武器颜色缓存, 同色共享)
    projectile_sprites = {}
    for w in WEAPONS:
        if w.get("type") == "projectile":
            col = w.get("color", (255, 120, 40))
            if isinstance(col, list):
                col = tuple(col)
            if col not in projectile_sprites:
                projectile_sprites[col] = make_projectile_sprite(col, 32)

    # 游戏状态: 优先使用 map.json 中的出生点
    if SPAWN_POINT:
        pos_x, pos_y = SPAWN_POINT
    else:
        pos_x, pos_y = POS_X, POS_Y
    dir_x, dir_y = DIR_X, DIR_Y
    plane_x, plane_y = PLANE_X, PLANE_Y
    enemies = []
    # 启动时从 map.json 加载预放置的敌人
    for ex, ey, ekind in INITIAL_ENEMIES:
        if len(enemies) >= MAX_ENEMIES:
            break
        # 避免与玩家出生点重合 (距离 < 1.5 时跳过)
        if math.hypot(ex - pos_x, ey - pos_y) < 1.5:
            continue
        enemies.append(make_enemy(ekind, ex, ey))
    if enemies:
        print(f"已从 {MAP_FILE.name} 加载 {len(enemies)} 个预放置敌人")
    kill_count = 0
    doors = init_doors()
    transitions = list(INITIAL_TRANSITIONS)
    transition_cooldown = 0.0  # 切换地图后短暂冷却, 防止立即再次触发

    z_buffer = [1e30] * SCREEN_W

    # 当前武器 + 武器状态
    current_weapon_idx = load_selected_weapon_idx()
    if current_weapon_idx >= len(WEAPONS):
        current_weapon_idx = 0
    swing_t = 0.0         # 0=空闲, 0~1=挥击进度 (仅近战)
    swing_active = False
    impact_done = False   # 本次挥击是否已完成伤害判定
    cooldown_t = 0.0      # 飞弹冷却剩余秒 (仅飞弹)
    projectiles = []      # 在场飞弹列表

    # 飘字(伤害数字)与击杀闪屏
    floating_texts = []
    kill_flash = 0.0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_e:
                    spawn_enemy(pos_x, pos_y, enemies)
                elif event.key == pygame.K_SPACE:
                    # 范围内有门扉 → 开门 (优先)
                    door_key = nearest_door_in_range(doors, pos_x, pos_y)
                    if door_key is not None:
                        doors[door_key]["want_open"] = True
                    else:
                        weapon = WEAPONS[current_weapon_idx]
                        if weapon.get("type") == "melee":
                            if not swing_active:
                                swing_active = True
                                swing_t = 0.0
                                impact_done = False
                        else:  # projectile
                            if cooldown_t <= 0:
                                spawn_projectile(projectiles, weapon,
                                                 pos_x, pos_y, dir_x, dir_y)
                                cooldown_t = weapon.get("cooldown", 0.5)
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3,
                                   pygame.K_4, pygame.K_5, pygame.K_6,
                                   pygame.K_7, pygame.K_8, pygame.K_9):
                    # 切换武器
                    idx = event.key - pygame.K_1
                    if idx < len(WEAPONS) and idx != current_weapon_idx:
                        current_weapon_idx = idx
                        # 切换武器时重置武器状态
                        swing_active = False
                        swing_t = 0.0
                        impact_done = False
                        cooldown_t = 0.0

        keys = pygame.key.get_pressed()

        # --- 转向 (AD): A=右转, D=左转 ---
        if keys[pygame.K_a]:
            cos_a = math.cos(-ROT_SPEED * dt)
            sin_a = math.sin(-ROT_SPEED * dt)
            dir_x, dir_y = dir_x * cos_a - dir_y * sin_a, dir_x * sin_a + dir_y * cos_a
            plane_x, plane_y = plane_x * cos_a - plane_y * sin_a, plane_x * sin_a + plane_y * cos_a
        if keys[pygame.K_d]:
            cos_a = math.cos(ROT_SPEED * dt)
            sin_a = math.sin(ROT_SPEED * dt)
            dir_x, dir_y = dir_x * cos_a - dir_y * sin_a, dir_x * sin_a + dir_y * cos_a
            plane_x, plane_y = plane_x * cos_a - plane_y * sin_a, plane_x * sin_a + plane_y * cos_a

        # --- 前后移动 (↑↓ / WS) ---
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            pos_x, pos_y = try_move(pos_x, pos_y, dir_x * MOVE_SPEED * dt, dir_y * MOVE_SPEED * dt, doors)
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            pos_x, pos_y = try_move(pos_x, pos_y, -dir_x * MOVE_SPEED * dt, -dir_y * MOVE_SPEED * dt, doors)

        # --- 左右平移 (←→): ←=右移, →=左移 ---
        if keys[pygame.K_LEFT]:
            pos_x, pos_y = try_move(pos_x, pos_y, dir_y * MOVE_SPEED * dt, -dir_x * MOVE_SPEED * dt, doors)
        if keys[pygame.K_RIGHT]:
            pos_x, pos_y = try_move(pos_x, pos_y, -dir_y * MOVE_SPEED * dt, dir_x * MOVE_SPEED * dt, doors)

        # --- 当前武器状态推进 ---
        weapon = WEAPONS[current_weapon_idx]
        if weapon.get("type") == "melee":
            if swing_active:
                swing_t += dt / max(0.05, weapon.get("swing_time", HAMMER_SWING_TIME))
                if swing_t >= weapon.get("impact_t", HAMMER_IMPACT_T) and not impact_done:
                    kills, hits = hammer_attack(enemies, pos_x, pos_y,
                                                dir_x, dir_y, weapon)
                    kill_count += kills
                    if hits:
                        add_floating_texts(floating_texts, hits)
                    if kills > 0:
                        kill_flash = 1.0
                    impact_done = True
                if swing_t >= 1.0:
                    swing_t = 0.0
                    swing_active = False
        else:  # projectile
            if cooldown_t > 0:
                cooldown_t = max(0.0, cooldown_t - dt)
            # 飞弹更新 + 命中飘字 + 击杀闪屏
            p_kills, p_hits = update_projectiles(projectiles, enemies, doors, dt)
            if p_hits:
                add_floating_texts(floating_texts, p_hits)
            if p_kills > 0:
                kill_count += p_kills
                kill_flash = 1.0

        # --- 敌人 AI ---
        update_enemies(enemies, pos_x, pos_y, dt, doors)

        # 飘字推进 + 击杀闪屏衰减
        update_floating_texts(floating_texts, dt)
        if kill_flash > 0:
            kill_flash = max(0.0, kill_flash - dt * 3.0)

        # --- 门扉更新 ---
        update_doors(doors, pos_x, pos_y, dt)

        # 是否有可交互门扉 (用于显示提示)
        interact_door = nearest_door_in_range(doors, pos_x, pos_y)

        # --- 传送门检测 ---
        if transition_cooldown > 0:
            transition_cooldown = max(0.0, transition_cooldown - dt)
        elif transitions:
            for t in transitions:
                if math.hypot(t["x"] - pos_x, t["y"] - pos_y) < 0.5:
                    # 触发地图切换
                    new_doors, new_enemies, new_transitions = switch_map(
                        t["target_map"], t["target_x"], t["target_y"])
                    if new_doors is not None:
                        doors = new_doors
                        enemies = new_enemies
                        transitions = new_transitions
                        pos_x = t["target_x"]
                        pos_y = t["target_y"]
                        projectiles = []
                        floating_texts = []
                        transition_cooldown = 1.0
                        kill_flash = 0.0
                    break

        # --- 渲染 ---
        draw_floor_ceiling(screen)
        cast_rays(screen, z_buffer, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y, doors)

        # 准星锁定检测: 屏幕中央列是否有可见敌人
        target_locked = False
        inv_det_chk = 1.0 / (plane_x * dir_y - dir_x * plane_y)
        for e in enemies:
            if e["death_t"] is not None:
                continue
            esx = e["x"] - pos_x
            esy = e["y"] - pos_y
            etx = inv_det_chk * (dir_y * esx - dir_x * esy)
            ety = inv_det_chk * (-plane_y * esx + plane_x * esy)
            if ety <= 0.5:
                continue
            esx_screen = (SCREEN_W / 2) * (1 + etx / ety)
            if abs(esx_screen - SCREEN_W / 2) > 12:
                continue
            if ety >= z_buffer[SCREEN_W // 2]:
                continue  # 被墙遮挡
            if ety > 8.0:
                continue  # 太远
            target_locked = True
            break

        render_enemies(screen, enemies, z_buffer, pos_x, pos_y,
                       dir_x, dir_y, plane_x, plane_y, enemy_sprites)
        render_portals(screen, transitions, z_buffer, pos_x, pos_y,
                       dir_x, dir_y, plane_x, plane_y, portal_sprite)
        render_projectiles(screen, projectiles, z_buffer, pos_x, pos_y,
                           dir_x, dir_y, plane_x, plane_y, projectile_sprites)
        draw_floating_texts(screen, floating_texts, z_buffer, pos_x, pos_y,
                            dir_x, dir_y, plane_x, plane_y, font_small)
        draw_crosshair(screen, target_locked)
        # 近战武器才显示锤子视图; 飞弹武器不画 (用准星瞄准)
        if weapon.get("type") == "melee":
            draw_hammer(screen, hammer_surf, swing_t)
        draw_minimap(screen, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y, enemies, doors, transitions)
        draw_hud(screen, font_big, font_small, enemies, kill_count, swing_t, swing_active,
                 interact_door is not None, kill_flash,
                 weapon=weapon, weapon_idx=current_weapon_idx,
                 cooldown_t=cooldown_t, projectiles=projectiles)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
