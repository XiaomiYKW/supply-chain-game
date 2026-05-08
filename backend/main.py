import models
import database
import game_logic
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from collections import defaultdict

models.Base.metadata.create_all(bind=database.engine)

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

    config = db.query(models.GameConfig).first()
    if not config:
        config = models.GameConfig(
            selling_price=100, supplier1_price=40, supplier1_lead_time=1,
            supplier2_price=60, supplier2_lead_time=0, factory_capacity=1000,
            raw_holding_cost=2, fg_holding_cost=5,
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
    return {"id": db_user.id, "username": db_user.username, "role": db_user.role}

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
        "finished_goods_stock": s.finished_goods_stock
    } for s in states]

@app.get("/report/{user_id}")
def get_report(user_id: int, db: Session = Depends(get_db)):
    report = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == True
    ).order_by(models.GameState.month.desc()).first()

    if not report:
        raise HTTPException(status_code=404, detail="No settled report found")
    return report

@app.post("/submit_decision")
def submit_decision(decision: DecisionSubmit, db: Session = Depends(get_db)):
    state = db.query(models.GameState).filter(
        models.GameState.user_id == decision.user_id,
        models.GameState.is_submitted == False,
        models.GameState.is_settled == False
    ).first()

    if not state:
        raise HTTPException(status_code=400, detail="No active month found or decision already submitted")

    state.forecast_demand = decision.forecast_demand
    state.purchase_supplier_1 = decision.purchase_supplier_1
    state.purchase_supplier_2 = decision.purchase_supplier_2
    state.production_quantity = decision.production_quantity
    state.is_submitted = True

    db.commit()
    return {"message": "Decision submitted successfully", "month": state.month}

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
def get_ranking(db: Session = Depends(get_db)):
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
def get_students(db: Session = Depends(get_db)):
    users = db.query(models.User).filter(models.User.role == "student").all()
    return [{"id": u.id, "username": u.username} for u in users]

@app.get("/teacher/student/{user_id}/history")
def get_student_history(user_id: int, db: Session = Depends(get_db)):
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
