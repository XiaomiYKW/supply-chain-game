import random

def calculate_monthly_results(current_state, config, prev_states=None):
    if current_state.actual_demand is None or current_state.actual_demand == 0:
        variation = random.uniform(0.8, 1.2)
        current_state.actual_demand = round(current_state.forecast_demand * variation)

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

    current_state.total_cost = purchase_cost + holding_cost + overflow_cost
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
