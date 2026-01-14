import math

def calculate_fanger_pmv(ta, tr, vel, rh, met, clo):
    """
    计算 Fanger PMV 指数 (标准 ISO 7730 算法修正版)
    
    :param ta:  空气温度 (Air Temperature, °C)
    :param tr:  平均辐射温度 (Mean Radiant Temperature, °C)
    :param vel: 空气流速 (Air Velocity, m/s)
    :param rh:  相对湿度 (Relative Humidity, %) - 输入范围 0-100
    :param met: 代谢率 (Metabolic Rate, met) - 1 met = 58.15 W/m2
    :param clo: 服装热阻 (Clothing Insulation, clo)
    :return:    PMV 值 (-3.0 到 +3.0)
    """
    # 1. 安全检查，防止极端数据导致崩溃
    if ta < -50 or ta > 100: return 0.0
    if rh < 0: rh = 0
    if rh > 100: rh = 100
    
    # 2. 基础变量转换
    pa = rh * 10 * math.exp(16.6536 - 4030.183 / (ta + 235)) # 水蒸气分压 (Pa)
    icl = 0.155 * clo                                      # 服装热阻 (m2·K/W)
    m = met * 58.15                                        # 代谢产热 (W/m2)
    w = 0                                                  # 对外做功 (通常为0)
    mw = m - w                                             # 人体内部产热
    
    # 3. 服装表面积系数 (fcl)
    if icl <= 0.078:
        fcl = 1.0 + 1.29 * icl
    else:
        fcl = 1.05 + 0.645 * icl

    # 4. 迭代计算服装表面温度 (t_cl)
    # 使用开尔文温度进行辐射计算
    taa = ta + 273
    tra = tr + 273
    t_cl = taa + (35.5 - ta) / (3.5 * icl + 0.1) # 初始猜测值

    eps = 0.00015
    n = 0
    h_c = 12.1 * math.sqrt(vel) # 初始对流系数

    while n < 150:
        t_cl_old = t_cl
        
        # 计算两种对流换热系数：强制对流 vs 自然对流，取大者
        h_cf = 12.1 * math.sqrt(vel)
        h_cn = 2.38 * abs(t_cl - taa) ** 0.25
        h_c = max(h_cf, h_cn)
        
        # 能量平衡方程求解新 t_cl
        # T_cl = T_sk - I_cl * (Radiation + Convection)
        # 这里使用迭代形式
        t_surf_k4 = (t_cl) ** 4      # T_cl^4
        mrt_k4 = (tra) ** 4          # MRT^4
        
        term1 = 3.96 * 10**(-8) * fcl * (t_surf_k4 - mrt_k4) # 辐射项
        term2 = fcl * h_c * (t_cl - taa)                     # 对流项
        
        # 35.7 - 0.028*MW 是皮肤温度估算公式
        t_new = (35.7 - 0.028 * mw) - icl * (term1 + term2)
        
        # 使用混合更新防止震荡
        t_cl = (t_cl_old + t_new) / 2 + 273 # 注意公式输出的是摄氏度，这里为了下一轮循环由于我们都用K，所以...
        # 修正：上面公式太乱，直接用最原始的 ISO 7730 迭代公式会更稳：
        
        p1 = 3.96 * 10**(-8) * fcl
        p2 = p1 * (tra**4)
        p3 = 100 + 4 * eps # 虚拟项
        # 重新标准化计算：
        break # 跳出这个不稳定的 Python 写法，直接用下面的终极修正版
    
    # === 重新实现最简化的不动点迭代 (Robust Version) ===
    t_cl = ta + (35.5 - ta) / (3.5 * (0.155 * clo) + 0.1) # 重置猜测 (摄氏度)
    for _ in range(100):
        t_cl_abs = t_cl + 273
        
        h_cf = 12.1 * math.sqrt(vel)
        h_cn = 2.38 * abs(t_cl - ta)**0.25
        h_c = max(h_cf, h_cn)
        
        rad_loss = 3.96 * 10**(-8) * fcl * (t_cl_abs**4 - tra**4)
        conv_loss = fcl * h_c * (t_cl - ta)
        
        # 能量平衡推导出的新 Tcl
        t_skin = 35.7 - 0.028 * mw
        loss_total = icl * (rad_loss + conv_loss)
        t_cl_new = t_skin - loss_total
        
        if abs(t_cl_new - t_cl) < 0.001:
            t_cl = t_cl_new
            break
        t_cl = (t_cl + t_cl_new) / 2 # 阻尼迭代
    
    # 5. 计算热负荷 (Heat Load)
    t_cl_abs = t_cl + 273
    rad_loss = 3.96 * 10**(-8) * fcl * (t_cl_abs**4 - tra**4)
    conv_loss = fcl * h_c * (t_cl - ta)
    
    # 各部分散热项
    hl1 = 3.05 * 0.001 * (5733 - 6.99 * mw - pa)    # 皮肤扩散散热
    hl2 = 0.42 * (mw - 58.15)                       # 出汗散热
    hl3 = 1.7 * 10**(-5) * m * (5867 - pa)          # 呼吸潜热
    hl4 = 0.0014 * m * (34 - ta)                    # 呼吸显热
    hl5 = rad_loss                                  # 辐射散热
    hl6 = conv_loss                                 # 对流散热
    
    # 总热负荷误差
    load_err = mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6
    
    # 6. 计算 PMV
    ts_coeff = 0.303 * math.exp(-0.036 * m) + 0.028
    pmv = ts_coeff * load_err
    
    # 强力钳制 (Fanger模型只在 -3 到 +3 有效)
    return max(-3.0, min(3.0, pmv))

def pmv_to_comfort_score(pmv):
    """
    将 PMV (-3 到 +3) 转换为 0-1 的舒适度分数
    """
    return max(0.0, 1.0 - (abs(pmv) / 3.0))

def get_sensation_string(pmv):
    if pmv >= 2.5: return "Hot"
    elif pmv >= 1.5: return "Warm"
    elif pmv >= 0.5: return "Slightly Warm"
    elif pmv >= -0.5: return "Neutral"
    elif pmv >= -1.5: return "Slightly Cool"
    elif pmv >= -2.5: return "Cool"
    else: return "Cold"