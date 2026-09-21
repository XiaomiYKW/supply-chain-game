import models
import database
import game_logic
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from collections import defaultdict
import uuid
import io
import json
import math
import random
from datetime import datetime
from openpyxl import load_workbook, Workbook

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
        # ---- 本轮新增 ----
        "demand_mode": ("VARCHAR(32)", "'curve_preset'"),
        "game_total_months": ("INTEGER", "12"),
        "demand_seed": ("INTEGER", "20240920"),
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

            # ---- demand_plan 表（本次新增），SQLite手工判断不存在才创建 ----
            dp_exist = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='demand_plan'")).fetchone()
            if dp_exist is None:
                conn.execute(text("""
                    CREATE TABLE demand_plan (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        month INTEGER NOT NULL UNIQUE,
                        base_demand FLOAT NOT NULL DEFAULT 400.0,
                        source VARCHAR(16) DEFAULT 'default',
                        curve_type VARCHAR(32),
                        params_json TEXT,
                        updated_at DATETIME,
                        updated_by INTEGER REFERENCES users(id)
                    )
                """))
        else:
            for col, (col_type, default_value) in desired_game_config.items():
                conn.execute(text(f"ALTER TABLE game_config ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default_value}"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_token VARCHAR(64)"))
            for col, (col_type, default_value) in desired_game_state.items():
                conn.execute(text(f"ALTER TABLE game_state ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default_value}"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS demand_plan (
                    id SERIAL PRIMARY KEY,
                    month INTEGER NOT NULL UNIQUE,
                    base_demand FLOAT NOT NULL DEFAULT 400.0,
                    source VARCHAR(16) DEFAULT 'default',
                    curve_type VARCHAR(32),
                    params_json TEXT,
                    updated_at TIMESTAMP,
                    updated_by INTEGER REFERENCES users(id)
                )
            """))

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

class StudentCreate(BaseModel):
    username: str
    password: str

class StudentBatchCreate(BaseModel):
    students: List[StudentCreate]

class StudentResetPassword(BaseModel):
    password: str


class GameConfigUpdate(BaseModel):
    selling_price: Optional[float] = None
    supplier1_price: Optional[float] = None
    supplier1_lead_time: Optional[int] = None
    supplier2_price: Optional[float] = None
    supplier2_lead_time: Optional[int] = None
    factory_capacity: Optional[float] = None
    raw_holding_cost: Optional[float] = None
    fg_holding_cost: Optional[float] = None
    raw_warehouse_capacity: Optional[float] = None
    fg_warehouse_capacity: Optional[float] = None
    raw_overflow_cost: Optional[float] = None
    fg_overflow_cost: Optional[float] = None
    demand_variation_low: Optional[float] = None
    demand_variation_high: Optional[float] = None
    fixed_cost_per_month: Optional[float] = None
    stockout_penalty_per_unit: Optional[float] = None
    negative_cash_interest_rate: Optional[float] = None
    initial_cash: Optional[float] = None
    initial_raw_stock: Optional[float] = None
    initial_fg_stock: Optional[float] = None
    # ---- 本轮新增 3 项可配置 ----
    demand_mode: Optional[str] = None          # excel_import / curve_preset
    game_total_months: Optional[int] = None    # 6 ~ 24
    demand_seed: Optional[int] = None          # 换卷种子


class LoginRequest(BaseModel):
    username: str
    password: str


def get_or_create_config(db: Session) -> models.GameConfig:
    config = db.query(models.GameConfig).first()
    if config:
        # ---- 兼容老库补默认值 ----
        if config.demand_mode is None or config.demand_mode.lower() == "student_forecast":
            config.demand_mode = "curve_preset"
        if config.game_total_months is None or config.game_total_months < 6 or config.game_total_months > 24:
            config.game_total_months = 12
        if config.demand_seed is None:
            config.demand_seed = 20240920
        return config
    config = models.GameConfig(
        selling_price=100, supplier1_price=40, supplier1_lead_time=1,
        supplier2_price=60, supplier2_lead_time=0, factory_capacity=1000,
        raw_holding_cost=2, fg_holding_cost=5,
        raw_warehouse_capacity=2000, fg_warehouse_capacity=1500,
        raw_overflow_cost=10, fg_overflow_cost=20,
        demand_variation_low=0.7, demand_variation_high=1.3,
        fixed_cost_per_month=3000, stockout_penalty_per_unit=10,
        negative_cash_interest_rate=0.02,
        initial_cash=100000, initial_raw_stock=500, initial_fg_stock=200,
        # ---- 本轮新增默认值 ----
        demand_mode="curve_preset",
        game_total_months=12,
        demand_seed=20240920,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _serialize_config(config: models.GameConfig, db: Optional[Session] = None, user_month: Optional[int] = None) -> dict:
    data = {
        "id": config.id,
        "selling_price": float(config.selling_price or 0),
        "supplier1_price": float(config.supplier1_price or 0),
        "supplier1_lead_time": int(config.supplier1_lead_time or 0),
        "supplier2_price": float(config.supplier2_price or 0),
        "supplier2_lead_time": int(config.supplier2_lead_time or 0),
        "factory_capacity": float(config.factory_capacity or 0),
        "raw_holding_cost": float(config.raw_holding_cost or 0),
        "fg_holding_cost": float(config.fg_holding_cost or 0),
        "raw_warehouse_capacity": float(config.raw_warehouse_capacity or 0),
        "fg_warehouse_capacity": float(config.fg_warehouse_capacity or 0),
        "raw_overflow_cost": float(config.raw_overflow_cost or 0),
        "fg_overflow_cost": float(config.fg_overflow_cost or 0),
        "demand_variation_low": float(config.demand_variation_low or 0),
        "demand_variation_high": float(config.demand_variation_high or 0),
        "fixed_cost_per_month": float(config.fixed_cost_per_month or 0),
        "stockout_penalty_per_unit": float(config.stockout_penalty_per_unit or 0),
        "negative_cash_interest_rate": float(config.negative_cash_interest_rate or 0),
        "initial_cash": float(config.initial_cash or 0),
        "initial_raw_stock": float(config.initial_raw_stock or 0),
        "initial_fg_stock": float(config.initial_fg_stock or 0),
        # ---- 本轮新增 3 字段回显 ----
        "demand_mode": config.demand_mode or "curve_preset",
        "game_total_months": int(config.game_total_months or 12),
        "demand_seed": int(config.demand_seed or 20240920),
    }
    # ---- 如果学生端GET时带了user_month，追加本月基准需求量提示 ----
    if db is not None and user_month is not None:
        data["current_month_base_demand"] = _resolve_base_demand(db, config, user_month)
    return data


@app.on_event("startup")
def startup_init_config():
    db = database.SessionLocal()
    try:
        config = get_or_create_config(db)
        # ---- 初始化 DemandPlan：按 game_total_months 填充默认 400，不足补齐，超出删除 ----
        _ensure_default_demand_plan(db, config)
    finally:
        db.close()


# ============================================================
#  本轮核心：Demand 模式公共函数 & 6 种曲线公式
# ============================================================

def _seeded_variation(seed: int, month: int, low: float, high: float) -> float:
    """基于 (seed+month) 确定性生成 uniform 波动 → 同月全班 actual_demand 一字不差"""
    if low <= 0:
        low = 0.7
    if high <= 0:
        high = 1.3
    if low > high:
        low, high = high, low
    rng = random.Random()
    rng.seed(int(seed) * 1_000_003 + int(month) * 31 + 7)
    return rng.uniform(low, high)


def _ensure_default_demand_plan(db: Session, config: models.GameConfig):
    """保证 DemandPlan 表至少有 1..game_total_months 月的记录（默认400），过长的月份删除"""
    total = int(config.game_total_months or 12)
    total = max(6, min(24, total))
    existing_rows = db.query(models.DemandPlan).all()
    existing_by_month = {int(r.month): r for r in existing_rows}
    # 补齐缺失月
    for m in range(1, total + 1):
        if m not in existing_by_month:
            db.add(models.DemandPlan(month=m, base_demand=400.0, source="default"))
    # 删除超出总月数的旧记录（允许保留但避免过长）
    for r in existing_rows:
        if int(r.month) > total:
            db.delete(r)
    db.commit()


def _resolve_base_demand(db: Session, config: models.GameConfig, month: int) -> float:
    """根据 DemandPlan 表解析出该月基准中枢（teacher 预设模式）；缺失则按 400 兜底。
    注意：旧 student_forecast 模式已彻底删除，实际需求永远走 班级共用 base + seeded 波动。
    """
    m = int(month)
    row = db.query(models.DemandPlan).filter(models.DemandPlan.month == m).first()
    if row is not None and row.base_demand is not None:
        base = float(row.base_demand)
        return base if base > 0 else 400.0
    return 400.0


def _generate_curve_values(curve_type: str, params: Dict[str, Any], total_months: int) -> List[float]:
    """6 种曲线生成器，返回长度为 total_months 的每月 base_demand（四舍五入到整数）。"""
    total = max(6, min(24, int(total_months)))
    t_list = list(range(1, total + 1))
    curve = (curve_type or "flat").lower()

    def _round(x: float) -> float:
        return float(max(1, round(x)))

    if curve == "flat":
        base = float(params.get("base", 400))
        return [_round(base) for _ in t_list]

    if curve == "sine":
        base = float(params.get("base", 400))
        amp = float(params.get("amplitude", 150))
        period = float(params.get("period", 12))
        shift = float(params.get("phase_shift", 0))
        return [
            _round(base + amp * math.sin(2 * math.pi * (t + shift) / max(1, period)))
            for t in t_list
        ]

    if curve == "linear_growth":
        base = float(params.get("base", 400))
        growth = float(params.get("growth_per_month", 15))
        return [_round(base + growth * (t - 1)) for t in t_list]

    if curve == "boom_bust":
        base = float(params.get("base", 400))
        boom_gain = float(params.get("boom_gain", 200))
        bust_loss = float(params.get("bust_loss", -250))
        vals = []
        for t in t_list:
            if t <= total * 0.33:
                ratio = t / max(1, total * 0.33)
                vals.append(_round(base + boom_gain * ratio))
            elif t <= total * 0.66:
                vals.append(_round(base + boom_gain))
            else:
                ratio = (t - total * 0.66) / max(1, total * 0.34)
                vals.append(_round(base + boom_gain + bust_loss * ratio))
        return vals

    if curve == "bullwhip":
        base = float(params.get("base", 400))
        noise_scale = float(params.get("noise_scale", 80))
        rng = random.Random()
        rng.seed(int(params.get("seed", 9999)))
        vals = []
        for t in t_list:
            amplify = 1 + 0.05 * (t - 1)
            noise = rng.gauss(0, 1) * noise_scale * amplify
            vals.append(_round(base + noise))
        return vals

    if curve == "promo_pulse":
        base = float(params.get("base", 400))
        pulse_every = max(1, int(params.get("pulse_every", 3)))
        peak_mult = float(params.get("peak_mult", 2.0))
        normal_mult = float(params.get("normal_mult", 0.9))
        vals = []
        for t in t_list:
            if t % pulse_every == 0:
                vals.append(_round(base * peak_mult))
            else:
                vals.append(_round(base * normal_mult))
        return vals

    # 兜底：平稳
    base = float(params.get("base", 400))
    return [_round(base) for _ in t_list]


def _upsert_demand_plan(db: Session,
                        values_by_month: Dict[int, float],
                        source: str,
                        curve_type: Optional[str] = None,
                        params_json: Optional[str] = None,
                        teacher_id: Optional[int] = None):
    """按 month upsert DemandPlan，多余的月份不删（交给上层 ensure_default）。"""
    warnings = []
    existing = db.query(models.DemandPlan).all()
    by_month = {int(r.month): r for r in existing}
    seen_months = set()
    for m_raw, v in values_by_month.items():
        try:
            m = int(m_raw)
        except Exception:
            warnings.append(f"非法月份 {m_raw}，已跳过")
            continue
        if m < 1 or m > 24:
            warnings.append(f"月份 {m} 超出 1-24 范围，已跳过")
            continue
        if m in seen_months:
            warnings.append(f"重复月份 {m}，覆盖为最新值")
        seen_months.add(m)
        base_val = float(v) if float(v) > 0 else 400.0
        if m in by_month:
            row = by_month[m]
            row.base_demand = base_val
            row.source = source
            row.curve_type = curve_type
            row.params_json = params_json
            row.updated_at = datetime.utcnow()
            row.updated_by = teacher_id
        else:
            db.add(models.DemandPlan(
                month=m, base_demand=base_val, source=source,
                curve_type=curve_type, params_json=params_json,
                updated_at=datetime.utcnow(), updated_by=teacher_id
            ))
    db.commit()
    return warnings


def _demand_plan_to_list(db: Session, total_months: int) -> List[Dict[str, Any]]:
    """返回 [ {month, base_demand, source, curve_type} ... ] 按月份排序"""
    rows = db.query(models.DemandPlan).order_by(models.DemandPlan.month.asc()).all()
    result = []
    for r in rows:
        if int(r.month) > int(total_months or 12):
            continue
        result.append({
            "month": int(r.month),
            "base_demand": float(r.base_demand or 0),
            "source": r.source or "default",
            "curve_type": r.curve_type or None,
        })
    return result


# ============================================================
#  本轮 Pydantic 请求模型
# ============================================================

class DemandModeUpdate(BaseModel):
    demand_mode: str  # student_forecast / excel_import / curve_preset


class CurveGenerateRequest(BaseModel):
    curve_type: str                           # flat/sine/linear_growth/boom_bust/bullwhip/promo_pulse
    params: Dict[str, Any] = {}               # 曲线参数
    persist: bool = False                     # True=写库 False=仅预览


class DemandPlanBatchUpdate(BaseModel):
    rows: List[Dict[str, Any]]                # [{month, base_demand} ...]，来自教师端表格编辑后批量保存


# ============================================================
#  本轮 6 个 Demand 相关 HTTP 接口（全部 teacher 保护，除 list 可给 teacher）
# ============================================================

@app.get("/teacher/demand-summary")
def teacher_get_demand_summary(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    """返回当前 mode + total_months + seed + 每月基准列表（供Tab4页面加载）"""
    config = get_or_create_config(db)
    _ensure_default_demand_plan(db, config)
    return {
        "demand_mode": config.demand_mode or "curve_preset",
        "game_total_months": int(config.game_total_months or 12),
        "demand_seed": int(config.demand_seed or 20240920),
        "demand_variation_low": float(config.demand_variation_low or 0.7),
        "demand_variation_high": float(config.demand_variation_high or 1.3),
        "list": _demand_plan_to_list(db, config.game_total_months),
    }


@app.put("/teacher/demand-mode")
def teacher_update_demand_mode(
    body: DemandModeUpdate,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    mode = (body.demand_mode or "curve_preset").lower()
    if mode not in {"excel_import", "curve_preset"}:
        raise HTTPException(status_code=400, detail="无效 demand_mode，仅允许 excel_import / curve_preset")
    config = get_or_create_config(db)
    config.demand_mode = mode
    db.commit()
    db.refresh(config)
    return {"success": True, "demand_mode": config.demand_mode}


@app.get("/teacher/demand-plan/template.xlsx")
def teacher_download_demand_template(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    config = get_or_create_config(db)
    total = int(config.game_total_months or 12)
    wb = Workbook()
    ws = wb.active
    ws.title = "monthly_demand"
    ws.append(["月份", "基准需求量(必填)", "备注(可选)"])
    sample_peaks = {1: 400, 3: 420, 6: 500, 9: 380, 12: 450}
    for m in range(1, total + 1):
        ws.append([m, sample_peaks.get(m, 400), f"第{m}月需求量中枢；最终实际需求 = 基准 × 随机波动({config.demand_variation_low}~{config.demand_variation_high})"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    headers = {"Content-Disposition": "attachment; filename=demand_plan_template.xlsx"}
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@app.post("/teacher/demand-plan/import-excel")
async def teacher_import_demand_excel(
    file: UploadFile = File(...),
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    data = await file.read()
    try:
        wb = load_workbook(filename=io.BytesIO(data), data_only=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel解析失败: {str(e)}")
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers_row = next(rows_iter, None)
    if headers_row is None:
        raise HTTPException(status_code=400, detail="空Excel")

    def _match_col(target_keywords, row_values):
        for idx, cell in enumerate(row_values):
            txt = "" if cell is None else str(cell).lower()
            for kw in target_keywords:
                if kw in txt:
                    return idx
        return -1

    col_month = _match_col(["month", "月份", "月"], headers_row)
    col_base = _match_col(["demand", "base", "基准", "需求", "量"], headers_row)
    if col_month < 0 or col_base < 0:
        raise HTTPException(status_code=400, detail="缺少列：第一行需包含 [月份/month] 与 [基准需求量/demand/base]")
    values = {}
    for raw in rows_iter:
        if raw is None or all(c is None or str(c).strip() == "" for c in raw):
            continue
        try:
            m = int(raw[col_month])
            v = float(raw[col_base])
        except Exception:
            continue
        values[m] = v
    warnings = _upsert_demand_plan(db, values, source="excel", teacher_id=teacher.id)
    config = get_or_create_config(db)
    return {
        "success": True,
        "imported_months": len(values),
        "warnings": warnings,
        "list": _demand_plan_to_list(db, config.game_total_months)
    }


@app.post("/teacher/demand-plan/generate-curve")
def teacher_generate_curve(
    body: CurveGenerateRequest,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    config = get_or_create_config(db)
    total = int(config.game_total_months or 12)
    values = _generate_curve_values(body.curve_type, body.params or {}, total_months=total)
    values_by_month = {(i + 1): v for i, v in enumerate(values)}
    warnings = []
    if body.persist:
        params_json = json.dumps({
            "curve_type": body.curve_type,
            "params": body.params or {}
        }, ensure_ascii=False)
        warnings = _upsert_demand_plan(
            db, values_by_month,
            source="curve", curve_type=body.curve_type.lower(),
            params_json=params_json, teacher_id=teacher.id
        )
    # 同时把 seeded_variation 的包络线也返回（前端画上下灰线）
    low = float(config.demand_variation_low or 0.7)
    high = float(config.demand_variation_high or 1.3)
    seed = int(config.demand_seed or 20240920)
    envelope = []
    for m in range(1, total + 1):
        v = values_by_month[m]
        var = _seeded_variation(seed, m, low, high)
        envelope.append({
            "month": m,
            "base": v,
            "variation": round(var, 4),
            "actual_demand_seeded": round(v * var)
        })
    return {
        "success": True,
        "persisted": body.persist,
        "warnings": warnings,
        "envelope": envelope,
        "list": _demand_plan_to_list(db, config.game_total_months) if body.persist else None
    }


@app.put("/teacher/demand-plan/batch")
def teacher_batch_update_demand_plan(
    body: DemandPlanBatchUpdate,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    """用于教师端手动编辑表格后一次性保存"""
    values = {}
    for r in (body.rows or []):
        try:
            m = int(r["month"])
            v = float(r["base_demand"])
            values[m] = v
        except Exception:
            continue
    warnings = _upsert_demand_plan(db, values, source="manual", teacher_id=teacher.id)
    config = get_or_create_config(db)
    return {
        "success": True,
        "updated_months": len(values),
        "warnings": warnings,
        "list": _demand_plan_to_list(db, config.game_total_months)
    }


@app.delete("/teacher/demand-plan")
def teacher_reset_demand_plan(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    """清空并重设为全400默认"""
    db.query(models.DemandPlan).delete()
    db.commit()
    config = get_or_create_config(db)
    _ensure_default_demand_plan(db, config)
    return {"success": True, "list": _demand_plan_to_list(db, config.game_total_months)}


@app.get("/")
async def root():
    return {"message": "Welcome to the Supply Chain Game API"}


@app.get("/game-config")
def get_game_config(
    month: Optional[int] = None,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    config = get_or_create_config(db)
    return _serialize_config(config, db=db, user_month=month)


@app.get("/teacher/game-config")
def teacher_get_game_config(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    config = get_or_create_config(db)
    return _serialize_config(config)


@app.put("/teacher/game-config")
def teacher_update_game_config(
    update: GameConfigUpdate,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    config = get_or_create_config(db)
    data = update.dict(exclude_unset=True)
    for field, value in data.items():
        if value is None:
            continue
        # ---- 边界保护 ----
        if field == "game_total_months":
            value = int(value)
            value = max(6, min(24, value))
        if field == "demand_seed":
            value = int(value)
        setattr(config, field, value)
    if config.demand_variation_low is not None and config.demand_variation_high is not None:
        if config.demand_variation_low > config.demand_variation_high:
            config.demand_variation_low, config.demand_variation_high = config.demand_variation_high, config.demand_variation_low
    # 改了总月数后，自动确保 DemandPlan 范围匹配
    if "game_total_months" in data:
        _ensure_default_demand_plan(db, config)
    db.commit()
    db.refresh(config)
    return {"success": True, "config": _serialize_config(config)}

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
def create_user(user: UserCreate, teacher: models.User = Depends(get_current_teacher), db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    if user.role not in ["student", "teacher"]:
        raise HTTPException(status_code=400, detail="角色无效")
    if user.role == "teacher":
        raise HTTPException(status_code=400, detail="不允许通过此接口创建教师账号")

    db_user = models.User(username=user.username, password_hash=user.password, role=user.role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    token = issue_token(db_user, db)

    _init_student_game(db, db_user)

    return {"id": db_user.id, "username": db_user.username, "role": db_user.role, "token": token}


def _init_student_game(db: Session, db_user: models.User):
    """为新创建的学生账号初始化游戏配置和首个月的状态"""
    config = get_or_create_config(db)

    existing_first = db.query(models.GameState).filter(
        models.GameState.user_id == db_user.id,
        models.GameState.month == 1
    ).first()
    if existing_first:
        return

    first_state = models.GameState(
        user_id=db_user.id, month=1,
        cash=config.initial_cash, raw_material_stock=config.initial_raw_stock,
        finished_goods_stock=config.initial_fg_stock,
        is_submitted=False, is_settled=False
    )
    db.add(first_state)
    db.commit()


@app.post("/teacher/students/create")
def teacher_create_student(
    student: StudentCreate,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    existing = db.query(models.User).filter(models.User.username == student.username).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"用户名 {student.username} 已存在")

    db_user = models.User(username=student.username, password_hash=student.password, role="student")
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    _init_student_game(db, db_user)

    return {
        "success": True,
        "id": db_user.id,
        "username": db_user.username,
        "password": student.password
    }


@app.post("/teacher/students/batch")
def teacher_batch_create_students(
    batch: StudentBatchCreate,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    created = []
    failed = []

    existing_usernames = {u.username for u in db.query(models.User).all()}

    for s in batch.students:
        if s.username in existing_usernames:
            failed.append({"username": s.username, "reason": "用户名已存在"})
            continue
        if not s.username or not s.password:
            failed.append({"username": s.username or "(空)", "reason": "用户名或密码为空"})
            continue

        try:
            db_user = models.User(username=s.username, password_hash=s.password, role="student")
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            _init_student_game(db, db_user)
            created.append({
                "id": db_user.id,
                "username": db_user.username,
                "password": s.password
            })
            existing_usernames.add(s.username)
        except Exception as e:
            db.rollback()
            failed.append({"username": s.username, "reason": str(e)})

    return {"success": True, "created": created, "failed": failed, "total": len(batch.students)}


@app.post("/teacher/students/import-excel")
async def teacher_import_excel_students(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db),
    file: UploadFile = File(...)
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls 格式的 Excel 文件")

    try:
        contents = await file.read()
        wb = load_workbook(filename=io.BytesIO(contents), read_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            raise HTTPException(status_code=400, detail="Excel 内容为空，至少需要标题行和一行数据")

        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        username_idx = None
        password_idx = None

        for i, h in enumerate(header):
            h_lower = h.lower()
            if "用户名" in h or "姓名" in h or "账号" in h or "name" in h_lower or "username" in h_lower:
                username_idx = i
            elif "密码" in h or "password" in h_lower or "pwd" in h_lower:
                password_idx = i

        if username_idx is None:
            username_idx = 0
        if password_idx is None:
            password_idx = 1

        created = []
        failed = []

        existing_usernames = {u.username for u in db.query(models.User).all()}

        for row_num, row in enumerate(rows[1:], start=2):
            if row is None:
                continue
            username_val = row[username_idx] if username_idx < len(row) else None
            password_val = row[password_idx] if password_idx < len(row) else None

            username = str(username_val).strip() if username_val is not None else ""
            password = str(password_val).strip() if password_val is not None else ""

            if not username:
                failed.append({"row": row_num, "username": "(空)", "reason": "用户名为空，已跳过"})
                continue

            if not password:
                password = "123456"

            if username in existing_usernames:
                failed.append({"row": row_num, "username": username, "reason": "用户名已存在"})
                continue

            try:
                db_user = models.User(username=username, password_hash=password, role="student")
                db.add(db_user)
                db.commit()
                db.refresh(db_user)
                _init_student_game(db, db_user)
                created.append({
                    "id": db_user.id,
                    "username": db_user.username,
                    "password": password,
                    "row": row_num
                })
                existing_usernames.add(username)
            except Exception as e:
                db.rollback()
                failed.append({"row": row_num, "username": username, "reason": str(e)})

        wb.close()

        return {
            "success": True,
            "created": created,
            "failed": failed,
            "total": len(rows) - 1
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 Excel 失败：{str(e)}")


@app.get("/teacher/students/list")
def teacher_list_students(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    students = db.query(models.User).filter(models.User.role == "student").order_by(models.User.id.asc()).all()
    result = []
    for s in students:
        settled_states = db.query(models.GameState).filter(
            models.GameState.user_id == s.id,
            models.GameState.is_settled == True
        ).all()
        total_profit = float(sum(st.profit or 0 for st in settled_states))
        months_played = len(settled_states)
        result.append({
            "id": s.id,
            "username": s.username,
            "months_played": months_played,
            "total_profit": total_profit
        })
    return result


@app.put("/teacher/students/{student_id}/reset-password")
def teacher_reset_student_password(
    student_id: int,
    reset: StudentResetPassword,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    student = db.query(models.User).filter(
        models.User.id == student_id,
        models.User.role == "student"
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生账号不存在")

    student.password_hash = reset.password
    student.auth_token = None
    db.commit()

    return {"success": True, "id": student.id, "username": student.username, "new_password": reset.password}


@app.delete("/teacher/students/{student_id}")
def teacher_delete_student(
    student_id: int,
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    student = db.query(models.User).filter(
        models.User.id == student_id,
        models.User.role == "student"
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生账号不存在")

    db.query(models.GameState).filter(models.GameState.user_id == student_id).delete()
    db.delete(student)
    db.commit()

    return {"success": True, "id": student_id, "username": student.username}

@app.get("/game_state/{user_id}")
def get_game_state(
    user_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 学生只能看自己的 state，老师可以看所有
    if user.role == "student" and int(user.id) != int(user_id):
        raise HTTPException(status_code=403, detail="无权查看其他学生的游戏状态")
    state = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_settled == False
    ).order_by(models.GameState.month.asc()).first()

    if not state:
        raise HTTPException(status_code=404, detail="No active game state found")
    return state


@app.get("/history/{user_id}")
def get_history(
    user_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role == "student" and int(user.id) != int(user_id):
        raise HTTPException(status_code=403, detail="无权查看其他学生的历史")
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
def get_report(
    user_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role == "student" and int(user.id) != int(user_id):
        raise HTTPException(status_code=403, detail="无权查看其他学生的报告")
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
        "forecast_demand": report.forecast_demand,
        "production_quantity": report.production_quantity,
        "purchase_supplier_1": report.purchase_supplier_1,
        "purchase_supplier_2": report.purchase_supplier_2,
    }

@app.post("/submit_decision")
def submit_decision(
    decision: DecisionSubmit,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role == "student" and int(user.id) != int(decision.user_id):
        raise HTTPException(status_code=403, detail="无权替其他学生提交决策")
    state = db.query(models.GameState).filter(
        models.GameState.user_id == decision.user_id,
        models.GameState.is_submitted == False,
        models.GameState.is_settled == False
    ).first()

    if not state:
        raise HTTPException(status_code=400, detail="No active month found or decision already submitted")

    # ---- 游戏封盘保护：如果当前月超过总月数或最后一月已结算，禁止继续提交 ----
    config = get_or_create_config(db)
    total_months = int(config.game_total_months or 12)
    if int(state.month) > total_months:
        raise HTTPException(status_code=400, detail=f"游戏已结束（共 {total_months} 个月）")

    if decision.forecast_demand < 0:
        raise HTTPException(status_code=400, detail="forecast_demand must be >= 0")
    if decision.purchase_supplier_1 < 0 or decision.purchase_supplier_2 < 0:
        raise HTTPException(status_code=400, detail="purchase quantity must be >= 0")
    if decision.production_quantity < 0:
        raise HTTPException(status_code=400, detail="production_quantity must be >= 0")

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
        "game_total_months": total_months,
        "game_finished": int(state.month) >= total_months,
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
def settle_month(
    user_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role == "student" and int(user.id) != int(user_id):
        raise HTTPException(status_code=403, detail="无权替其他学生结算")
    state = db.query(models.GameState).filter(
        models.GameState.user_id == user_id,
        models.GameState.is_submitted == True,
        models.GameState.is_settled == False
    ).first()

    if not state:
        raise HTTPException(status_code=400, detail="No submitted decision found for this month")

    config = get_or_create_config(db)
    total_months = int(config.game_total_months or 12)
    # ---- 封盘保护 ----
    if int(state.month) > total_months:
        raise HTTPException(status_code=400, detail=f"游戏已结束（共 {total_months} 个月）")

    # ============================================================
    #  本轮关键：先按 mode+month 解析 base_demand + seeded_variation
    #  注入到 state 临时属性，game_logic 会优先使用它们（保持纯函数无DB依赖）
    # ============================================================
    base = _resolve_base_demand(db, config, state.month)
    variation = _seeded_variation(
        seed=int(config.demand_seed or 20240920),
        month=int(state.month),
        low=float(config.demand_variation_low or 0.7),
        high=float(config.demand_variation_high or 1.3)
    )
    state._demand_base_for_calc = float(base)
    state._demand_variation_for_calc = float(variation)

    # 2. Calculate results（已无 student_forecast，100%教师预设）
    game_logic.calculate_monthly_results(state, config)

    is_last_month = int(state.month) >= total_months

    # 3. 如果不是最后一个月 → 创建下月状态；否则不建，封盘
    if not is_last_month:
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
        "game_total_months": total_months,
        "game_finished": is_last_month,
        "profit": state.profit,
        "actual_demand": state.actual_demand,
        "actual_sales": state.actual_sales
    }

def _build_student_ranking(db: Session):
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


@app.get("/teacher/ranking")
def get_ranking(teacher: models.User = Depends(get_current_teacher), db: Session = Depends(get_db)):
    return _build_student_ranking(db)


@app.get("/student/my-ranking")
def get_student_my_ranking(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "student":
        raise HTTPException(status_code=403, detail="仅学生可调用此接口")
    ranking = _build_student_ranking(db)
    total_students = len(ranking)
    my_entry = next((r for r in ranking if r["user_id"] == user.id), None)
    my_rank = my_entry["rank"] if my_entry else None
    my_total_profit = my_entry["total_profit"] if my_entry else 0.0
    my_months_played = my_entry["months_played"] if my_entry else 0

    first_entry = ranking[0] if ranking else None
    first_user_id = first_entry["user_id"] if first_entry else None
    first_total_profit = first_entry["total_profit"] if first_entry else 0.0
    first_months_played = first_entry["months_played"] if first_entry else 0

    first_history = []
    if first_user_id is not None:
        states = db.query(models.GameState).filter(
            models.GameState.user_id == first_user_id,
            models.GameState.is_settled == True
        ).order_by(models.GameState.month.asc()).all()
        cumulative = 0.0
        for s in states:
            profit_val = float(s.profit or 0)
            cumulative += profit_val
            first_history.append({
                "month": s.month,
                "profit": profit_val,
                "cumulative_profit": cumulative,
                "revenue": float(s.revenue or 0),
                "total_cost": float(s.total_cost or 0)
            })

    return {
        "total_students": total_students,
        "my_rank": my_rank,
        "my_total_profit": my_total_profit,
        "my_months_played": my_months_played,
        "first_place": {
            "display_name": "当前第一名" if first_entry else None,
            "total_profit": first_total_profit,
            "months_played": first_months_played,
            "history": first_history
        }
    }

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


@app.post("/teacher/reset_class")
def teacher_reset_class(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    """全班初始化下一轮：清空所有学生的游戏进度(game_state + report)，并为每个学生重建月1初始状态。
    不删除学生账号，不删除教师配置（GameConfig）和需求计划（DemandPlan）。
    """
    students = db.query(models.User).filter(models.User.role == "student").all()
    student_ids = [u.id for u in students]

    total_states_deleted = 0
    if student_ids:
        # 游戏的月度数据 + 报告都在 GameState 表里（is_settled=True 当报告用，is_settled=False 当本月进行中）
        states_deleted_q = db.query(models.GameState).filter(
            models.GameState.user_id.in_(student_ids)
        )
        total_states_deleted = states_deleted_q.count()
        states_deleted_q.delete(synchronize_session=False)
        db.commit()

    # 为每个学生重建第 1 个月的初始状态（和 _init_student_game 逻辑一致，但用当前最新 GameConfig 值）
    config = get_or_create_config(db)
    rebuilt = 0
    for u in students:
        first_state = models.GameState(
            user_id=u.id, month=1,
            cash=config.initial_cash,
            raw_material_stock=config.initial_raw_stock,
            finished_goods_stock=config.initial_fg_stock,
            is_submitted=False, is_settled=False
        )
        db.add(first_state)
        rebuilt += 1
    db.commit()

    return {
        "message": "全班已重置并初始化新一轮游戏",
        "students_total": len(students),
        "game_states_deleted": total_states_deleted,
        "months_initialized": rebuilt
    }


@app.get("/teacher/export_class_ranking")
def teacher_export_class_ranking(
    teacher: models.User = Depends(get_current_teacher),
    db: Session = Depends(get_db)
):
    """导出全班匿名排名 + 各月明细 Excel。
    全匿名：第1列为「排名」（按累计总利润倒序），不暴露 username / user_id 等任何个人信息。
    Sheet1 = 「全班排名汇总」：排名 / 累计总利润 / 已完成月数 / 总收益 / 总成本 / 本月利润（最新月）
    Sheet2 = 「各月利润明细」：行=排名1..N，列=月1..月M 的当月利润
    Sheet3 = 「各月预测 vs 实际 对比」：行=排名1..N，列=月M 的 (预测需求 / 实际需求 / 预测偏差率%) 每3列
    """
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    # 1. 收集所有学生的累计利润
    students = db.query(models.User).filter(models.User.role == "student").all()

    rows = []
    max_month_any = 0
    for u in students:
        reports = db.query(models.GameState).filter(
            models.GameState.user_id == u.id,
            models.GameState.is_settled == True
        ).order_by(models.GameState.month.asc()).all()
        if not reports:
            # 没玩过一局也放进导出表（累计利润 = 初始现金），显示已完成 0 月
            init_config = get_or_create_config(db)
            rows.append({
                "uid": u.id,
                "total_profit": 0.0,
                "months_played": 0,
                "total_revenue": 0.0,
                "total_cost": 0.0,
                "latest_month_profit": None,
                "by_month": {}
            })
            continue
        total_profit = 0.0
        total_rev = 0.0
        total_cost = 0.0
        by_month = {}
        latest_month_profit = 0.0
        for r in reports:
            month = r.month
            profit_val = float(r.profit or 0)
            total_profit += profit_val
            total_rev += float(r.revenue or 0)
            total_cost += float(r.total_cost or 0)
            latest_month_profit = profit_val
            by_month[month] = {
                "profit": profit_val,
                "revenue": float(r.revenue or 0),
                "actual_demand": float(r.actual_demand or 0),
                "actual_sales": float(r.actual_sales or 0),
                "forecast_demand": float(r.forecast_demand or 0) if r.forecast_demand is not None else None,
                "total_cost": float(r.total_cost or 0),
            }
            if month > max_month_any:
                max_month_any = month
        rows.append({
            "uid": u.id,
            "total_profit": total_profit,
            "months_played": len(reports),
            "total_revenue": total_rev,
            "total_cost": total_cost,
            "latest_month_profit": latest_month_profit,
            "by_month": by_month,
        })

    # 按累计总利润从高到低排；若相同按已完成月数多优先（模拟「先完成者胜」）；稳定
    rows.sort(key=lambda r: (-r["total_profit"], -r["months_played"]))

    wb = Workbook()
    bold = Font(bold=True, size=11)
    center = Alignment(horizontal="center", vertical="center")
    header_fill = PatternFill(start_color="FFE2EFDA", end_color="FFE2EFDA", fill_type="solid")
    profit_fill = PatternFill(start_color="FFFFF2CC", end_color="FFFFF2CC", fill_type="solid")

    # ======== Sheet 1: 全班排名汇总 ========
    ws1 = wb.active
    ws1.title = "全班排名汇总"
    headers1 = ["排名", "累计总利润（元）", "已完成月数", "累计总收益（元）", "累计总成本（元）", "最新结算月利润（元）"]
    for i, h in enumerate(headers1, start=1):
        cell = ws1.cell(row=1, column=i, value=h)
        cell.font = bold; cell.fill = header_fill; cell.alignment = center
    for idx, r in enumerate(rows, start=1):
        ws1.cell(row=idx + 1, column=1, value=idx).alignment = center
        p_cell = ws1.cell(row=idx + 1, column=2, value=round(r["total_profit"], 2))
        p_cell.fill = profit_fill
        ws1.cell(row=idx + 1, column=3, value=r["months_played"]).alignment = center
        ws1.cell(row=idx + 1, column=4, value=round(r["total_revenue"], 2))
        ws1.cell(row=idx + 1, column=5, value=round(r["total_cost"], 2))
        ws1.cell(row=idx + 1, column=6, value=round(r["latest_month_profit"], 2) if r["latest_month_profit"] is not None else "—")
    for c in range(1, len(headers1) + 1):
        ws1.column_dimensions[get_column_letter(c)].width = max(18, len(headers1[c - 1]) + 4)

    # ======== Sheet 2: 各月利润明细（行=排名, 列=月1..月M）========
    ws2 = wb.create_sheet(title="各月利润明细")
    ws2.cell(row=1, column=1, value="排名").font = bold
    ws2.cell(row=1, column=1).fill = header_fill
    ws2.cell(row=1, column=1).alignment = center
    total_months = max(max_month_any, 1)
    for m in range(1, total_months + 1):
        cell = ws2.cell(row=1, column=m + 1, value=f"第 {m} 月利润（元）")
        cell.font = bold; cell.fill = header_fill; cell.alignment = center
    for idx, r in enumerate(rows, start=1):
        ws2.cell(row=idx + 1, column=1, value=idx).alignment = center
        for m in range(1, total_months + 1):
            md = r["by_month"].get(m)
            val = round(md["profit"], 2) if md else "—"
            c = ws2.cell(row=idx + 1, column=m + 1, value=val)
            if md and float(md["profit"] or 0) > 0:
                c.fill = profit_fill
    for col in range(1, total_months + 2):
        ws2.column_dimensions[get_column_letter(col)].width = 15

    # ======== Sheet 3: 各月预测 vs 实际 对比（每月份3列：预测需求 / 实际需求 / 预测偏差率%）========
    ws3 = wb.create_sheet(title="各月预测 vs 实际对比")
    ws3.cell(row=1, column=1, value="排名").font = bold
    ws3.cell(row=1, column=1).fill = header_fill
    ws3.cell(row=1, column=1).alignment = center
    col = 2
    header_3_map = {}  # month -> (pred_col, act_col, dev_col)
    for m in range(1, total_months + 1):
        pred_c = ws3.cell(row=1, column=col + 0, value=f"月{m}·预测需求")
        act_c = ws3.cell(row=1, column=col + 1, value=f"月{m}·实际需求")
        dev_c = ws3.cell(row=1, column=col + 2, value=f"月{m}·预测偏差率(%)")
        for tmp_c in [pred_c, act_c, dev_c]:
            tmp_c.font = bold; tmp_c.fill = header_fill; tmp_c.alignment = center
        header_3_map[m] = (col, col + 1, col + 2)
        col += 3
    for idx, r in enumerate(rows, start=1):
        ws3.cell(row=idx + 1, column=1, value=idx).alignment = center
        for m in range(1, total_months + 1):
            pc, ac, dc = header_3_map[m]
            md = r["by_month"].get(m)
            if md:
                pred = md["forecast_demand"]
                actual = md["actual_demand"]
                pred_num = round(pred) if pred is not None else 0
                ws3.cell(row=idx + 1, column=pc, value=pred if pred is not None else "未填写")
                ws3.cell(row=idx + 1, column=ac, value=round(actual))
                if actual and actual > 0:
                    dev_pct = (pred_num - actual) / actual * 100.0
                    cell = ws3.cell(row=idx + 1, column=dc, value=round(dev_pct, 2))
                    if abs(dev_pct) > 30:
                        from openpyxl.styles import PatternFill as PF2
                        cell.fill = PF2(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")
                else:
                    ws3.cell(row=idx + 1, column=dc, value="—")
            else:
                ws3.cell(row=idx + 1, column=pc, value="—")
                ws3.cell(row=idx + 1, column=ac, value="—")
                ws3.cell(row=idx + 1, column=dc, value="—")
    for c_idx in range(1, col):
        ws3.column_dimensions[get_column_letter(c_idx)].width = 14

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    from datetime import datetime
    from urllib.parse import quote
    fname_escaped = f"class_ranking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    fname_display = f"全班匿名排名_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    # RFC 6266：filename* 支持中文，同时提供 ASCII fallback
    headers = {
        "Content-Disposition": f"attachment; filename=\"{fname_escaped}\"; filename*=UTF-8''{quote(fname_display)}",
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


import os

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8005))
    uvicorn.run(app, host="0.0.0.0", port=port)
