import pygame
import heapq
import random
import os
from config import *
from simulation import sim_manager 

class SpriteLoader:
    def get_frames(self, n, c): 
        p=f"assets/{n}.png"
        return self.load_smart(p) if os.path.exists(p) else self.dummy(c)

    def load_smart(self, p):
        s = pygame.image.load(p)
        if pygame.display.get_init() and pygame.display.get_surface():
            try: s = s.convert_alpha()
            except: pass
        w, h = s.get_size()
        f = [[],[],[],[]]
        if w/h > 8: 
            tw, th = w//24, h
            dw, dh = tw*SPRITE_SCALE, th*SPRITE_SCALE
            a = [pygame.transform.scale(s.subsurface((i*tw, 0, tw, th)), (dw, dh)) for i in range(24)]
            f[DIR_RIGHT] = a[0:6]; f[DIR_UP] = a[6:12]; f[DIR_LEFT] = a[12:18]; f[DIR_DOWN] = a[18:24]
        else:
            c, r = 9, 4
            fw, fh = w//c, h//r
            dw, dh = fw*SPRITE_SCALE, fh*SPRITE_SCALE
            m = {0:2, 1:1, 2:3, 3:0}
            for ri in range(r):
                if ri in m: 
                    for ci in range(c): 
                        sub = s.subsurface((ci*fw, ri*fh, fw, fh))
                        f[m[ri]].append(pygame.transform.scale(sub, (dw, dh)))
        return f

    def dummy(self, c):
        f = []
        sz = 48
        for d in range(4):
            dfs = []
            for _ in range(3): 
                s = pygame.Surface((sz, sz)); s.fill(c); pygame.draw.rect(s, BLACK, s.get_rect(), 2); dfs.append(s)
            f.append(dfs)
        return f

class Node:
    def __init__(self, gp): self.gp=gp; self.g=0; self.h=0; self.f=0; self.parent=None
    def __lt__(self, o): return self.f < o.f

class PathFinder:
    def __init__(self, w, h, size, walls, furn):
        self.gs=size; self.cols=w//size; self.rows=h//size
        self.grid=[[0]*self.rows for _ in range(self.cols)]
        obstacles = []
        obstacles.extend(walls)
        for f in furn:
            if isinstance(f, dict) and "rect" in f: obstacles.append(f["rect"].inflate(-15, -15))
            else: obstacles.append(f)
        for o in obstacles:
            sc,ec=max(0,o.left//size),min(self.cols-1,o.right//size)
            sr,er=max(0,o.top//size),min(self.rows-1,o.bottom//size)
            for c in range(sc,ec+1):
                for r in range(sr,er+1): self.grid[c][r]=1
    
    def get_neighbors(self, n):
        nb=[]
        for dc,dr in [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]:
            nc,nr=n.gp[0]+dc,n.gp[1]+dr
            if 0<=nc<self.cols and 0<=nr<self.rows and self.grid[nc][nr]==0:
                if abs(dc)==1 and abs(dr)==1:
                    if self.grid[n.gp[0]+dc][n.gp[1]]==1 or self.grid[n.gp[0]][n.gp[1]+dr]==1: continue
                nb.append(Node((nc,nr)))
        return nb

    def is_walkable(self, px, py):
        gc = int(px // self.gs)
        gr = int(py // self.gs)
        if 0 <= gc < self.cols and 0 <= gr < self.rows:
            return self.grid[gc][gr] == 0
        return False

    def find_path(self, start, end):
        sg=(int(start[0]//self.gs),int(start[1]//self.gs))
        eg=(int(end[0]//self.gs),int(end[1]//self.gs))
        if self.grid[sg[0]][sg[1]]==1 or self.grid[eg[0]][eg[1]]==1: return []
        opens=[]; closed=set(); heapq.heappush(opens,Node(sg))
        steps = 0
        while opens and steps < 4000:
            steps += 1
            curr=heapq.heappop(opens); closed.add(curr.gp)
            if curr.gp == eg:
                path=[]
                while curr: path.append(pygame.math.Vector2(curr.gp[0]*self.gs+self.gs//2,curr.gp[1]*self.gs+self.gs//2)); curr=curr.parent
                return path[::-1]
            for n in self.get_neighbors(curr):
                if n.gp in closed: continue
                cost=1.4 if n.gp[0]!=curr.gp[0] and n.gp[1]!=curr.gp[1] else 1.0
                tg=curr.g+cost
                nin=next((x for x in opens if x.gp==n.gp),None)
                if nin is None or tg<nin.g:
                    n.g=tg; n.h=abs(n.gp[0]-eg[0])+abs(n.gp[1]-eg[1]); n.f=n.g+n.h; n.parent=curr
                    if nin is None: heapq.heappush(opens,n)
        return []

class HouseMap:
    def __init__(self):
        self.walls, self.furniture = [], []
        self.anchors = {}
        self.build_house()
        self.pathfinder = PathFinder(MAP_WIDTH, MAP_HEIGHT, GRID_SIZE, self.walls, self.furniture)
        
    def build_house(self):
        w, h, t = MAP_WIDTH, MAP_HEIGHT, 20
        self.walls = [pygame.Rect(0,0,w,t), pygame.Rect(0,h-t,w,t), pygame.Rect(0,0,t,h), pygame.Rect(w-t,0,t,h),
                      pygame.Rect(350,0,t,150), pygame.Rect(350,250,t,300), pygame.Rect(350,650,t,150),
                      pygame.Rect(0,384,350,t), pygame.Rect(700,0,t,300), pygame.Rect(700,450,t,350)]
        self.zones = {
            "MasterRoom": pygame.Rect(0, 0, 350, 384),
            "KidsRoom":   pygame.Rect(0, 384, 350, 384),
            "LivingRoom": pygame.Rect(350, 0, 674, 768)
        }
        self.furniture = [
            {"rect": pygame.Rect(50,50,160,180), "name": "Parents Bed"},
            {"rect": pygame.Rect(50,450,100,150), "name": "Kids Bed"},
            {"rect": pygame.Rect(50,650,120,80), "name": "Toy Box"},
            {"rect": pygame.Rect(720,50,250,80), "name": "Stove"},
            {"rect": pygame.Rect(800,200,120,120), "name": "Dining Table"},
            {"rect": pygame.Rect(450,50,150,50), "name": "TV"},
            {"rect": pygame.Rect(450,250,150,80), "name": "Sofa"}
        ]
        self.anchors = {
            "Sleep_Dad": (250, 150), "Sleep_Mom": (250, 200), "Sleep_Son": (200, 500),
            "Table": (760, 260), "Stove": (850, 160), "Sofa": (520, 360), "ToyBox": (200, 680),
        }

    def get_zone_at(self, pos):
        for name, rect in self.zones.items():
            if rect.collidepoint(pos.x, pos.y): return name
        return "LivingRoom"

    def get_target_coord(self, action, name, mom_pos=None):
        base_pos = None
        if action == "Find_Mom" and mom_pos: base_pos = mom_pos
        else:
            key = f"{action}_{name}"
            if key in self.anchors: base_pos = self.anchors[key]
            elif action == "Sleep": base_pos = self.anchors.get(f"Sleep_{name}", (100, 100))
            elif action == "Eat": base_pos = self.anchors["Table"]
            elif action == "Cook": base_pos = self.anchors["Stove"]
            elif action == "Watch_TV": base_pos = self.anchors["Sofa"]
            elif action == "Play": base_pos = self.anchors["ToyBox"] if name == "Son" else self.anchors["Sofa"]
            elif action == "Move_To": 
                if name == "LivingRoom": base_pos = (500, 300)
                elif name == "MasterRoom": base_pos = (200, 200)
                elif name == "KidsRoom": base_pos = (200, 600)
        
        if base_pos:
            for _ in range(10):
                rx = random.randint(-40, 40); ry = random.randint(-40, 40)
                candidate = (base_pos[0] + rx, base_pos[1] + ry)
                if self.pathfinder.is_walkable(candidate[0], candidate[1]): return candidate
            return base_pos
        return (500, 400)

    def draw(self, screen):
        screen.fill(FLOOR_COLOR)
        with sim_manager.lock:
            zone_data = sim_manager.zone_data
            sps = {"LivingRoom": sim_manager.get_setpoint("LivingRoom"), "MasterRoom": sim_manager.get_setpoint("MasterRoom"), "KidsRoom": sim_manager.get_setpoint("KidsRoom")}
        font_room = pygame.font.SysFont("arial", 20, bold=True)
        font_furn = pygame.font.SysFont("arial", 14, italic=True)

        for z_name, rect in self.zones.items():
            t, rh = zone_data.get(z_name, (20.0, 50.0))
            color_int = int(max(0, min(255, (t - 15) * 20)))
            zone_color = (color_int, 100, 255 - color_int, 50) 
            s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            s.fill(zone_color)
            screen.blit(s, rect.topleft)
            
            sp_val = sps.get(z_name)
            sp_txt = f"Set:{sp_val:.0f}" if sp_val > 0 else "OFF"
            
            txt_surf = font_room.render(z_name, True, (50,50,50))
            bg_rect = txt_surf.get_rect(topleft=(rect.x + 40, rect.y + 10))
            pygame.draw.rect(screen, (255,255,255,180), bg_rect)
            screen.blit(txt_surf, (rect.x + 40, rect.y + 10))
            
            info_text = f"{t:.1f}C / {rh:.0f}% ({sp_txt})"
            info_surf = font_furn.render(info_text, True, BLACK)
            screen.blit(info_surf, (rect.x + 40, rect.y + 35))

        for w in self.walls: pygame.draw.rect(screen, WALL_COLOR, w)
        for f in self.furniture: 
            pygame.draw.rect(screen, (139,69,19), f["rect"])
            pygame.draw.rect(screen, (100,50,0), f["rect"], 3)
            t = font_furn.render(f["name"], True, (255,255,220))
            screen.blit(t, (f["rect"].centerx - t.get_width()//2, f["rect"].centery - t.get_height()//2))
            
            # 🔥🔥🔥 绘制桌子上的食物 (红点)
            if f["name"] == "Dining Table":
                food_cnt = GLOBAL_GAME_STATE.get("food_servings", 0)
                if food_cnt > 0:
                    for i in range(min(5, food_cnt)):
                        pygame.draw.circle(screen, (255, 0, 0), (f["rect"].x + 20 + i*15, f["rect"].y + 20), 5)

house_map = HouseMap()