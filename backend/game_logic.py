import random

def calculate_monthly_results(current_state, config, prev_states=None):
    if current_state.actual_demand is None or current_state.actual_demand == 0:
        variation = random.uniform(0.8, 1.2)
        current_state.actual_demand = round(current_state.forecast_demand * variation)

    actual_production = min(
        current_state.production_quantity,
        current_state.raw_material_stock,
        config.factory_capacity
    )

    available_fg = current_state.finished_goods_stock + actual_production
    current_state.actual_sales = min(available_fg, current_state.actual_demand)

    current_state.revenue = current_state.actual_sales * config.selling_price

    purchase_cost = (current_state.purchase_supplier_1 * config.supplier1_price +
                     current_state.purchase_supplier_2 * config.supplier2_price)

    holding_cost = (current_state.raw_material_stock * config.raw_holding_cost +
                    current_state.finished_goods_stock * config.fg_holding_cost)

    current_state.total_cost = purchase_cost + holding_cost
    current_state.profit = current_state.revenue - current_state.total_cost

    current_state.is_settled = True

    return current_state

def get_next_month_initial(current_state, config, supplier1_pending=0, supplier1_current=0, supplier2_current=0):
    actual_production = min(
        current_state.production_quantity,
        current_state.raw_material_stock,
        config.factory_capacity
    )

    next_cash = current_state.cash + current_state.profit

    next_raw = (
        current_state.raw_material_stock
        - actual_production
        + supplier2_current
        + supplier1_pending
    )

    next_fg = (
        current_state.finished_goods_stock
        + actual_production
        - current_state.actual_sales
    )

    return {
        "user_id": current_state.user_id,
        "month": current_state.month + 1,
        "cash": max(0, next_cash),
        "raw_material_stock": max(0, next_raw),
        "finished_goods_stock": max(0, next_fg),
        "is_submitted": False,
        "is_settled": False
    }
