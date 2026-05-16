from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum
from database import Base

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
    month = Column(Integer)  # 1-24

    # Financial and Inventory data
    cash = Column(Float)                    # 月初现金
    raw_material_stock = Column(Float)      # 月初原材料库存
    finished_goods_stock = Column(Float)    # 月初成品库存
    
    # User decisions
    forecast_demand = Column(Float)         # 用户预测的需求
    purchase_supplier_1 = Column(Float)     # 向供应商1采购数量
    purchase_supplier_2 = Column(Float)     # 向供应商2采购数量
    production_quantity = Column(Float)     # 本月生产数量
    
    # Results (calculated at month end)
    actual_demand = Column(Float)           # 系统生成的实际需求
    actual_sales = Column(Float)            # 实际销售 = min(成品库存, 实际需求)
    revenue = Column(Float)                 # 收入
    total_cost = Column(Float)              # 总成本
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
    initial_cash = Column(Float)
    initial_raw_stock = Column(Float)
    initial_fg_stock = Column(Float)
