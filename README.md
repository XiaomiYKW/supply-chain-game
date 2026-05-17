# 供应链模拟游戏教学辅助系统

单机版本：这是一个专为供应链教学设计的模拟游戏系统，支持多用户并发操作、教师端实时排名监控以及经营趋势可视化。

## 系统特性

- **多用户并发**: 支持 30+ 账号同时在线，数据严格隔离。
- **核心逻辑模拟**: 包含需求波动、生产限制、两种供应商渠道（长周期/短周期）、库存持有成本等。
- **自动化结算**: 学生提交决策后自动进行月底结算并推导下月初始状态。
- **教师端看板**: 实时展示学生利润排行榜，并可深入查看每位学生的历史操作明细。
- **可视化分析**: 使用 Chart.js 展示经营过程中的利润、收入与成本趋势，并提供逐月“成本拆分 + 累计利润”明细表。
- **权限隔离**: 学生端无法进入教师端页面；教师接口需要 token 鉴权。

## 目录结构

- `backend/`: 基于 FastAPI + SQLAlchemy 的后端
  - `main.py`: API 入口与路由定义
  - `models.py`: 数据库 ORM 模型
  - `game_logic.py`: 核心结算算法与下月推导逻辑
  - `database.py`: 数据库连接配置 (SQLite/PostgreSQL)
- **前端文件 (根目录)**: 
  - `index.html`: 登录页面
  - `decision.html`: 学生决策录入页
  - `report.html`: 个人结算报告与趋势图
  - `teacher.html`: 教师管理后台（排名与详情）
  - `js/app.js`: 前端核心交互逻辑

## 快速开始

### 1. 后端环境配置
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8005
```

### 2. 前端访问
推荐使用 Python 的简易服务器以避免某些浏览器的本地文件访问限制：
```bash
# 在项目根目录运行
python -m http.server 8080
```
访问地址：`http://localhost:8080/index.html`

---

## 测试流程指南

### 第一步：创建测试账号
1. 访问后端自动生成的文档：`http://127.0.0.1:8005/docs`
2. 使用 `POST /users/` 接口创建两个账号：
   - **学生账号**: `{"username": "student1", "password": "123", "role": "student"}`
   - **教师账号**: `{"username": "teacher1", "password": "123", "role": "teacher"}`

### 第二步：学生操作测试
1. 打开 `http://localhost:8080`，以 `student1` 登录。
2. **第一月决策**: 在决策页输入预测(如 400)、生产(如 400)、供应商1采购(如 500)，提交。
3. **查看报告**: 观察随机生成的实际需求和本月利润，并查看底部趋势图。
4. **进入下月**: 点击“返回决策”，确认页面顶部显示为“第 2 月”，且现金和库存已根据结算结果更新。

### 第三步：教师监控测试
1. 使用 `teacher1` 账号登录。
2. **查看排行榜**: 确认 `student1` 的累计利润已出现在列表中。
3. **查看详情**: 点击“查看详情”，确认可以看到该学生每月的具体决策参数（预测、采购、生产量）和趋势图。
4. **权限验证**: 用学生账号访问 `teacher.html` 应自动跳回首页；直接调用 `/teacher/*` 接口会返回 401/403。

### 第四步：并发压力模拟
1. 使用不同浏览器或无痕窗口登录多个学生账号进行操作。
2. 确认各自的 `month` 推进互不干扰。

---

## 游戏核心逻辑说明

1. **实际需求**: `用户预测值 * 随机因子`，默认区间为 `(0.7 - 1.3)`（可在 `game_config` 调整）。
2. **供应商 1**: 价格 ¥40，前置期 1 月（本月订货，下月初到）。
3. **供应商 2**: 价格 ¥60，前置期 0 月（即买即到，用于补货）。
4. **生产**: 消耗原材料 1:1 产出成品，受限于工厂最大产能 (1000)。
5. **持有成本**: 成品持有费 (¥5/个) 高于原材料 (¥2/个)。
6. **成本拆分（报告可见）**: 采购成本 + 库存持有成本 + 超仓超额成本 + 固定成本 + 缺货惩罚 + 负现金利息。

---

## 经营约束与难度

### 1. 现金不足限制（采购会被限制）
- 在提交决策时，如果现金不足以支持采购，系统会自动下调采购量（优先满足供应商2，再满足供应商1）。
- 接口返回中会包含 `adjusted/requested/accepted` 字段，前端会弹窗提示实际采购量。

### 2. 仓库上限（新增参数）
- 原材料仓库容量：`raw_warehouse_capacity`（默认 2000）
- 成品仓库容量：`fg_warehouse_capacity`（默认 1500）

### 3. 超额成本（超过仓库上限的惩罚）
- 原材料超额成本：`raw_overflow_cost`（默认 10/单位/月）
- 成品超额成本：`fg_overflow_cost`（默认 20/单位/月）
- 超额成本按“月底库存”计算，并计入当月 `total_cost`，从而降低当月利润。

### 4. 固定成本 / 缺货惩罚 / 负现金利息（提高难度）
- 固定成本：`fixed_cost_per_month`（默认 3000/月）
- 缺货惩罚：`stockout_penalty_per_unit`（默认 10/单位）；缺货量 = `max(0, 实际需求 - 实际销售)`
- 负现金利息：`negative_cash_interest_rate`（默认 0.02/月）；利息 = `max(0, -月初现金) * 利率`

---

## 教师端访问控制
- 登录/注册接口会返回 `token`，前端会保存在 `localStorage.authToken`。
- 教师端页面加载时会调用 `/me` 校验 token + 角色；不是教师会跳回首页。
- 所有 `/teacher/*` 接口必须带请求头 `X-Auth-Token`，且对应账号角色为 `teacher` 才能访问。

---

## Neon 重置游戏（可选）

### A. 只重置游戏进度（保留账号）
1. 不要长期使用 `DROP TABLE game_state;`（会导致后端报表不存在）。如果误删了表，请先重启后端服务让表自动重建。
2. 清空历史并给每个学生重新插入第 1 月初始状态（在 Neon SQL Editor 运行）：
```sql
TRUNCATE TABLE game_state RESTART IDENTITY;

INSERT INTO game_state (
  user_id, month,
  cash, raw_material_stock, finished_goods_stock,
  is_submitted, is_settled
)
SELECT
  u.id, 1,
  c.initial_cash, c.initial_raw_stock, c.initial_fg_stock,
  false, false
FROM users u
CROSS JOIN (
  SELECT * FROM game_config ORDER BY id LIMIT 1
) c
WHERE u.role = 'student';
```
