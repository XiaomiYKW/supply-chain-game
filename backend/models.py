from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
import enum
from database import Base
from datetime import datetime


class UserRole(enum.Enum):
    STUDENT = "student"
    TEACHER = "teacher"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # student or teacher
    auth_token = Column(String, index=True, unique=True, nullable=True)

    game_states = relationship("GameState", back_populates="user")


class GameState(Base):
    __tablename__ = "game_state"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    month = Column(Integer)  # 1..game_total_months

    # Financial and Inventory data
    cash = Column(Float)                    # 月初现金
    raw_material_stock = Column(Float)      # 月初原材料库存
    finished_goods_stock = Column(Float)    # 月初成品库存

    # User decisions
    forecast_demand = Column(Float)         # 用户主观预测（仅记录/对比，不再参与actual_demand生成）
    purchase_supplier_1 = Column(Float)     # 向供应商1采购数量
    purchase_supplier_2 = Column(Float)     # 向供应商2采购数量
    production_quantity = Column(Float)     # 本月生产数量

    # Results (calculated at month end)
    actual_demand = Column(Float)           # 系统生成的实际需求（全班同月一致，seeded）
    actual_sales = Column(Float)            # 实际销售 = min(成品库存, 实际需求)
    revenue = Column(Float)                 # 收入
    total_cost = Column(Float)              # 总成本
    purchase_cost = Column(Float)           # 采购成本
    holding_cost = Column(Float)            # 库存持有成本
    overflow_cost = Column(Float)           # 超额成本
    fixed_cost = Column(Float)              # 固定成本
    stockout_cost = Column(Float)           # 缺货惩罚成本
    interest_cost = Column(Float)           # 负现金利息成本
    profit = Column(Float)                  # 本月利润

    is_submitted = Column(Boolean, default=False)  # 是否已提交决策
    is_settled = Column(Boolean, default=False)    # 是否已结算

    user = relationship("User", back_populates="game_states")


class GameConfig(Base):
    __tablename__ = "game_config"

    id = Column(Integer, primary_key=True, index=True)
    selling_price = Column(Float)
    supplier1_price = Column(Float)
    supplier1_lead_time = Column(Integer)
    supplier2_price = Column(Float)
    supplier2_lead_time = Column(Integer)
    factory_capacity = Column(Float)
    raw_holding_cost = Column(Float)
    fg_holding_cost = Column(Float)
    raw_warehouse_capacity = Column(Float)
    fg_warehouse_capacity = Column(Float)
    raw_overflow_cost = Column(Float)
    fg_overflow_cost = Column(Float)
    demand_variation_low = Column(Float)
    demand_variation_high = Column(Float)
    fixed_cost_per_month = Column(Float)
    stockout_penalty_per_unit = Column(Float)
    negative_cash_interest_rate = Column(Float)
    initial_cash = Column(Float)
    initial_raw_stock = Column(Float)
    initial_fg_stock = Column(Float)

    # ---- Demand mode & lifecycle (本次新增) ----
    # excel_import / curve_preset (二选一, 已彻底移除旧 student_forecast 模式)
    demand_mode = Column(String, default="curve_preset")
    # 总游戏月数，默认12个月，范围6-24可在教师端调
    game_total_months = Column(Integer, default=12)
    # 全局确定性随机种子：seed + month → 同月全班 actual_demand 100%一致
    demand_seed = Column(Integer, default=20240920)


class DemandPlan(Base):
    """每月基准需求量（全班同月共用一条）"""
    __tablename__ = "demand_plan"

    id = Column(Integer, primary_key=True, index=True)
    # 1..game_total_months，UNIQUE 保证每月只有一条基准
    month = Column(Integer, unique=True, index=True, nullable=False)
    # 教师设定/曲线生成的基准中枢（最终actual_demand = base_demand × seeded_variation）
    base_demand = Column(Float, nullable=False, default=400.0)
    # 数据来源：default / excel / curve
    source = Column(String, default="default")
    # curve 模式时记录曲线类型，便于回显；excel 模式为 null
    curve_type = Column(String, nullable=True)
    # curve 模式的参数 JSON，便于重算；excel 模式可记录导入文件名
    params_json = Column(Text, nullable=True)
    # 审计信息
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
