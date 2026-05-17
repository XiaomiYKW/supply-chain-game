import models
import database
import game_logic
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from collections import defaultdict
import uuid

models.Base.metadata.create_all(bind=database.engine)

def ensure_schema():
    desired_game_config = {
        "raw_warehouse_capacity": ("FLOAT", "2000"),
        "fg_warehouse_capacity": ("FLOAT", "1500"),
        "raw_overflow_cost": ("FLOAT", "10"),
        "fg_overflow_cost": ("FLOAT", "20"),
        "demand_variation_low": ("FLOAT", "0.7"),
        "demand_variation_high": ("FLOAT", "1.3"),
        "fixed_cost_per_month": ("FLOAT", "3000"),
        "stockout_penalty_per_unit": ("FLOAT", "10"),
        "negative_cash_interest_rate": ("FLOAT", "0.02"),
    }
    desired_game_state = {
        "purchase_cost": ("FLOAT", "0"),
        "holding_cost": ("FLOAT", "0"),
        "overflow_cost": ("FLOAT", "0"),
        "fixed_cost": ("FLOAT", "0"),
        "stockout_cost": ("FLOAT", "0"),
        "interest_cost": ("FLOAT", "0"),
    }

    engine = database.engine
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(game_config)")).fetchall()
            existing = {r[1] for r in rows}
            for col, (col_type, default_value) in desired_game_config.items():
                if col in existing:
                    continue
                conn.execute(text(f"ALTER TABLE game_config ADD COLUMN {col} {col_type} DEFAULT {default_value}"))

            user_rows = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            user_existing = {r[1] for r in user_rows}
            if "auth_token" not in user_existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN auth_token TEXT"))

            state_rows = conn.execute(text("PRAGMA table_info(game_state)")).fetchall()
            state_existing = {r[1] for r in state_rows}
            for col, (col_type, default_value) in desired_game_state.items():
                if col in state_existing:
                    continue
                conn.execute(text(f"ALTER TABLE game_state ADD COLUMN {col} {col_type} DEFAULT {default_value}"))
        else:
            for col, (col_type, default_value) in desired_game_config.items():
                conn.execute(text(f"ALTER TABLE game_config ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default_value}"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_token VARCHAR(64)"))
            for col, (col_type, default_value) in desired_game_state.items():
                conn.execute(text(f"ALTER TABLE game_state ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default_value}"))

ensure_schema()

app = FastAPI(title="Supply Chain Game API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def issue_token(user: models.User, db: Session) -> str:
    token = uuid.uuid4().hex
    user.auth_token = token
    db.commit()
    return token

def get_current_user(
    db: Session = Depends(get_db),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> models.User:
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Missing auth token")
    user = db.query(models.User).filter(models.User.auth_token == x_auth_token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    return user

def get_current_teacher(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher access required")
    return user

def compute_cost_breakdown(state: models.GameState, config: models.GameConfig):
    purchase_supplier_1 = state.purchase_supplier_1 or 0
    purchase_supplier_2 = state.purchase_supplier_2 or 0

    available_raw = (state.raw_material_stock or 0) + purchase_supplier_2
    actual_production = min(
        state.production_quantity or 0,
        available_raw,
        config.factory_capacity
    )
    available_fg = (state.finished_goods_stock or 0) + actual_production
    actual_sales = state.actual_sales if state.actual_sales is not None else min(available_fg, state.actual_demand or 0)

    end_raw = available_raw - actual_production
    end_fg = available_fg - actual_sales

    purchase_cost = purchase_supplier_1 * (config.supplier1_price or 0) + purchase_supplier_2 * (config.supplier2_price or 0)
    holding_cost = end_raw * (config.raw_holding_cost or 0) + end_fg * (config.fg_holding_cost or 0)

    overflow_raw_units = max(0, end_raw - (config.raw_warehouse_capacity or 0)) if config.raw_warehouse_capacity is not None else 0
    overflow_fg_units = max(0, end_fg - (config.fg_warehouse_capacity or 0)) if config.fg_warehouse_capacity is not None else 0
    overflow_cost = overflow_raw_units * (config.raw_overflow_cost or 0) + overflow_fg_units * (config.fg_overflow_cost or 0)

    fixed_cost = float(config.fixed_cost_per_month or 0)
    stockout_units = max(0, (state.actual_demand or 0) - (actual_sales or 0))
    stockout_cost = float(stockout_units * (config.stockout_penalty_per_unit or 0))
    interest_cost = float(max(0, -(state.cash or 0)) * (config.negative_cash_interest_rate or 0))

    return {
        "purchase_cost": float(purchase_cost),
        "holding_cost": float(holding_cost),
        "overflow_cost": float(overflow_cost),
        "fixed_cost": fixed_cost,
        "stockout_cost": stockout_cost,
        "interest_cost": interest_cost,
    }

class DecisionSubmit(BaseModel):
    user_id: int
    forecast_demand: float
    purchase_supplier_1: float
    purchase_supplier_2: float
    production_quantity: float

class UserCreate(BaseModel):
    username: str
    password: str
    role: str

class LoginRequest(BaseModel):
    username: str
    password: str

@app.get("/")
async def root():
    return {"message": "Welcome to the Supply Chain Game API"}

@app.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.username == request.username,
        models.User.password_hash == request.password
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_token(user, db)
    return {"id": user.id, "username": user.username, "role": user.role, "token": token}

@app.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}

@app.post("/users/")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    db_user = models.User(username=user.username, password_hash=user.password, role=user.role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    token = issue_token(db_user, db)

    config = db.query(models.GameConfig).first()
    if not config:
        config = models.GameConfig(
            selling_price=100, supplier1_price=40, supplier1_lead_time=1,
            supplier2_price=60, supplier2_lead_time=0, factory_capacity=1000,
            raw_holding_cost=2, fg_holding_cost=5,
            raw_warehouse_capacity=2000, fg_warehouse_capacity=1500,
            raw_overflow_cost=10, fg_overflow_cost=20,
            demand_variation_low=0.7, demand_variation_high=1.3,
            fixed_cost_per_month=3000, stockout_penalty_per_unit=10,
            negative_cash_interest_rate=0.02,
            initial_cash=100000, initial_raw_stock=500, initial_fg_stock=200
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    first_state = models.GameState(
        user_id=db_user.id, month=1,
        cash=config.initial_cash, raw_material_stock=config.initial_raw_stock,
        finished_goods_stock=config.initial_fg_stock,
        is_submitted=False, is_settled=False
    )
    db.add(first_state)
    db.commit()
    return {"id": db_user.id, "username": db_user.username, "role": db_user.role, "token": token}

@app.get("/game_state/{user_id}")
def get_game_state(user_id: int, db: Session = Depends(get_db)):
    state = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == False
    ).order_by(models.GameState.month.asc()).first()

    if not state:
        raise HTTPException(status_code=404, detail="No active game state found")
    return state

@app.get("/history/{user_id}")
def get_history(user_id: int, db: Session = Depends(get_db)):
    config = db.query(models.GameConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="game_config not initialized")
    states = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == True
    ).order_by(models.GameState.month.asc()).all()

    result = []
    cumulative_profit = 0.0
    for s in states:
        breakdown = compute_cost_breakdown(s, config) if (
            s.purchase_cost is None or s.holding_cost is None or s.overflow_cost is None
            or s.fixed_cost is None or s.stockout_cost is None or s.interest_cost is None
        ) else None
        profit_value = float(s.profit or 0)
        cumulative_profit += profit_value
        result.append({
            "month": s.month,
            "profit": s.profit,
            "cumulative_profit": cumulative_profit,
            "revenue": s.revenue,
            "total_cost": s.total_cost,
            "purchase_cost": s.purchase_cost if s.purchase_cost is not None else (breakdown["purchase_cost"] if breakdown else 0.0),
            "holding_cost": s.holding_cost if s.holding_cost is not None else (breakdown["holding_cost"] if breakdown else 0.0),
            "overflow_cost": s.overflow_cost if s.overflow_cost is not None else (breakdown["overflow_cost"] if breakdown else 0.0),
            "fixed_cost": s.fixed_cost if s.fixed_cost is not None else (breakdown["fixed_cost"] if breakdown else 0.0),
            "stockout_cost": s.stockout_cost if s.stockout_cost is not None else (breakdown["stockout_cost"] if breakdown else 0.0),
            "interest_cost": s.interest_cost if s.interest_cost is not None else (breakdown["interest_cost"] if breakdown else 0.0),
            "actual_demand": s.actual_demand,
            "actual_sales": s.actual_sales,
            "cash": s.cash,
            "raw_material_stock": s.raw_material_stock,
            "finished_goods_stock": s.finished_goods_stock
        })
    return result

@app.get("/report/{user_id}")
def get_report(user_id: int, db: Session = Depends(get_db)):
    config = db.query(models.GameConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="game_config not initialized")
    report = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == True
    ).order_by(models.GameState.month.desc()).first()

    if not report:
        raise HTTPException(status_code=404, detail="No settled report found")
    cumulative_profit = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == True
    ).with_entities(models.GameState.profit).all()
    cumulative_profit_value = float(sum((p[0] or 0) for p in cumulative_profit))
    breakdown = compute_cost_breakdown(report, config)
    return {
        "month": report.month,
        "profit": report.profit,
        "cumulative_profit": cumulative_profit_value,
        "revenue": report.revenue,
        "total_cost": report.total_cost,
        "purchase_cost": report.purchase_cost if report.purchase_cost is not None else breakdown["purchase_cost"],
        "holding_cost": report.holding_cost if report.holding_cost is not None else breakdown["holding_cost"],
        "overflow_cost": report.overflow_cost if report.overflow_cost is not None else breakdown["overflow_cost"],
        "fixed_cost": report.fixed_cost if report.fixed_cost is not None else breakdown["fixed_cost"],
        "stockout_cost": report.stockout_cost if report.stockout_cost is not None else breakdown["stockout_cost"],
        "interest_cost": report.interest_cost if report.interest_cost is not None else breakdown["interest_cost"],
        "actual_demand": report.actual_demand,
        "actual_sales": report.actual_sales,
        "cash": report.cash,
        "raw_material_stock": report.raw_material_stock,
        "finished_goods_stock": report.finished_goods_stock,
    }

@app.post("/submit_decision")
def submit_decision(decision: DecisionSubmit, db: Session = Depends(get_db)):
    state = db.query(models.GameState).filter(
        models.GameState.user_id == decision.user_id,
        models.GameState.is_submitted == False,
        models.GameState.is_settled == False
    ).first()

    if not state:
        raise HTTPException(status_code=400, detail="No active month found or decision already submitted")

    if decision.forecast_demand < 0:
        raise HTTPException(status_code=400, detail="forecast_demand must be >= 0")
    if decision.purchase_supplier_1 < 0 or decision.purchase_supplier_2 < 0:
        raise HTTPException(status_code=400, detail="purchase quantity must be >= 0")
    if decision.production_quantity < 0:
        raise HTTPException(status_code=400, detail="production_quantity must be >= 0")

    config = db.query(models.GameConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="game_config not initialized")

    cash = state.cash or 0
    requested_p1 = decision.purchase_supplier_1
    requested_p2 = decision.purchase_supplier_2

    if cash <= 0 and (requested_p1 > 0 or requested_p2 > 0):
        raise HTTPException(status_code=400, detail="Insufficient cash to purchase")

    accepted_p2 = requested_p2
    accepted_p1 = requested_p1

    if config.supplier2_price and config.supplier2_price > 0:
        accepted_p2 = min(requested_p2, cash / config.supplier2_price)
    cost_p2 = accepted_p2 * (config.supplier2_price or 0)
    remaining_cash = cash - cost_p2

    if remaining_cash < 0:
        remaining_cash = 0

    if config.supplier1_price and config.supplier1_price > 0:
        accepted_p1 = min(requested_p1, remaining_cash / config.supplier1_price)

    adjusted = (accepted_p1 != requested_p1) or (accepted_p2 != requested_p2)

    state.forecast_demand = decision.forecast_demand
    state.purchase_supplier_1 = accepted_p1
    state.purchase_supplier_2 = accepted_p2
    state.production_quantity = min(decision.production_quantity, config.factory_capacity or decision.production_quantity)
    state.is_submitted = True

    db.commit()
    return {
        "message": "Decision submitted successfully",
        "month": state.month,
        "adjusted": adjusted,
        "requested": {
            "purchase_supplier_1": requested_p1,
            "purchase_supplier_2": requested_p2,
        },
        "accepted": {
            "purchase_supplier_1": accepted_p1,
            "purchase_supplier_2": accepted_p2,
        },
    }

@app.post("/settle_month/{user_id}")
def settle_month(user_id: int, db: Session = Depends(get_db)):
    state = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_submitted == True,
        models.GameState.is_settled == False
    ).first()

    if not state:
        raise HTTPException(status_code=400, detail="No submitted decision found for this month")

    config = db.query(models.GameConfig).first()

    # 2. Calculate results
    game_logic.calculate_monthly_results(state, config)
    
    # 3. Create next month state
    # Get pending purchases from supplier 1 (from previous month)
    pending_from_supplier1 = 0
    if state.month > 1:
        prev_state = db.query(models.GameState).filter(
            models.GameState.user_id == user_id,
            models.GameState.month == state.month - 1
        ).first()
        if prev_state:
            pending_from_supplier1 = prev_state.purchase_supplier_1 or 0
    
    next_state_data = game_logic.get_next_month_initial(
        state, config,
        supplier1_pending=pending_from_supplier1,
        supplier1_current=state.purchase_supplier_1 or 0,
        supplier2_current=state.purchase_supplier_2 or 0
    )

    next_state = models.GameState(**next_state_data)
    db.add(next_state)
    db.commit()

    return {
        "message": f"Month {state.month} settled successfully",
        "month": state.month,
        "profit": state.profit,
        "actual_demand": state.actual_demand,
        "actual_sales": state.actual_sales
    }

@app.get("/teacher/ranking")
def get_ranking(teacher: models.User = Depends(get_current_teacher), db: Session = Depends(get_db)):
    users = db.query(models.User).filter(models.User.role == "student").all()

    ranking = []
    for user in users:
        settled_states = db.query(models.GameState).filter(
            models.GameState.user_id == user.id,
            models.GameState.is_settled == True
        ).all()
        
        total_profit = sum(s.profit or 0 for s in settled_states)
        months_played = len(settled_states)

        ranking.append({
            "user_id": user.id,
            "username": user.username,
            "total_profit": float(total_profit),
            "months_played": months_played
        })

    ranking.sort(key=lambda x: x["total_profit"], reverse=True)

    for i, r in enumerate(ranking):
        r["rank"] = i + 1

    return ranking

@app.get("/teacher/students")
def get_students(teacher: models.User = Depends(get_current_teacher), db: Session = Depends(get_db)):
    users = db.query(models.User).filter(models.User.role == "student").all()
    return [{"id": u.id, "username": u.username} for u in users]

@app.get("/teacher/student/{user_id}/history")
def get_student_history(user_id: int, teacher: models.User = Depends(get_current_teacher), db: Session = Depends(get_db)):
    states = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == True
    ).order_by(models.GameState.month.asc()).all()

    return [{
        "month": s.month,
        "profit": s.profit,
        "revenue": s.revenue,
        "total_cost": s.total_cost,
        "actual_demand": s.actual_demand,
        "actual_sales": s.actual_sales,
        "cash": s.cash,
        "raw_material_stock": s.raw_material_stock,
        "finished_goods_stock": s.finished_goods_stock,
        "forecast_demand": s.forecast_demand,
        "purchase_supplier_1": s.purchase_supplier_1,
        "purchase_supplier_2": s.purchase_supplier_2,
        "production_quantity": s.production_quantity
    } for s in states]

import os

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8005))
    uvicorn.run(app, host="0.0.0.0", port=port)
