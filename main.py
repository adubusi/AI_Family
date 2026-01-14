import pygame
import sys
import os
import multiprocessing
import threading
import traceback 
from config import *
from simulation import sim_manager
from map_system import house_map
from agent_sprite import Character 
from agent_brain import GLOBAL_FOOD

class Button:
    def __init__(self, x, y, w, h, text, callback):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text; self.callback = callback; self.hover = False; self.enabled = True; self.font = pygame.font.SysFont("arial", 18, bold=True)
    def update_text(self, new_text): self.text = new_text
    def set_enabled(self, val): self.enabled = val
    def draw(self, screen):
        color = (0, 180, 0) if (self.hover and self.enabled) else ((50, 50, 50) if self.enabled else (60, 60, 60))
        pygame.draw.rect(screen, color, self.rect, border_radius=8)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 2, border_radius=8)
        txt_surf = self.font.render(self.text, True, WHITE)
        screen.blit(txt_surf, (self.rect.centerx - txt_surf.get_width()//2, self.rect.centery - txt_surf.get_height()//2))
    def handle_event(self, event):
        if not self.enabled: return False
        if event.type == pygame.MOUSEMOTION: self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and self.hover: self.callback(); return True
        return False

def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption(f"AI Family: Waste Detection & Social Cooking")
    clock = pygame.time.Clock()
    
    font = pygame.font.SysFont("arial", 16)
    title_font = pygame.font.SysFont("arial", 24, bold=True)
    game_surface = pygame.Surface((MAP_WIDTH, MAP_HEIGHT))
    
    sim_manager.start()
    
    sprites = pygame.sprite.Group()
    roster = [
        {"name": "Mom", "role": "PROVIDER", "color": (255,100,100), "spawn": (120, 200), "sprite": "Mom"}, 
        {"name": "Dad", "role": "PROVIDER", "color": (100,100,255), "spawn": (200, 250), "sprite": "Dad"}, 
        {"name": "Son", "role": "CONSUMER", "color": (100,255,100), "spawn": (150, 600), "sprite": "Son"}  
    ]
    
    agent_list = [Character(cfg) for cfg in roster]
    for a in agent_list: sprites.add(a)
    
    state_ctx = {
        "running": True, "mode": 0, "day": 1,
        "waste": {"LivingRoom": 0.0, "MasterRoom": 0.0, "KidsRoom": 0.0},
        "pmv_sum": 0, "pmv_count": 0, "last_h": 0.0, 
        "reflection_threads_started": False, "reflections_ready": False,
        
        "hourly_log": [],      
        "prev_bill": 0.0,      
        "last_hour_cost": 0.0, 
        "last_logged_hour": -1
    }

    def start_next_day():
        print(f"🔄 Starting Day {state_ctx['day'] + 1}...")
        sim_manager.restart()
        for s in sprites: s.reset_state()
        state_ctx['mode'] = 0; state_ctx['day'] += 1
        state_ctx['last_h'] = 0.0 
        state_ctx['waste'] = {k: 0.0 for k in state_ctx['waste']}
        state_ctx['pmv_sum'] = 0; state_ctx['pmv_count'] = 0
        state_ctx['reflection_threads_started'] = False; state_ctx['reflections_ready'] = False
        
        state_ctx['hourly_log'] = []
        state_ctx['prev_bill'] = 0.0
        state_ctx['last_hour_cost'] = 0.0
        state_ctx['last_logged_hour'] = -1
        
        btn_next.set_enabled(False); btn_next.update_text("Day in Progress...")

    btn_next = Button(60, WINDOW_HEIGHT - 80, 200, 50, "Day in Progress...", start_next_day)
    btn_next.set_enabled(False) 

    while state_ctx["running"]:
        dt = clock.tick(30) / 1000.0 
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT: state_ctx["running"] = False
            btn_next.handle_event(event)

        try:
            with sim_manager.lock:
                h = sim_manager.current_hour
                price, power, bill, out_temp = sim_manager.energy_data
                zones = sim_manager.zone_data
        except:
            h = 12.0; bill = 0; zones = {}; out_temp = 0.0

        current_hour_int = int(h)
        if current_hour_int != state_ctx['last_logged_hour']:
            delta = bill - state_ctx['prev_bill']
            if delta < 0: delta = 0 
            
            current_pmvs = [s.current_pmv for s in sprites]
            avg_pmv = sum(current_pmvs) / max(1, len(current_pmvs))
            
            state_ctx['hourly_log'].append({
                'hour': current_hour_int, 
                'cost': delta,
                'avg_pmv': avg_pmv 
            })
            
            state_ctx['last_hour_cost'] = delta 
            state_ctx['prev_bill'] = bill
            state_ctx['last_logged_hour'] = current_hour_int

        # 🔥🔥🔥 实时计算浪费警告 (Waste Alert) 🔥🔥🔥
        # 逻辑：如果房间空调开着 (Setpoint > 0) 且房间里没人 -> 这是一个严重的警告
        occupancy = {k: False for k in zones.keys()}
        for s in sprites: occupancy[s.current_room] = True
        
        waste_warnings = []
        for room, (temp, rh) in zones.items():
            sp = sim_manager.get_setpoint(room)
            if sp > 0 and not occupancy.get(room, False):
                # 累积浪费分数/时间
                state_ctx['waste'][room] += dt * 0.1
                # 生成警告信息
                waste_warnings.append(f"{room} AC is ON but EMPTY!")

        waste_alert_str = "None"
        if waste_warnings:
            waste_alert_str = " | ".join(waste_warnings)

        ep_process_dead = (sim_manager.p is not None) and (not sim_manager.p.is_alive())
        time_limit_reached = (h > 23.5)

        if (ep_process_dead or time_limit_reached) and state_ctx["mode"] == 0:
            state_ctx["mode"] = 1
            if not ep_process_dead: sim_manager.pause_time()
            print(f"\n🌙 End of Day. Bill: {bill:.2f}")
            print(f"🗑️ Waste Report: {state_ctx['waste']}") # 打印当日浪费情况

        state_ctx['last_h'] = h

        if state_ctx["mode"] == 0:
            # 🔥 将 waste_alert_str 传递给 sprites
            sprites.update(agent_list, bill, state_ctx['last_hour_cost'], waste_alert_str)
            total_comfort = sum([s.visual_comfort for s in sprites])
            state_ctx['pmv_sum'] += (1.0 - total_comfort/len(sprites))
            state_ctx['pmv_count'] += 1
        
        screen.fill(UI_BG_COLOR)
        house_map.draw(game_surface)
        for s in sprites: s.draw(game_surface, font)
        
        if state_ctx["mode"] == 1:
            overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            game_surface.blit(overlay, (0,0))
            status_txt = "Analyzing Behavior..." if not state_ctx["reflections_ready"] else "Evolution Complete."
            status_surf = title_font.render(status_txt, True, WHITE)
            game_surface.blit(status_surf, (MAP_WIDTH//2 - status_surf.get_width()//2, MAP_HEIGHT//2))

        screen.blit(game_surface, (UI_BAR_WIDTH, 0))
            
        x, y = 20, 30
        screen.blit(title_font.render(f"Day {state_ctx['day']} | {h:.1f}h", True, WHITE), (x, y)); y+=40
        out_c = (100, 200, 255) if out_temp < 10 else ((255, 100, 100) if out_temp > 28 else WHITE)
        screen.blit(font.render(f"Outdoor: {out_temp:.1f}C", True, out_c), (x, y)); y+=30
        screen.blit(font.render(f"Food: {GLOBAL_FOOD.get_count()}", True, WHITE), (x, y)); y+=30
        
        budget_left = DAILY_BUDGET_LIMIT - bill
        b_col = GREEN if budget_left > 10 else (RED if budget_left < 0 else (255, 165, 0))
        screen.blit(font.render(f"Budget Left: ${budget_left:.2f}", True, b_col), (x, y)); y+=20
        screen.blit(font.render(f"Spent: ${bill:.2f}", True, WHITE), (x, y)); y+=30

        avg_comf = sum([s.visual_comfort for s in sprites]) / len(sprites)
        comf_c = GREEN if avg_comf > 0.8 else ((255, 255, 0) if avg_comf > 0.5 else RED)
        screen.blit(font.render(f"Avg Comfort: {avg_comf:.2f}", True, comf_c), (x, y)); y+=30
        
        # 显示严重警告
        if waste_alert_str != "None":
             screen.blit(font.render(f"⚠️ WASTE: {waste_alert_str}", True, RED), (x, y)); y+=30

        y += 20
        screen.blit(font.render("--- Agent Activity ---", True, SELECTION_COLOR), (x, y)); y+=25
        for s in sprites:
            thought_full = s.current_thought
            if len(thought_full) > 35: thought_full = thought_full[:32] + "..."
            txt = f"{s.name}: {thought_full}"
            screen.blit(font.render(txt, True, s.config['color']), (x, y)); y+=20
            
        if state_ctx["mode"] == 1:
            if not state_ctx["reflection_threads_started"]:
                state_ctx["reflection_threads_started"] = True
                avg_discomfort = state_ctx['pmv_sum'] / max(1, state_ctx['pmv_count'])
                
                btn_next.update_text("Reflecting...")
                btn_next.set_enabled(False)

                def run_reflections():
                    try:
                        threads = []
                        for s in sprites:
                            # 传递 waste (state_ctx['waste']) 给反思模块
                            t = threading.Thread(target=s.brain.reflect_and_plan, args=(bill, avg_discomfort, state_ctx['waste'], state_ctx['hourly_log']))
                            threads.append(t)
                            t.start()
                        for t in threads: t.join()
                    except Exception as e:
                        print(f"Thread Error: {e}")
                        traceback.print_exc()
                    finally:
                        state_ctx["reflections_ready"] = True
                
                threading.Thread(target=run_reflections, daemon=True).start()

            if state_ctx["reflections_ready"] and not btn_next.enabled:
                btn_next.update_text("START NEXT DAY")
                btn_next.set_enabled(True)
                
        btn_next.draw(screen)
        pygame.display.flip()
    
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    multiprocessing.freeze_support() 
    main()