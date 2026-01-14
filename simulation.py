import sys
import os
import time
import math
import multiprocessing
import threading 
import ctypes
from config import *

# ==================================================================================
# 🌡️ 共享内存索引
# 0: Hour, 1-3: Temp, 4-6: Setpoint, 7: Price, 8: Power, 9: Bill
# 10-12: Humidity, 13: Outdoor Temp
# ==================================================================================

def run_energyplus_process(shared_array, pause_event):
    if os.name == 'nt':
        try: os.add_dll_directory(EPLUS_DIR)
        except: pass
    sys.path.insert(0, EPLUS_DIR)
    
    if not os.path.exists(WEATHER_FILE):
        print(f"❌ Error: Weather file not found: {WEATHER_FILE}")
        return

    from pyenergyplus.api import EnergyPlusAPI
    
    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    handles = {"init": False}

    def generate_robust_idf():
        print("📝 Generating IDF (1 Day)...")
        def to_idf_obj(obj_type, fields):
            lines = [f"  {obj_type},"]
            for i, f in enumerate(fields):
                terminator = ";" if i == len(fields) - 1 else ","
                lines.append(f"    {f}{terminator}")
            return "\n".join(lines) + "\n"

        def add_room_geometry(name, x, y, w, d, h, capacity):
            s = ""
            s += to_idf_obj("Zone", [name, "0", "0", "0", "0", "1", "1", str(h)])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Floor", "Floor", "FloorConst", name, "", "Ground", "", "NoSun", "NoWind", "", "4", f"{x}", f"{y+d}", "0", f"{x+w}", f"{y+d}", "0", f"{x+w}", f"{y}", "0", f"{x}", f"{y}", "0"])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Roof", "Roof", "RoofConst", name, "", "Outdoors", "", "SunExposed", "WindExposed", "", "4", f"{x}", f"{y+d}", f"{h}", f"{x+w}", f"{y+d}", f"{h}", f"{x+w}", f"{y}", f"{h}", f"{x}", f"{y}", f"{h}"])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Wall_S", "Wall", "WallConst", name, "", "Outdoors", "", "SunExposed", "WindExposed", "", "4", f"{x}", f"{y}", f"{h}", f"{x}", f"{y}", "0", f"{x+w}", f"{y}", "0", f"{x+w}", f"{y}", f"{h}"])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Wall_E", "Wall", "WallConst", name, "", "Outdoors", "", "SunExposed", "WindExposed", "", "4", f"{x+w}", f"{y}", f"{h}", f"{x+w}", f"{y}", "0", f"{x+w}", f"{y+d}", "0", f"{x+w}", f"{y+d}", f"{h}"])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Wall_N", "Wall", "WallConst", name, "", "Outdoors", "", "SunExposed", "WindExposed", "", "4", f"{x+w}", f"{y+d}", f"{h}", f"{x+w}", f"{y+d}", "0", f"{x}", f"{y+d}", "0", f"{x}", f"{y+d}", f"{h}"])
            s += to_idf_obj("BuildingSurface:Detailed", [f"{name}_Wall_W", "Wall", "WallConst", name, "", "Outdoors", "", "SunExposed", "WindExposed", "", "4", f"{x}", f"{y+d}", f"{h}", f"{x}", f"{y+d}", "0", f"{x}", f"{y}", "0", f"{x}", f"{y}", f"{h}"])
            s += to_idf_obj("ZoneControl:Thermostat", [f"{name}_Ctrl", name, "AlwaysOn", "ThermostatSetpoint:DualSetpoint", f"{name}_Therm"])
            s += to_idf_obj("ZoneHVAC:EquipmentConnections", [name, f"{name}_Eq", f"{name}_In", "", f"{name}_Node", f"{name}_Ret"])
            s += to_idf_obj("ZoneHVAC:EquipmentList", [f"{name}_Eq", "SequentialLoad", "ZoneHVAC:IdealLoadsAirSystem", f"{name}_HVAC", "1", "1"])
            s += to_idf_obj("ZoneHVAC:IdealLoadsAirSystem", [f"{name}_HVAC", "", f"{name}_In", "", "", "50", "", "", "", "LimitCapacity", "", str(capacity), "", "Autosize", "", "", "", "ConstantSensibleHeatRatio", "0.7"])
            return s

        idf_str = ""
        idf_str += to_idf_obj("Version", ["23.1"])
        idf_str += to_idf_obj("SimulationControl", ["No", "No", "No", "No", "Yes"])
        idf_str += to_idf_obj("Building", ["GameHouse", "0.0", "Suburbs", ".04", ".4", "FullExterior", "25", "6"])
        idf_str += to_idf_obj("Site:Location", ["Beijing", "39.9", "116.4", "8.0", "31.3"])
        idf_str += to_idf_obj("GlobalGeometryRules", ["UpperLeftCorner", "CounterClockwise", "World"])
        idf_str += to_idf_obj("Timestep", ["6"]) 
        idf_str += to_idf_obj("RunPeriod", ["GameRun", "1", "1", "", "1", "1", "", "Monday", "Yes", "Yes", "No", "Yes", "Yes"])
        idf_str += to_idf_obj("Site:GroundTemperature:BuildingSurface", ["5.0"] * 12)
        
        idf_str += to_idf_obj("Material", ["Concrete", "MediumRough", "0.1", "1.0", "2000", "1000", "0.9", "0.7", "0.7"])
        idf_str += to_idf_obj("Material", ["Insulation", "Smooth", "0.02", "0.04", "30", "1200", "0.9", "0.7", "0.7"])
        idf_str += to_idf_obj("Construction", ["FloorConst", "Concrete", "Insulation"])
        idf_str += to_idf_obj("Construction", ["WallConst", "Concrete", "Insulation"])
        idf_str += to_idf_obj("Construction", ["RoofConst", "Concrete", "Insulation"])
        
        idf_str += to_idf_obj("ScheduleTypeLimits", ["Temperature", "-60", "200", "Continuous"])
        idf_str += to_idf_obj("ScheduleTypeLimits", ["ControlType", "0", "4", "Discrete"])
        
        idf_str += to_idf_obj("Schedule:Compact", ["AlwaysOn", "ControlType", "Through: 12/31", "For: AllDays", "Until: 24:00", "4"])
        idf_str += to_idf_obj("Schedule:Compact", ["Living_Heat_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "20.0"])
        idf_str += to_idf_obj("Schedule:Compact", ["Master_Heat_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "18.0"])
        idf_str += to_idf_obj("Schedule:Compact", ["Kids_Heat_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "22.0"])
        idf_str += to_idf_obj("Schedule:Compact", ["Living_Cool_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "26.0"])
        idf_str += to_idf_obj("Schedule:Compact", ["Master_Cool_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "26.0"])
        idf_str += to_idf_obj("Schedule:Compact", ["Kids_Cool_Sch", "Temperature", "Through: 12/31", "For: AllDays", "Until: 24:00", "26.0"])
        
        idf_str += to_idf_obj("ThermostatSetpoint:DualSetpoint", ["LivingRoom_Therm", "Living_Heat_Sch", "Living_Cool_Sch"])
        idf_str += to_idf_obj("ThermostatSetpoint:DualSetpoint", ["MasterRoom_Therm", "Master_Heat_Sch", "Master_Cool_Sch"])
        idf_str += to_idf_obj("ThermostatSetpoint:DualSetpoint", ["KidsRoom_Therm", "Kids_Heat_Sch", "Kids_Cool_Sch"])

        idf_str += add_room_geometry("LivingRoom", 0, 0, 10, 10, 3, 3000)
        idf_str += add_room_geometry("MasterRoom", 10, 0, 5, 5, 3, 1500)
        idf_str += add_room_geometry("KidsRoom", 10, 5, 5, 5, 3, 1500)
        
        # 显式指定室外温度，且使用 timestep 频率
        idf_str += to_idf_obj("Output:Variable", ["Environment", "Site Outdoor Air Drybulb Temperature", "timestep"])
        
        idf_str += to_idf_obj("Output:Variable", ["*", "Zone Mean Air Temperature", "hourly"])
        idf_str += to_idf_obj("Output:Variable", ["*", "Zone Air Relative Humidity", "hourly"])
        idf_str += to_idf_obj("Output:Variable", ["*", "Zone Air System Sensible Heating Energy", "hourly"])
        idf_str += to_idf_obj("Output:Variable", ["*", "Zone Air System Sensible Cooling Energy", "hourly"])
        
        with open(IDF_NAME, 'w') as f: f.write(idf_str)

    def callback(state):
        while not pause_event.is_set(): time.sleep(0.1)
        
        try:
            if not handles["init"]:
                # ... 句柄获取 ...
                handles["Living_T"] = api.exchange.get_variable_handle(state, "Zone Mean Air Temperature", "LivingRoom")
                handles["Master_T"] = api.exchange.get_variable_handle(state, "Zone Mean Air Temperature", "MasterRoom")
                handles["Kids_T"]   = api.exchange.get_variable_handle(state, "Zone Mean Air Temperature", "KidsRoom")
                handles["Living_RH"] = api.exchange.get_variable_handle(state, "Zone Air Relative Humidity", "LivingRoom")
                handles["Master_RH"] = api.exchange.get_variable_handle(state, "Zone Air Relative Humidity", "MasterRoom")
                handles["Kids_RH"]   = api.exchange.get_variable_handle(state, "Zone Air Relative Humidity", "KidsRoom")
                handles["Living_Heat_J"] = api.exchange.get_variable_handle(state, "Zone Air System Sensible Heating Energy", "LivingRoom")
                handles["Living_Cool_J"] = api.exchange.get_variable_handle(state, "Zone Air System Sensible Cooling Energy", "LivingRoom")
                handles["Master_Heat_J"] = api.exchange.get_variable_handle(state, "Zone Air System Sensible Heating Energy", "MasterRoom")
                handles["Master_Cool_J"] = api.exchange.get_variable_handle(state, "Zone Air System Sensible Cooling Energy", "MasterRoom")
                handles["Kids_Heat_J"]   = api.exchange.get_variable_handle(state, "Zone Air System Sensible Heating Energy", "KidsRoom")
                handles["Kids_Cool_J"]   = api.exchange.get_variable_handle(state, "Zone Air System Sensible Cooling Energy", "KidsRoom")
                handles["Living_SP"] = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Living_Heat_Sch")
                handles["Master_SP"] = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Master_Heat_Sch")
                handles["Kids_SP"]   = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Kids_Heat_Sch")
                handles["Living_Cool_SP"] = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Living_Cool_Sch")
                handles["Master_Cool_SP"] = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Master_Cool_Sch")
                handles["Kids_Cool_SP"]   = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "Kids_Cool_Sch")

                # 搜寻室外温度句柄
                handles["Outdoor_T"] = api.exchange.get_variable_handle(state, "Site Outdoor Air Drybulb Temperature", "Environment")
                
                # 如果没找到 (-1)，尝试备用 Key
                if handles["Outdoor_T"] == -1:
                    print("❌ Error: Outdoor Temp handle is -1. Dumping available output variables...")
                    handles["Outdoor_T"] = api.exchange.get_variable_handle(state, "Site Outdoor Air Drybulb Temperature", "")
                    if handles["Outdoor_T"] != -1:
                        print("✅ Found Outdoor Temp with empty key!")
                
                handles["init"] = True
                shared_array[9] = 0.0
                return

            # Warmup Check
            if api.exchange.warmup_flag(state):
                shared_array[0] = -1.0
                if handles["Outdoor_T"] != -1:
                    val = api.exchange.get_variable_value(state, handles["Outdoor_T"])
                    shared_array[13] = val
                return

            # Read Data
            shared_array[1] = api.exchange.get_variable_value(state, handles["Living_T"])
            shared_array[2] = api.exchange.get_variable_value(state, handles["Master_T"])
            shared_array[3] = api.exchange.get_variable_value(state, handles["Kids_T"])
            shared_array[10] = api.exchange.get_variable_value(state, handles["Living_RH"])
            shared_array[11] = api.exchange.get_variable_value(state, handles["Master_RH"])
            shared_array[12] = api.exchange.get_variable_value(state, handles["Kids_RH"])
            
            # 读取室外温度
            if handles["Outdoor_T"] != -1:
                out_t = api.exchange.get_variable_value(state, handles["Outdoor_T"])
                if out_t > -99: 
                    shared_array[13] = out_t
            
            h = api.exchange.hour(state); shared_array[0] = float(h)

            # Energy Calc
            j_tot = 0
            j_tot += api.exchange.get_variable_value(state, handles["Living_Heat_J"]) + api.exchange.get_variable_value(state, handles["Living_Cool_J"])
            j_tot += api.exchange.get_variable_value(state, handles["Master_Heat_J"]) + api.exchange.get_variable_value(state, handles["Master_Cool_J"])
            j_tot += api.exchange.get_variable_value(state, handles["Kids_Heat_J"])   + api.exchange.get_variable_value(state, handles["Kids_Cool_J"])
            kwh = (j_tot / 3600000.0) / 3.0
            if kwh == 0:
                for i in range(3):
                    if shared_array[4+i] > 0 and abs(shared_array[4+i] - shared_array[1+i]) > 0.5: kwh += 0.2
            
            # ==============================================================================
            # 💰 电价计算逻辑 (TOU - Time of Use)
            # ==============================================================================
            # Valley (0.30): 23:00-07:00 (Hours: 24, 1, 2, 3, 4, 5, 6, 7)
            # Flat (0.90):   07:00-10:00, 15:00-18:00, 21:00-23:00 (Hours: 8,9,10, 16,17,18, 22,23)
            # Peak (1.50):   10:00-15:00, 18:00-21:00 (Hours: 11,12,13,14,15, 19,20,21)
            # ==============================================================================
            current_h = int(h)
            
            if current_h in [24, 1, 2, 3, 4, 5, 6, 7]:
                price = 0.30  # Valley
            elif current_h in [11, 12, 13, 14, 15, 19, 20, 21]:
                price = 1.50  # Peak (High Penalty!)
            else:
                price = 0.90  # Flat (Baseline)
                
            shared_array[7] = price
            shared_array[8] = kwh * 6.0 
            shared_array[9] += kwh * price

            # Write Control
            l = shared_array[4] if shared_array[4] > 1 else -60.0
            m = shared_array[5] if shared_array[5] > 1 else -60.0
            k = shared_array[6] if shared_array[6] > 1 else -60.0
            api.exchange.set_actuator_value(state, handles["Living_SP"], l)
            api.exchange.set_actuator_value(state, handles["Master_SP"], m)
            api.exchange.set_actuator_value(state, handles["Kids_SP"],   k)
            api.exchange.set_actuator_value(state, handles["Living_Cool_SP"], l + 4.0 if l > 0 else 100.0)
            api.exchange.set_actuator_value(state, handles["Master_Cool_SP"], m + 4.0 if m > 0 else 100.0)
            api.exchange.set_actuator_value(state, handles["Kids_Cool_SP"],   k + 4.0 if k > 0 else 100.0)

            time.sleep(0.8)
        except: pass

    generate_robust_idf()
    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state, callback)
    api.runtime.run_energyplus(state, ['-w', WEATHER_FILE, '-d', 'out_sim', IDF_NAME])

# ... (PMVCalculator, CounterfactualSimulator, SimulationProxy 保持不变) ...
class PMVCalculator:
    @staticmethod
    def calc_pmv(ta, tr, vel, rh, met, clo):
        if ta < -20 or ta > 50: return 0.0
        try:
            pa = rh * 10 * math.exp(16.6536 - 4030.183 / (ta + 235))
            icl = 0.155 * clo
            m = met * 58.15; mw = m 
            fcl = 1.0 + 0.2 * icl if icl < 0.078 else 1.05 + 0.645 * icl
            hcf = 12.1 * math.sqrt(vel)
            tcl = 35.7 - 0.028 * mw
            for _ in range(10):
                hc = max(hcf, 2.38 * abs(tcl - ta)**0.25)
                tcl = 35.7 - 0.028 * mw - icl * (3.96 * 10**-8 * fcl * ((tcl + 273)**4 - (tr + 273)**4) + fcl * hc * (tcl - ta))
            ts = 0.303 * math.exp(-0.036 * m) + 0.028
            pmv = ts * (mw - 3.05 * 0.001 * (5733 - 6.99 * mw - pa) - 0.42 * (mw - 58.15)
                        - 1.7 * 10**-5 * m * (5867 - pa) - 0.0014 * m * (34 - ta)
                        - 3.96 * 10**-8 * fcl * ((tcl + 273)**4 - (tr + 273)**4) - fcl * hc * (tcl - ta))
            return max(-3.0, min(3.0, pmv))
        except: return 0.0

class CounterfactualSimulator:
    @staticmethod
    def simulate_what_if(action_data, current_context):
        real_temp = action_data['temp']
        out_temp = action_data['out_temp']
        cost = action_data['cost']
        hypothetical_temp = real_temp + (out_temp - real_temp) * 0.2
        hypo_pmv = PMVCalculator.calc_pmv(hypothetical_temp, hypothetical_temp, 0.1, 50, 1.2, 1.2)
        return {"hypothetical_temp": hypothetical_temp, "hypothetical_pmv": hypo_pmv, "saved_money": cost}

cf_engine = CounterfactualSimulator()

class SimulationProxy:
    def __init__(self):
        self.shared_array = None; self.p = None; self.lock = threading.Lock() 
        self.pause_event = None
    @property
    def current_hour(self): return int(self.shared_array[0]) if self.shared_array else 0
    @property
    def zone_data(self):
        if not self.shared_array: return {"LivingRoom":(20,50), "MasterRoom":(20,50), "KidsRoom":(20,50)}
        return {
            "LivingRoom": (self.shared_array[1], self.shared_array[10]),
            "MasterRoom": (self.shared_array[2], self.shared_array[11]),
            "KidsRoom":   (self.shared_array[3], self.shared_array[12])
        }
    @property
    def energy_data(self):
        if not self.shared_array: return (0.1, 0.0, 0.0, 0.0)
        return (self.shared_array[7], self.shared_array[8], self.shared_array[9], self.shared_array[13])
    
    def get_setpoint(self, room):
        if not self.shared_array: return 22.0
        idx_map = {"LivingRoom": 4, "MasterRoom": 5, "KidsRoom": 6}
        return self.shared_array[idx_map.get(room, 4)]
    
    def set_setpoint(self, room, val):
        if not self.shared_array: return
        idx_map = {"LivingRoom": 4, "MasterRoom": 5, "KidsRoom": 6}
        if room in idx_map: self.shared_array[idx_map[room]] = float(val)

    def pause_time(self):
        if self.pause_event: self.pause_event.clear()
    
    def resume_time(self):
        if self.pause_event: self.pause_event.set()

    def start(self):
        self.shared_array = multiprocessing.Array('d', SHARED_ARRAY_SIZE)
        self.pause_event = multiprocessing.Event()
        self.pause_event.set()
        for i in range(SHARED_ARRAY_SIZE): self.shared_array[i] = 0.0
        self.shared_array[1]=20.0; self.shared_array[2]=20.0; self.shared_array[3]=20.0
        self.shared_array[4]=22.0; self.shared_array[5]=20.0; self.shared_array[6]=24.0
        self.shared_array[7]=0.1
        self.shared_array[10]=50.0; self.shared_array[11]=50.0; self.shared_array[12]=50.0
        self.shared_array[13] = -4.0
        self.p = multiprocessing.Process(target=run_energyplus_process, args=(self.shared_array, self.pause_event))
        self.p.daemon = True; self.p.start()

    def restart(self):
        if self.p and self.p.is_alive():
            print("🔄 Killing old EnergyPlus process...")
            self.p.terminate(); self.p.join()
        print("🔄 Restarting EnergyPlus...")
        self.start()

sim_manager = SimulationProxy()