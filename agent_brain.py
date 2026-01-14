import threading
import json
import os
import traceback
from openai import OpenAI
from config import *

# ==============================================================================
# 🛠️ 全局共享状态 (食物)
# ==============================================================================
class GlobalFoodState:
    def __init__(self):
        self.servings = 0
        self.lock = threading.Lock()

    def add_food(self, amount):
        with self.lock:
            self.servings += amount
            GLOBAL_GAME_STATE["food_servings"] = self.servings

    def try_eat(self):
        with self.lock:
            if self.servings > 0:
                self.servings -= 1
                GLOBAL_GAME_STATE["food_servings"] = self.servings
                return True
            return False

    def get_count(self):
        with self.lock:
            return self.servings

GLOBAL_FOOD = GlobalFoodState()

# ==============================================================================
# 📝 Prompts (新增：儿子找爸妈，爸妈都做饭，空调浪费警告)
# ==============================================================================

SYSTEM_INSTRUCTION_DAY = """
[SYSTEM: FAMILY SIMULATION]
You are {name}, the {role}.

🔥🔥🔥 [PRIME DIRECTIVE: WEIGHT INTERPRETATION] 🔥🔥🔥
**Comfort vs Cost Weight**: {balance_val} (Range: 0.0 to 1.0)
**Your Financial Tolerance**: ${cost_tolerance:.2f}/hour

[DECISION MATRIX BASED ON WEIGHT]
1. **IF WEIGHT = 1.0 (Pure Hedonist)**: 
   - IGNORE COST completely unless "Spending Sensation" says "BANKRUPT". 
   - Keep AC ON to maintain perfect comfort (PMV 0.0). 
   - Spending money is NOT a problem.
2. **IF WEIGHT = 0.0 (Pure Miser)**:
   - IGNORE COMFORT. If AC is on, turn it OFF immediately unless freezing/heatstroke.
3. **IF WEIGHT = 0.5**: Balance both normally.

**YESTERDAY'S LESSON**: "{daily_rule}"

[URGENT WASTE ALERT]
**{waste_alert}**
(If you see a room named here, you MUST go there and turn OFF the AC immediately! It is wasting huge money!)

[CRITICAL BIO-FEEDBACK]
1. **HUNGER ({hunger:.0f}%)**:
   - If Hunger < 80%: You are HUNGRY.
   - If Hunger < 40%: STARVING! Stop everything and [Eat].
2. **HAPPINESS ({happy:.0f}%)**:
   - If Happiness < 80%: BORED. Go [Play] or [Watch_TV].

[STATUS]
Time: {hour:.1f}h | Loc: {room}
**Sensation: {sensation}** (PMV={pmv:.2f})
Food in Kitchen: {food_info}

[HOUSE & WALLET]
{house_status}

[INCOMING MESSAGES]
{messages}

[ACTIONS]
- [Eat]: Restore hunger. (Must be in Kitchen).
- [Cook]: (Parents Only). Adds 3 food. (Must be in Kitchen).
- [Adjust_Clothing]: Target "0.3" to "1.5".
- [Adjust_AC]: Target "RoomName:Temp" or "RoomName:0" (to turn off).
- [Chat]: Target "Name", Content "Msg".
- [Move_To]: Target "Room".
- [Watch_TV]: Target "Sofa".
- [Play]: Target "ToyBox".
- [Sleep]: Go to bed.

[ACTION ENFORCEMENT]
⚠️ DO NOT just "think". OUTPUT THE ACTION.
- CORRECT: {{ "action": "Cook", "thought": "Cooking now!" }}
- IF you want to Cook but are not in Kitchen, OUTPUT "Cook" ANYWAY.
- IF you want to Chat, you must be close to them, or [Move_To] them first.

[DECISION LOGIC]
1. **WASTE CHECK**: Is there a WASTE ALERT? If yes, fix it NOW.
2. **FOOD LOGIC**: 
   - If Food=0 and you are Parent: [Cook].
   - If Food=0 and you are Son: Find Mom/Dad and [Chat] "I am hungry".
3. **WALLET CHECK**: Look at "Spending Sensation". Only react if it says "Above Tolerance" or "BANKRUPT".
4. **COMFORT CHECK**: If Sensation is NOT "Neutral", adjust AC.

Output JSON: {{"action": "...", "target": "...", "thought": "...", "message": "..."}}
"""

SYSTEM_INSTRUCTION_NIGHT = """
[SYSTEM: NIGHT TIME ({hour:.1f}h)]
You are {name}. It is NIGHT. You are in Bed.

[STATUS]
Room Temp: {temp:.1f}C | Clothing: {clothing:.1f} | Sensation: {sensation}

[INSTRUCTIONS]
1. **SLEEP**: If PMV is okay (-1.5 to +1.5), action MUST be "Sleep".
2. **EMERGENCY**: Only wake up ([Adjust_AC]) if extreme Cold/Hot.

Output JSON: {{"action": "Sleep" or "Adjust_AC", "target": "...", "thought": "..."}}
"""

ROLE_INSTRUCTION_MOM = """
- **PROVIDER (Mom)**: 
  1. If Food count is 0 OR you hear "hungry": [Cook]. 
  2. If Hunger < 85: [Eat].
"""

ROLE_INSTRUCTION_DAD = """
- **PROVIDER (Dad)**: 
  1. If Food count is 0 OR you hear "hungry": [Cook].
  2. Watch the wallet!
"""

ROLE_INSTRUCTION_SON = """
- **CHILD**: 
  1. **DO NOT COOK**. You cannot cook.
  2. If Hunger < 85: 
     - If Food > 0: [Eat].
     - If Food = 0: Find Mom or Dad and [Chat] "I am hungry".
  3. If Happy < 85: [Play]!
"""

# ==============================================================================
# 🧠 Agent Brain 类
# ==============================================================================
class AgentBrain:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        try:
            self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        except:
            self.client = None
            print(f"Warning: OpenAI client init failed for {name}")

        self.incoming_messages = []
        self.last_thought = ""
        self.daily_rule = "Balance comfort and cost." 
        self.memory_file = f"memory_{self.name}.json"
        self.load_memories()

    def load_memories(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.daily_rule = data.get("last_rule", self.daily_rule)
            except Exception as e:
                print(f"Load Memory Error: {e}")
    
    def reset_daily_memory(self):
        self.incoming_messages = []
        self.last_thought = "Waking up..."
        self.load_memories()

    def save_memories(self, new_rule):
        self.daily_rule = new_rule
        data = {"last_rule": new_rule}
        try:
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except: pass

    def receive_message(self, sender, content):
        msg = f"From {sender}: {content}"
        self.incoming_messages.append(msg)
        if len(self.incoming_messages) > 3:
            self.incoming_messages.pop(0)

    def reflect_and_plan(self, total_bill, avg_discomfort, waste_report, hourly_logs):
        if not self.client: return

        expensive_hours = sorted(hourly_logs, key=lambda x: x['cost'], reverse=True)
        max_cost_hour = expensive_hours[0] if expensive_hours else {'hour': 12, 'cost': 0}
        
        uncomfortable_hours = sorted(hourly_logs, key=lambda x: abs(x['avg_pmv']), reverse=True)
        max_discomfort_hour = uncomfortable_hours[0] if uncomfortable_hours else {'hour': 12, 'avg_pmv': 0}
        
        cost_issue = f"High Cost at {max_cost_hour['hour']}:00 (${max_cost_hour['cost']:.2f})."
        
        pmv_val = max_discomfort_hour['avg_pmv']
        sensation = "Neutral"
        if pmv_val > 1.5: sensation = "TOO HOT"
        elif pmv_val < -1.5: sensation = "TOO COLD"
        comfort_issue = f"Worst Comfort at {max_discomfort_hour['hour']}:00 ({sensation}, PMV={pmv_val:.1f})."

        # 🔥🔥🔥 WASTE ANALYSIS & PENALTY CALCULATION 🔥🔥🔥
        waste_penalty_section = ""
        total_waste_score = sum(waste_report.values())
        
        if total_waste_score > 1.0: # 只有当浪费值超过一定阈值才触发严重惩罚
            waste_rooms = [r for r, s in waste_report.items() if s > 0.5]
            waste_str = ", ".join(waste_rooms)
            waste_penalty_section = f"""
####################################################################
[⚠️ CRITICAL WASTE PENALTY ⚠️]
VIOLATION DETECTED: Air Conditioners were left running in EMPTY rooms!
Locations: {waste_str}
Result: A HUGE 'Virtual Fine' has been applied to your conscience.
CAUSE: You left the room without turning off the AC.
####################################################################
"""
        else:
            waste_penalty_section = "[Waste Check] Good job. No empty rooms were cooled unnecessarily."

        # 动态调整反思逻辑中的权重影响
        w = COMFORT_VS_COST_WEIGHT
        weight_guide = ""
        if w >= 0.8:
            weight_guide = "Since Weight > 0.8, IGNORE Cost issues unless we are totally bankrupt. FOCUS ON COMFORT."
        elif w <= 0.2:
            weight_guide = "Since Weight < 0.2, IGNORE Comfort issues. FOCUS ON SAVING MONEY."

        reflection_prompt = f"""
[REFLECTION TASK]
You are {self.name}.
Total Bill: ${total_bill:.2f} (Budget: ${DAILY_BUDGET_LIMIT})
Cost vs Comfort Weight: {COMFORT_VS_COST_WEIGHT} (0=Saver, 1=Comfort).
{weight_guide}

{waste_penalty_section}

[PROBLEMS]
1. {cost_issue}
2. {comfort_issue}

[ANALYSIS]
Compare your Weight ({COMFORT_VS_COST_WEIGHT}) with the problems.
1. **IF WASTE PENALTY EXISTS**: Your ONLY priority is to prevent this tomorrow. You MUST make a rule about turning off ACs.
2. If Weight is HIGH (>0.6) and you were Uncomfortable: Create a rule to FIX COMFORT.
3. If Weight is LOW (<0.4) and Bill is High: Create a rule to SAVE MONEY.
4. If Balanced: Try to solve the biggest problem.

Write a ONE SENTENCE strategic rule for tomorrow.
Output JSON: {{ "new_rule": "..." }}
"""
        try:
            resp = self.client.chat.completions.create(
                model="qwen-plus", 
                messages=[{"role":"system","content":reflection_prompt}],
                response_format={"type":"json_object"},
                timeout=30 
            )
            content = resp.choices[0].message.content
            res = json.loads(content)
            new_rule = res.get("new_rule", "Balance life.")
            self.save_memories(new_rule)
            print(f"[{self.name}] Reflection Complete. New Rule: {new_rule}") # Debug log
        except Exception as e:
            print(f"Reflection Error: {e}")

    def think(self, state_dict):
        if not self.client:
            return {"action": "Idle", "thought": "No Brain"}

        h = state_dict['hour']
        is_night = (h >= 22.0 or h < 6.0)

        current_bill = state_dict.get('current_bill', 0.0)
        last_hour_cost = state_dict.get('last_hour_cost', 0.0)
        waste_alert = state_dict.get('waste_alert', "None") # 🔥 获取环境警告

        budget_left = DAILY_BUDGET_LIMIT - current_bill
        
        # ==============================================================================
        # ⚖️ 动态归一化逻辑 (修复量级差异问题)
        # ==============================================================================
        w = COMFORT_VS_COST_WEIGHT
        
        # 1. 计算"心理价格容忍度" (Dynamic Cost Tolerance)
        # 基础每小时容忍度是 $0.5。
        # 如果 w=1.0 (享乐), 容忍度增加 $4.5 -> 总容忍 $5.0 (几乎可以忽略任何电费)
        # 如果 w=0.0 (吝啬), 容忍度增加 $0.0 -> 总容忍 $0.5 (非常敏感)
        base_tolerance = 0.5 
        dynamic_tolerance = base_tolerance + (w * 4.5)
        
        # 2. 生成"消费体感" (Spending Sensation)
        money_sensation = "Safe"
        if budget_left < 0: 
            money_sensation = "BANKRUPT!! (PANIC)"
        elif last_hour_cost > dynamic_tolerance: 
            money_sensation = f"Money is burning FAST! (Spent ${last_hour_cost:.2f} > Limit ${dynamic_tolerance:.2f})"
        elif last_hour_cost > (dynamic_tolerance * 0.7): 
            money_sensation = f"Expensive... (Approaching Limit ${dynamic_tolerance:.2f})"
        else:
            money_sensation = f"Safe (Within Budget)"

        # 3. 生成权重描述字符串
        if w >= 0.8: balance_desc = "PRIORITY: COMFORT. IGNORE BILLS."
        elif w >= 0.5: balance_desc = "PRIORITY: BALANCED."
        else: balance_desc = "PRIORITY: SAVINGS. SUFFERING IS ACCEPTABLE."
        # ==============================================================================

        house_status_str = ""
        if 'house_data' in state_dict:
            for r_name, r_data in state_dict['house_data'].items():
                house_status_str += f"- {r_name}: {r_data['temp']:.1f}C (Set:{r_data['setpoint']:.0f})\n"
        
        house_status_str += f"\n[WALLET]\nBudget Left: ${budget_left:.2f}\nSpending Sensation: {money_sensation}"

        if is_night:
            prompt = SYSTEM_INSTRUCTION_NIGHT.format(
                name=self.name, hour=h, temp=state_dict['temp'],
                sensation=state_dict.get('sensation', 'Neutral'), 
                clothing=state_dict.get('clothing', 0.5)
            )
        else:
            food_info = str(GLOBAL_FOOD.get_count())

            role_ins = ROLE_INSTRUCTION_MOM if self.name == "Mom" else (ROLE_INSTRUCTION_SON if self.name == "Son" else ROLE_INSTRUCTION_DAD)
            msgs_str = "\n".join(self.incoming_messages) if self.incoming_messages else "None."
            
            # 🔥 传入 dynamic_tolerance 和修正后的指令
            prompt = SYSTEM_INSTRUCTION_DAY.format(
                name=self.name, role=self.role, daily_rule=self.daily_rule, 
                balance_val=w, balance_desc=balance_desc,
                cost_tolerance=dynamic_tolerance, # 传入计算出的容忍度
                hour=h, hunger=state_dict['hunger'], energy=state_dict['energy'],
                happy=state_dict.get('happy', 50), sensation=state_dict.get('sensation', 'Neutral'), 
                pmv=state_dict.get('pmv', 0.0), clothing=state_dict.get('clothing', 0.5),
                room=state_dict['room'], house_status=house_status_str, 
                food_info=food_info, messages=msgs_str, role_instructions=role_ins,
                waste_alert=waste_alert
            )

        try:
            resp = self.client.chat.completions.create(
                model="qwen-plus", 
                messages=[{"role":"system","content":prompt}],
                response_format={"type":"json_object"},
                timeout=10
            )
            content = resp.choices[0].message.content.replace("```json", "").replace("```", "").strip()
            decision = json.loads(content)
            self.last_thought = decision.get("thought", "")
            if not is_night: self.incoming_messages = []
            return decision
        except Exception as e:
            print(f"Thinking Error ({self.name}): {e}")
            return {"action": "Sleep" if is_night else "Idle", "thought": "Brain freeze..."}