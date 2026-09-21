import random

def calculate_monthly_results(current_state, config, prev_states=None):
    """
    实际需求 actual_demand 生成策略（幂等：已生成则直接跳过）：
    1. 上层 main.py 已按班级统一的 「DemandPlan base × seeded_variation（同班同月一致）」
       注入到 state._demand_base_for_calc / state._demand_variation_for_calc，
       确保同月全班 actual_demand 100%一字不差。
    2. 兜底：若上层未注入（例如异常情况），则按 base=400 × 本地随机波动 兜底，避免 0 值产生。
    """
    if current_state.actual_demand is None or current_state.actual_demand == 0:
        low = config.demand_variation_low if getattr(config, "demand_variation_low", None) is not None else 0.8
        high = config.demand_variation_high if getattr(config, "demand_variation_high", None) is not None else 1.2
        if low <= 0:
            low = 0.8
        if high <= 0:
            high = 1.2
        if low > high:
            low, high = high, low

        injected_base = getattr(current_state, "_demand_base_for_calc", None)
        injected_variation = getattr(current_state, "_demand_variation_for_calc", None)

        if injected_base is not None and injected_variation is not None:
            # ---- 教师预设模式（excel_import / curve_preset）：同月全班 actual_demand 一字不差 ----
            base_val = float(injected_base)
            var_val = float(injected_variation)
            current_state.actual_demand = round(base_val * var_val)
        else:
            # ---- 兜底：400平稳 × 本地随机波动（仅用于异常情况，保证全班月基准相近） ----
            variation = random.uniform(low, high)
            current_state.actual_demand = round(400.0 * variation)

    purchase_supplier_1 = current_state.purchase_supplier_1 or 0
    purchase_supplier_2 = current_state.purchase_supplier_2 or 0

    available_raw = (current_state.raw_material_stock or 0) + purchase_supplier_2
    actual_production = min(
        current_state.production_quantity or 0,
        available_raw,
        config.factory_capacity
    )

    available_fg = (current_state.finished_goods_stock or 0) + actual_production
    current_state.actual_sales = min(available_fg, current_state.actual_demand)

    current_state.revenue = current_state.actual_sales * config.selling_price

    purchase_cost = (purchase_supplier_1 * config.supplier1_price +
                     purchase_supplier_2 * config.supplier2_price)

    end_raw = available_raw - actual_production
    end_fg = available_fg - current_state.actual_sales

    holding_cost = (end_raw * config.raw_holding_cost +
                    end_fg * config.fg_holding_cost)

    overflow_raw_units = 0
    overflow_fg_units = 0
    if config.raw_warehouse_capacity is not None:
        overflow_raw_units = max(0, end_raw - config.raw_warehouse_capacity)
    if config.fg_warehouse_capacity is not None:
        overflow_fg_units = max(0, end_fg - config.fg_warehouse_capacity)

    overflow_cost = 0
    if config.raw_overflow_cost is not None:
        overflow_cost += overflow_raw_units * config.raw_overflow_cost
    if config.fg_overflow_cost is not None:
        overflow_cost += overflow_fg_units * config.fg_overflow_cost

    fixed_cost = getattr(config, "fixed_cost_per_month", 0) or 0
    stockout_units = max(0, (current_state.actual_demand or 0) - (current_state.actual_sales or 0))
    stockout_penalty = getattr(config, "stockout_penalty_per_unit", 0) or 0
    stockout_cost = stockout_units * stockout_penalty

    interest_rate = getattr(config, "negative_cash_interest_rate", 0) or 0
    interest_cost = max(0, -(current_state.cash or 0)) * interest_rate

    current_state.purchase_cost = purchase_cost
    current_state.holding_cost = holding_cost
    current_state.overflow_cost = overflow_cost
    current_state.fixed_cost = fixed_cost
    current_state.stockout_cost = stockout_cost
    current_state.interest_cost = interest_cost
    current_state.total_cost = purchase_cost + holding_cost + overflow_cost + fixed_cost + stockout_cost + interest_cost
    current_state.profit = current_state.revenue - current_state.total_cost

    current_state.is_settled = True

    return current_state

def get_next_month_initial(current_state, config, supplier1_pending=0, supplier1_current=0, supplier2_current=0):
    next_cash = current_state.cash + current_state.profit

    available_raw = (current_state.raw_material_stock or 0) + (supplier2_current or 0)
    actual_production = min(
        current_state.production_quantity or 0,
        available_raw,
        config.factory_capacity
    )
    end_raw = available_raw - actual_production

    next_raw = end_raw + (supplier1_pending or 0)

    next_fg = ((current_state.finished_goods_stock or 0)
               + actual_production
               - (current_state.actual_sales or 0))

    return {
        "user_id": current_state.user_id,
        "month": current_state.month + 1,
        "cash": next_cash,
        "raw_material_stock": max(0, next_raw),
        "finished_goods_stock": max(0, next_fg),
        "is_submitted": False,
        "is_settled": False
    }
