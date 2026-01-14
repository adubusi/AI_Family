import os

# ================= ⚖️ 决策平衡超参数 (最优先) =================
# 控制 AI 在 "舒适度" 和 "省钱" 之间的权衡
# 范围: 0.0 (吝啬鬼) ~ 1.0 (享乐主义)
COMFORT_VS_COST_WEIGHT = 1 

# ================= 💰 经济系统 =================
# 家庭每日电费预算 (超过这个值，全家都会觉得"穷"并感到恐慌)
DAILY_BUDGET_LIMIT = 20.0 

# ================= 🔧 基础配置 =================
API_KEY = "xxx" 
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

EPLUS_DIR = r"C:\EnergyPlusV23-1-0" #找到你安装的Energyplus版本
WEATHER_FILE = "CHN_Beijing.Beijing.545110_CSWD.epw" # 对应的天气文件
IDF_NAME = "Merged_House.idf"

# --- 尺寸配置 ---
MAP_WIDTH = 1024
MAP_HEIGHT = 768
UI_BAR_WIDTH = 320
WINDOW_WIDTH = MAP_WIDTH + UI_BAR_WIDTH
WINDOW_HEIGHT = MAP_HEIGHT

# 运行参数
FPS = 30
GRID_SIZE = 32
SPRITE_SCALE = 3
ANIMATION_SPEED = 0.1
MOVE_SPEED = 3.0

# 颜色
WHITE = (255, 255, 255); BLACK = (0, 0, 0); GRAY = (200, 200, 200)
FLOOR_COLOR = (240, 230, 210); WALL_COLOR = (40, 40, 50)
BUBBLE_BG = (255, 255, 240); SELECTION_COLOR = (255, 215, 0)
RED = (220, 50, 50); GREEN = (50, 180, 50); BLUE = (50, 100, 255)
UI_BG_COLOR = (30, 30, 40) 

DIR_DOWN, DIR_LEFT, DIR_RIGHT, DIR_UP = 0, 1, 2, 3

# ==================================================================================
# 🌡️ 共享内存索引定义
# 0: Hour, 1-3: Temp, 4-6: Setpoint, 7: Price, 8: Power, 9: Bill, 10-12: Humidity
# 13: Outdoor Temp
# ==================================================================================
SHARED_ARRAY_SIZE = 17 

# 全局游戏状态 (用于地图显示食物)
GLOBAL_GAME_STATE = {
    "food_servings": 0
}

# 记忆存储文件
MEMORY_FILE = "agent_evolution.json"
CSV_LOG_FILE = "pareto_data.csv"