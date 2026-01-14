import pygame
import threading
import random
import math
from config import *
from simulation import sim_manager
from map_system import house_map, SpriteLoader
from agent_brain import AgentBrain, GLOBAL_FOOD
from physics_utils import calculate_fanger_pmv, pmv_to_comfort_score, get_sensation_string

class Character(pygame.sprite.Sprite):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.name = config["name"]
        self.brain = AgentBrain(config["name"], config["role"])
        
        self.frames = SpriteLoader().get_frames(config["sprite"], config["color"])
        self.direction = DIR_DOWN
        self.current_frame = 0
        self.image = self.frames[DIR_DOWN][0]
        self.rect = self.image.get_rect(topleft=config["spawn"])
        self.pos = pygame.math.Vector2(config["spawn"])
        self.bed_pos = house_map.anchors.get(f"Sleep_{self.name}", config["spawn"])
        
        self.speed = 8.0 
        self.ai_thread = None
        self.last_think_tick = 0
        self.think_cooldown = 3000 

        self.status = "Idle"
        self.current_room = "LivingRoom"
        self.last_room = "LivingRoom" 
        self.path = []
        self.target_action = None
        self.current_thought = "Ready."
        self.bubble_timer = 0
        
        self.doing_action_timer = 0
        
        self.hunger = 80.0
        self.energy = 80.0
        self.happiness = 80.0
        
        self.visual_comfort = 1.0 
        self.current_pmv = 0.0
        self.current_sensation = "Neutral"
        self.clothing_level = 0.5 

    def reset_state(self):
        self.pos = pygame.math.Vector2(self.bed_pos)
        self.rect.center = (int(self.pos.x), int(self.pos.y))
        self.status = "Idle" 
        self.hunger = 60.0   
        self.energy = 100.0  
        self.happiness = 80.0
        self.path = []       
        self.clothing_level = 0.5 
        self.current_thought = "Waking up to a new day..."
        self.target_action = None
        self.doing_action_timer = 0
        self.brain.reset_daily_memory()
        self.update_physics()
        print(f"🔄 {self.name} respawned at Bed")

    def get_physio_state(self):
        clo = self.clothing_level
        if self.status == "Sleeping": clo = max(clo, 1.0) 
        met = 1.0 
        if self.status == "Sleeping": met = 0.7
        elif self.status == "Moving": met = 1.7
        elif self.doing_action_timer > 0:
            if self.target_action == "Play": met = 2.0 
        return clo, met

    def run_ai_thread(self, all_sprites, current_bill, last_hour_cost, waste_alert):
        try:
            with sim_manager.lock: 
                h = sim_manager.current_hour
                house_data = {}
                for room_name in ["LivingRoom", "MasterRoom", "KidsRoom"]:
                    t = sim_manager.zone_data.get(room_name, (20,50))[0]
                    sp = sim_manager.get_setpoint(room_name)
                    house_data[room_name] = {"temp": t, "setpoint": sp}

            temp = house_data.get(self.current_room, {"temp": 20})["temp"]

            state = {
                "hour": h % 24,
                "hunger": self.hunger, 
                "energy": self.energy,
                "happy": self.happiness,
                "comfort": self.visual_comfort, 
                "pmv": self.current_pmv,          
                "sensation": self.current_sensation, 
                "clothing": self.clothing_level, 
                "room": self.current_room, 
                "temp": temp,
                "house_data": house_data,
                "current_bill": current_bill,       
                "last_hour_cost": last_hour_cost,
                "waste_alert": waste_alert # 🔥 传入环境警告
            }
            decision = self.brain.think(state)
            self.process_decision(decision, all_sprites, h % 24)
        except Exception as e:
            print(f"AI Error: {e}")
        finally:
            self.ai_thread = None
            if self.status == "Thinking": 
                self.status = "Idle"

    def process_decision(self, d, all_sprites, hour):
        action = d.get("action", "Idle").strip()
        target = d.get("target")
        thought = d.get("thought", "...")
        msg = d.get("message", "")

        self.current_thought = f"{action}: {thought}"
        self.bubble_timer = 300 
        self.target_action = action
        
        try:
            cur_temp = sim_manager.zone_data.get(self.current_room, (25,0))[0]
            sp = sim_manager.get_setpoint(self.current_room)
            self.brain.record_action(action, cur_temp, sp > 0)
        except: pass

        if action == "Adjust_Clothing":
            try:
                val = float(str(target).replace("clo", "").strip())
                self.clothing_level = max(0.3, min(1.5, val))
                self.current_thought = f"Clothing -> {self.clothing_level} clo."
            except: pass
            self.status = "Idle"
            return

        if action == "Adjust_AC":
            target_room = self.current_room 
            target_val = 24.0
            if target:
                tgt_str = str(target)
                if ":" in tgt_str:
                    try: 
                        parts = tgt_str.split(":")
                        target_room = parts[0].strip(); target_val = float(parts[1])
                    except: pass
                else:
                    try: target_val = float(tgt_str)
                    except: pass
            sim_manager.set_setpoint(target_room, target_val)
            self.status = "Idle" 
            return

        if action == "Eat":
            if self.current_room == "Kitchen":
                self.execute_instant_action("Eat")
                return
            else:
                self.current_thought = "Going to Kitchen to Eat..."
                self._set_path(house_map.anchors.get("Table", (800, 200)))
                return

        if action == "Cook":
            # 🔥🔥🔥 修复点：允许所有角色尝试做饭（Prompt 已限制 Son 不会做）
            if self.current_room == "Kitchen":
                self.execute_instant_action("Cook")
                return
            else:
                self.current_thought = "Going to Stove to Cook..."
                self._set_path(house_map.anchors.get("Stove", (850, 160)))
                return

        if action == "Play" or action == "Watch_TV":
            target_pos = house_map.anchors.get("ToyBox") if (action=="Play" and self.name=="Son") else house_map.anchors.get("Sofa")
            if target_pos and self.pos.distance_to(pygame.math.Vector2(target_pos)) < 40:
                self.doing_action_timer = 200 
                self.status = "Busy" 
                self.current_thought = f"{action}ing... (Fun!)"
            else:
                self.current_thought = f"Going to {action}..."
                self._set_path(target_pos)
            return

        is_night_sleep_time = (hour >= 22.0 or hour < 6.0)
        if hour >= 21.0 and hour < 22.0:
            if self.pos.distance_to(pygame.math.Vector2(self.bed_pos)) > 20:
                 self.current_thought = "Heading to bed early..."
                 self._set_path(self.bed_pos)
                 return

        if is_night_sleep_time or action == "Sleep":
            if self.pos.distance_to(pygame.math.Vector2(self.bed_pos)) > 20:
                self._set_path(self.bed_pos); self.target_action = "Sleep" 
            else:
                self.status = "Sleeping"
            return

        if action == "Chat":
            target_sprite = next((s for s in all_sprites if s.name == target), None)
            if target_sprite:
                if self.pos.distance_to(target_sprite.pos) < 80: 
                    target_sprite.brain.receive_message(self.name, msg)
                    self.status = "Idle"
                    self.current_thought = f"Said: {msg}"
                else:
                    self.current_thought = f"Finding {target} to chat..."
                    self.target_action = "Find_Person" 
                    self._set_path(target_sprite.pos)
            return

        if action == "Move_To":
            dest = house_map.get_target_coord("Move_To", target)
            self._set_path(dest)
        elif action == "Find_Person":
            target_sprite = next((s for s in all_sprites if s.name == target), None)
            if target_sprite: self._set_path(target_sprite.pos)

    def _set_path(self, target_pos):
        if target_pos:
            t = pygame.math.Vector2(target_pos)
            self.path = house_map.pathfinder.find_path(self.pos, (t.x, t.y))
            if self.path: self.status = "Moving"
            else: self.status = "Idle"

    def execute_instant_action(self, action_type):
        if action_type == "Eat":
            if GLOBAL_FOOD.try_eat():
                self.hunger = 100.0 
                self.energy = min(100.0, self.energy + 20)
                self.current_thought = "Ate instantly! Yum."
            else:
                self.current_thought = "Table empty! Hungry..."
        elif action_type == "Cook":
            GLOBAL_FOOD.add_food(3)
            self.energy = min(100.0, self.energy + 5) 
            self.current_thought = "Cooked instantly! Food on table."
        self.status = "Idle"
        self.target_action = None

    def update(self, all_sprites, current_bill, last_hour_cost, waste_alert):
        self.update_physics() 

        # 🔥🔥🔥 强制睡觉逻辑：如果到了 21:00 还没有在睡觉/去床的路上，强制中断
        with sim_manager.lock: h = sim_manager.current_hour
        hour = h % 24
        if hour >= 21.0 or hour < 6.0:
            if self.status != "Sleeping" and self.target_action != "Sleep":
                self.doing_action_timer = 0 # 打断娱乐
                self.target_action = "Sleep"
                self._set_path(self.bed_pos)
                self.current_thought = "Go to bed NOW!"
        
        if self.doing_action_timer > 0:
            self.doing_action_timer -= 1
            if self.target_action in ["Play", "Watch_TV"]:
                 self.happiness = min(100, self.happiness + 0.3)
            if self.doing_action_timer <= 0:
                self.status = "Idle"; self.target_action = None; self.current_thought = "Done."
            return 

        if self.status == "Moving" and self.path:
            t = pygame.math.Vector2(self.path[0])
            v = t - self.pos
            if v.length() < self.speed:
                self.pos = pygame.math.Vector2(self.path.pop(0))
            else:
                v.normalize_ip(); self.pos += v * self.speed
            self.rect.center = (int(self.pos.x), int(self.pos.y))
            if abs(v.x)>abs(v.y): self.direction = DIR_RIGHT if v.x>0 else DIR_LEFT
            else: self.direction = DIR_DOWN if v.y>0 else DIR_UP
            self.image = self.frames[self.direction][int(self.current_frame)%4]
        
        elif self.status == "Moving" and not self.path:
            # 移动到达后，瞬间执行吃饭/做饭
            if self.target_action in ["Eat", "Cook"]:
                if (self.target_action == "Eat" and self.current_room != "Kitchen") or \
                   (self.target_action == "Cook" and self.current_room != "Kitchen"):
                    self.status = "Idle" 
                else:
                    self.execute_instant_action(self.target_action)
            elif self.target_action == "Sleep":
                self.status = "Sleeping"
            elif self.target_action in ["Play", "Watch_TV"]:
                self.doing_action_timer = 200; self.status = "Busy"
            else:
                self.status = "Idle"

        if self.status == "Sleeping":
            self.energy = min(100, self.energy + 0.3)
            self.happiness = min(100, self.happiness + 0.1)
        
        current_time = pygame.time.get_ticks()
        if self.ai_thread is None and (current_time - self.last_think_tick > self.think_cooldown):
            should_think = False
            if len(self.brain.incoming_messages) > 0: should_think = True
            elif self.status == "Idle": should_think = True
            elif self.status == "Sleeping" and random.random() < 0.02: should_think = True

            if should_think:
                if self.status != "Sleeping": self.status = "Thinking"
                self.ai_thread = threading.Thread(target=self.run_ai_thread, args=(all_sprites, current_bill, last_hour_cost, waste_alert))
                self.ai_thread.start()
                self.last_think_tick = current_time

        if self.bubble_timer > 0: self.bubble_timer -= 1

    def update_physics(self):
        new_room = house_map.get_zone_at(self.pos)
        if new_room != self.last_room:
            self.current_room = new_room; self.last_room = new_room; self.last_think_tick = -9999 
        else:
            self.current_room = new_room

        try: 
            z_data = sim_manager.zone_data.get(self.current_room, (25.0, 50.0))
            air_temp = z_data[0]; rh = z_data[1]
        except: 
            air_temp = 25.0; rh = 50.0
        
        clo, met = self.get_physio_state()

        self.current_pmv = calculate_fanger_pmv(ta=air_temp, tr=air_temp, vel=0.1, rh=rh, met=met, clo=clo)
        self.current_sensation = get_sensation_string(self.current_pmv)
        base_comfort = pmv_to_comfort_score(self.current_pmv)
        
        clothing_penalty = 0.0
        if self.status != "Sleeping": 
            if clo > 0.8: clothing_penalty = (clo - 0.8) * 0.1 
            elif clo < 0.4: clothing_penalty = 0.05 
            
        self.visual_comfort = max(0.0, base_comfort - clothing_penalty)
        
        if self.status != "Sleeping":
            self.hunger = max(0, self.hunger - 0.08)
            self.energy = max(0, self.energy - 0.04)
            if self.target_action not in ["Play", "Watch_TV"]:
                self.happiness = max(0, self.happiness - 0.05)

    def draw(self, screen, font):
        # 1. 绘制角色本身
        screen.blit(self.image, self.rect)
        
        # 2. 绘制状态点
        c = (0,255,0)
        if self.status=="Thinking": c=(0,0,255)
        if self.status=="Sleeping": c=(100,100,100)
        if self.status=="Busy": c=(255,165,0) 
        if self.hunger < 30: c = (255, 0, 0)
        pygame.draw.circle(screen, c, (self.rect.right, self.rect.top), 5)
        self.draw_ui(screen, font)
        # 3. 绘制气泡 (透明 + 自动分行)
        if self.bubble_timer > 0 and self.current_thought:
            # --- 自动分行逻辑 ---
            max_width = 180 # 气泡最大宽度
            words = self.current_thought.split(' ')
            lines = []
            current_line = ""
            
            for word in words:
                test_line = current_line + word + " "
                # 测试这一行加上新词会不会超宽
                if font.size(test_line)[0] < max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word + " "
            if current_line: lines.append(current_line)
            
            # --- 计算尺寸 ---
            line_height = font.get_linesize()
            bubble_width = 0
            for line in lines:
                w = font.size(line)[0]
                if w > bubble_width: bubble_width = w
            bubble_width += 20 # 左右留白
            bubble_height = len(lines) * line_height + 16 # 上下留白
            
            # --- 创建透明 Surface ---
            # flags=pygame.SRCALPHA 使其支持 Alpha 通道
            bubble_surf = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
            
            # 填充背景 (R, G, B, Alpha) -> Alpha=220 代表半透明
            bubble_surf.fill((255, 255, 240, 220)) 
            
            # 画边框
            pygame.draw.rect(bubble_surf, (50, 50, 50), bubble_surf.get_rect(), 1, border_radius=6)
            
            # --- 绘制每一行文字 ---
            text_y = 8
            for line in lines:
                text_surf = font.render(line, True, BLACK) # 文字用黑色
                bubble_surf.blit(text_surf, (10, text_y))
                text_y += line_height
            
            # --- 确定屏幕位置并防出界 ---
            dest_x = self.rect.centerx - bubble_width // 2
            dest_y = self.rect.top - bubble_height - 10
            
            # 屏幕边界检查
            if dest_x < UI_BAR_WIDTH: dest_x = UI_BAR_WIDTH + 5
            if dest_x + bubble_width > WINDOW_WIDTH: dest_x = WINDOW_WIDTH - bubble_width - 5
            if dest_y < 0: dest_y = self.rect.bottom + 10 # 如果上面没地儿了，就显示在下面
            
            # --- Blit 到主屏幕 ---
            screen.blit(bubble_surf, (dest_x, dest_y))

    def draw_ui(self, screen, font):
        x, y = self.rect.centerx-20, self.rect.top-25
        w, h = 40, 4
        comfort_col = (0, 255, 0) if self.visual_comfort > 0.8 else (255, 165, 0)
        if self.visual_comfort < 0.4: comfort_col = (255, 0, 0)
        pygame.draw.circle(screen, comfort_col, (x-5, y+10), 4)

        pygame.draw.rect(screen, (50,50,50), (x, y, w, h))
        pygame.draw.rect(screen, (255,140,0), (x, y, w*(self.hunger/100), h))
        y += 5
        pygame.draw.rect(screen, (50,50,50), (x, y, w, h))
        pygame.draw.rect(screen, (0,191,255), (x, y, w*(self.energy/100), h))
        y += 5
        pygame.draw.rect(screen, (50,50,50), (x, y, w, h))
        clo_ratio = (self.clothing_level - 0.3) / 1.2
        pygame.draw.rect(screen, (200,200,200), (x, y, w*clo_ratio, h))