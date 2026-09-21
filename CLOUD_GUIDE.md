# 云端系统架构、使用与维护指南

本文档面向「供应链模拟游戏」云端版本的**技术维护者 / 管理员**，讲解系统组成、部署上线、日常运维、故障排查的全流程。
普通教师/学生使用系统请直接读 `README.md`，无需本手册。

---

## 0. 云端访问地址（现有部署）

可直接使用（Render 免费实例首次访问可能休眠 10~30 秒）：

| 组件 | 链接 | 说明 |
|---|---|---|
| 前端（GitHub Pages） | https://xiaomiykw.github.io/supply-chain-game/ | 学生/教师登录入口（纯静态，免维护）|
| 后端 API（Render） | https://supply-chain-game.onrender.com | 所有 HTTP 请求的后端服务（FastAPI） |
| 接口文档 / 在线调试 | https://supply-chain-game.onrender.com/docs#/ | Swagger UI 在线直接调接口 |
| Render 后端控制台 | https://dashboard.render.com/web/srv-d7v9sa3eo5us73egoe30 | 看日志、重启、改环境变量（需账号） |
| Neon 数据库控制台 | https://console.neon.tech/app/projects/ancient-morning-17856711 | 备份、SQL Editor、重置数据（需账号）|
| GitHub 代码仓库 | https://github.com/XiaomiYKW/supply-chain-game | 发版 = push main 分支 |

---

## 1. 系统组成（4 块）

```
学生/教师浏览器  ──HTTPS──▶  GitHub Pages（静态 HTML/JS/CSS）
                              │
                              └──▶  Render（FastAPI 后端，端口 $PORT）
                                        │
                                        └──▶  Neon（PostgreSQL，持久化 DB）
代码源：GitHub（main 分支自动触发 Pages 发布 + Render 重部署）
```

| 组件 | 技术栈 | 作用 |
|---|---|---|
| ① GitHub Pages | 纯静态托管 | 对外提供 `index/decision/report/teacher 4 个 HTML + js/app.js`；不跑后端 |
| ② Render Web Service | FastAPI + Uvicorn（Python） | 提供所有 API（登录、提交决策、结算、教师看板、重置、导出 xlsx） |
| ③ Neon Serverless PostgreSQL | 关系型数据库 | 存 `users / game_state / game_config / demand_plan / user_role` 5 张表；历史留存、多账号隔离 |
| ④ GitHub 仓库 | Git 版本管理 | 代码唯一来源；push main → Pages 与 Render 自动同步更新 |

### Render 免费实例注意
- 闲置 15 分钟会休眠 → 首次打开前端时请求可能卡 10~30 秒在等后端唤醒（正常）
- 唤醒后第一次响应后一切正常
- 建议开课前半小时由教师先打开一次前端让实例暖起来

---

## 2. 云端使用流程（最终用户）

### 2.1 学生端
1. 浏览器打开：`https://xiaomiykw.github.io/supply-chain-game/`
2. 输入教师给的账号密码登录
3. 决策页填本月 4 个数字 → 提交自动结算 → 报告页看排名/利润/趋势
4. 游戏玩完 12 个月（或教师设的 N 个月）自动封盘，报告页可看最终名次

### 2.2 教师端
1. 首次使用（建教师账号）：打开 `https://supply-chain-game.onrender.com/docs#/` → 找 `POST /users/` → Try it out → 填入：
   ```json
   {"username":"teacher1","password":"你设的强密码","role":"teacher"}
   ```
2. 回到 `https://xiaomiykw.github.io/supply-chain-game/` 用 teacher1 登录，自动识别角色进入教师端
3. 教师端 Tab1~5 功能详情见 `README.md` 第四章（批量导入学生 / 重置全班 / 导出排名 / 参数设置 / 需求模式）

> 教师常用的「全班重置」「匿名排名导出」「批量建号」**全部在教师前端页点按钮**，不用跑 SQL，避免手误。

---

## 3. 部署与更新（发布新代码）

发布流程完全自动化（main 分支 → GitHub Pages + Render 双自动部署）：

```bash
# 本地改完代码
git add .
git commit -m "改了什么"
git push origin main
```

- GitHub Pages：5 分钟内自动重发静态文件（Settings → Pages → Build and deployment → Source=Deploy from a branch，Branch=main / root）
- Render：Auto Deploy 默认开启 → 自动拉取 main 最新 commit → pip install -r backend/requirements.txt → uvicorn 启服务 → 看 Render 控制台 Deploy Logs 是否绿色成功

如果 Render Auto Deploy 关掉了，也可以进 Render 控制台对应服务 → 手动点 **Deploy latest commit**。

---

## 4. 首次从零搭建（新环境参考）

如果要换账号/换项目，按以下 3 步搭建：

### 4.1 GitHub + Pages（前端）
1. 新建 GitHub 仓库，把本项目根目录全部文件推送到 `main`
2. 仓库 → **Settings → Pages**
   - Source：`Deploy from a branch`
   - Branch：`main` / `/(root)`
3. 等 Action 跑完，访问 `https://<username>.github.io/<repo>/` 能打开登录页

### 4.2 Neon（PostgreSQL 数据库）
1. https://console.neon.tech 登录 → 新建 Project
   - Postgres version：选默认最新即可
   - Region：离目标学生近（Asia 新加坡一般对国内延迟可接受）
2. 建完后复制 **Connection string**（形如 `postgresql://user:pass@hostname/dbname?sslmode=require`），这是后续 Render 的 `DATABASE_URL` 环境变量

### 4.3 Render（后端 API）
1. https://dashboard.render.com → **New → Web Service**
2. 连接刚建的 GitHub 仓库（授权 Render 访问）
3. 关键配置：
   | 字段 | 值 |
   |---|---|
   | **Root Directory** | `backend`（后端代码不在根目录，必须填 `backend`！）|
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | **Instance Type** | 免费 Free / Starter 都行 |
   | **Region** | 跟 Neon 尽量同一个（都是新加坡/都是法兰克福，降低延迟）|
4. Environment Variables 添加 1 条：
   ```
   DATABASE_URL = <刚才 Neon 复制的完整连接串>
   ```
5. 点 Create Web Service，等部署日志出现 `Uvicorn running on http://0.0.0.0:10000` 就成功了
6. 验证：浏览器打开 Render 分配的 `https://xxx.onrender.com` 应返回欢迎 JSON

### 4.4 首次建教师账号
```
打开 https://<你的Render域名>/docs#/
POST /users/  →  Try it out  →
  body: {"username":"teacher1","password":"强密码","role":"teacher"}
  Execute → 200 OK
```
以后每次新建库都要跑一次，否则没有教师账号。

### 4.5 前端 js/app.js 里后端地址检查
确认 `js/app.js` 中生产环境请求的后端是你的 Render 域名（而不是本地 `http://127.0.0.1:8005`），一般写了 `API_BASE = window.location.hostname.includes('github.io') ? 'https://supply-chain-game.onrender.com' : 'http://127.0.0.1:8005'` 即可自动切换。

---

## 5. 日常运维操作

### 5.1 验证服务是否正常（定期检查）
1. **前端能打开？** 访问 Pages 地址看登录页
2. **后端活着？** 访问 Render 域名根路径 `/` 应返回 `{"message":"Supply Chain Game API"}`
3. **DB 连接正常？** Render Logs 搜 `ensure_schema completed` / `Connected` 无红色 Exception
4. **接口能鉴权？** Swagger 里先 `POST /login` 拿 token → Authorize 填上 → `GET /me` 返回 200 + teacher1

### 5.2 课前暖机（Render 免费实例）
- 开课前 30 分钟：教师自己先打开一次 `https://xiaomiykw.github.io/supply-chain-game/` 登录，Render 实例被唤醒不会学生上课时卡 30 秒

### 5.3 每轮结束重置全班（推荐用前端 UI，别手跑 SQL）
> 前端 `teacher.html` → Tab2「全班操作」→ 🔴 **重置全班游戏**（二次确认）就够了。
> 效果：删所有学生的 `game_state`，**不删**学生账号、不删 `game_config`、不删 `demand_plan`，然后每个学生自动重建「第1月初始状态」（现金/原料/成品 = GameConfig 里的初始值）。

只有 UI 按钮失效时才用下面的 Neon SQL Editor 兜底：

```sql
-- ========== 只重置进度（保留账号/配置/曲线）==========
DELETE FROM game_state
WHERE user_id IN (SELECT id FROM users WHERE role = 'student');

INSERT INTO game_state (user_id, month, cash, raw_material_stock, finished_goods_stock, is_submitted, is_settled)
SELECT u.id, 1, c.initial_cash, c.initial_raw_stock, c.initial_fg_stock, false, false
FROM users u
CROSS JOIN (SELECT * FROM game_config ORDER BY id LIMIT 1) c
WHERE u.role = 'student';
```

### 5.4 新学期开学：删往届学生（保留教师）
教师前端 Tab1 批量删，或 Neon SQL Editor 兜底：
```sql
-- 先删历史（有外键，不能先删 users）
DELETE FROM game_state
WHERE user_id IN (SELECT id FROM users WHERE role = 'student');
-- 再删账号
DELETE FROM users WHERE role = 'student';
```
之后回教师端 Tab1 用 Excel 批量导入新一届学生。

### 5.5 数据备份（关键节点必做）
**建议备份时间点：** 开学前 / 期中考试后 / 期末考试导出排名后

1. **Neon 控制台** → 选项目 → **Branches / Restore / Export**（Neon 自带 point-in-time restore 是最佳实践）
2. 或者用 pg_dump（本地装了 PostgreSQL 客户端）：
   ```bash
   pg_dump "postgresql://user:pass@host/dbname?sslmode=require" -F c -f backup_202XMMDD.dump
   ```
3. 不建议长期依赖 `DROP TABLE` / 删库重建，容易触发表结构不一致；有问题一般先 5.1 诊断。

---

## 6. FastAPI 接口速查（维护手册）

所有需要鉴权的接口，在 Swagger UI 里先 `POST /login` 拿 token → 点右上角小锁 **Authorize** → 粘贴 token 才能成功。

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| POST | `/users/` | 否 | 新建用户（student / teacher） |
| POST | `/login` | 否 | 登录拿 `token`（前端存在 localStorage，请求头 `X-Auth-Token`）|
| GET | `/me` | 是（任意角色） | 反查当前登录用户信息（含 role）|
| GET | `/game-config` | 是（教师读 / 学生读） | 读全部游戏参数（售价/仓库/难度/总月数/需求种子…）|
| PUT | `/teacher/game-config` | 是（仅教师） | 局部改游戏参数（支持只改 1 个，body 用哪个字段传哪个）|
| GET | `/teacher/demand-mode` | 是（仅教师） | 查当前需求模式（excel_import / curve_preset）+ 需求种子 |
| PUT | `/teacher/demand-mode` | 是（仅教师） | 切模式 + 改需求种子（`demand_mode` / `demand_seed`）|
| POST | `/teacher/reset_class` | 是（仅教师） | **前端按钮"重置全班"调用的接口**，推荐代替手动 SQL |
| GET | `/teacher/export_class_ranking` | 是（仅教师） | **前端按钮"导出匿名排名 Excel"**，返回 xlsx 的 `StreamingResponse`，文件名严格 RFC6266 编码 |
| GET | `/teacher/students` | 是（仅教师） | 列表：全班学生账号、进度、累计利润（Tab1 用）|
| GET | `/teacher/ranking` | 是（仅教师） | 排名：累计利润降序 + 已玩月数作为第二排序键（Tab5 用）|
| GET | `/teacher/demand-summary` | 是（仅教师） | 查 1~N 月每月基准需求（demand_plan 表，来自 Excel/曲线）|
| PUT | `/teacher/demand-plan/bulk` | 是（仅教师） | 批量写每月基准需求（Tab4 表格保存用）|
| POST | `/teacher/demand-plan/curve` | 是（仅教师） | 给曲线类型+总月数，后端生成每月基准需求（Tab4 生成并预览用）|
| POST | `/teacher/students/import` | 是（仅教师） | 上传 xlsx 批量创建学生账号（Tab1）|
| GET | `/game_state/{user_id}` | 是（学生只看自己 / 教师看任意） | 某学生当前处于第几月、现金/库存/已填决策 |
| POST | `/submit_decision` | 是（仅学生） | 提交本月 4 项决策 → 自动结算 → 返回 GameState |
| GET | `/report/{user_id}` | 是（学生只看自己 / 教师看任意） | 最近已结算月报告（含累计利润、成本拆分、forecast/production/supplier1/2 决策记录）|
| GET | `/history/{user_id}` | 是（学生只看自己 / 教师看任意） | 全部已结算月历史列表（画趋势图、月度明细表）|
| DELETE | `/teacher/students/{user_id}` | 是（仅教师） | 删除某学生账号 + 对应全部历史 |
| POST | `/teacher/students/{user_id}/reset` | 是（仅教师） | 重置单个学生回第 1 月（保留账号）|

### 鉴权规则（关键）
- 所有学生接口：`Depends(get_current_user)` + 校验 `role=student` 且 `user.id == path 里 user_id`（不能看别人）
- 所有 `/teacher/*` 接口：`Depends(get_current_teacher)` 强制 `role=teacher`
- 前端统一把 token 写在 `X-Auth-Token` 请求头；收到 HTTP 401 → 前端自动删 localStorage 并跳登录页（避免旧 token 死循环）

---

## 7. 数据库表结构（维护时参考）

| 表名 | 用途 | 关键字段 |
|---|---|---|
| `users` | 账号表 | `id / username / password_hash / role (student|teacher) / display_name` |
| `user_role` | 角色表 | `user_id / role`（通常与 users.role 同步，兼容多角色扩展）|
| `game_state` | 每月状态 + 决策 + 结算结果 | 每个学生每月 1 条：`user_id / month / is_submitted / is_settled`；决策：`forecast_demand / production_quantity / purchase_supplier_1 / purchase_supplier_2`；结算：`actual_demand / actual_sales / revenue / total_cost / profit / cumulative_profit / 各成本项…` |
| `game_config` | 全局单例配置表 | **22+ 参数全在这里**：价格、交期、产能、仓库容量、6 项成本/惩罚、初始值、`game_total_months`（总月数）、`demand_mode`、`demand_seed`、`demand_variation_low/high` |
| `demand_plan` | 每月基准需求（1-N 月） | `month / base_demand / source（excel_import / curve_xxx）`；全班统一，来自 Tab4 Excel 或曲线 |

### 自动建表 + Schema 补列（无需手跑 SQL）
- `main.py` 启动 → `ensure_schema()` 自动：
  1. `CREATE TABLE IF NOT EXISTS` 建 5 张表
  2. `PRAGMA table_info(xxx) / SELECT column_name FROM information_schema.columns`（分别适配 SQLite / PostgreSQL）查现有列
  3. 缺列就 `ALTER TABLE ADD COLUMN xxx` 补齐（`demand_mode`、`total_months`、`demand_seed`、`demand_plan` 表都是这么加的）
- **因此代码升级只需 push + Render 重启**，不会因为老库缺列崩。

---

## 8. 常见故障排查

| 现象 | 排查顺序 |
|---|---|
| 前端打开但登录一直「网络错误」 | ① Render 是否休眠（等 30s 刷）；② 看浏览器控制台 Network 登录请求返回啥（5xx / CORS / DNS）；③ 直接访问 `https://supply-chain-game.onrender.com/` 看通不通 |
| 登录成功但教师端学生列表空 / 排名 0 | ① localStorage 里 `authToken` 过期 → 退出重新登录；② 接口 401/403 → 看 Network 响应体（多半是学生 token 访问 teacher 接口或 token 过期）|
| Render 部署失败 | ① Build Log：requirements 版本不兼容 / pip 装不上（升级 setuptools/wheel）；② Start Log：`DATABASE_URL` 漏了或格式不对；③ Root Directory 忘了填 `backend` 导致找不到 main.py |
| 导出匿名排名 Excel 500 | ① Render 日志有没有 `openpyxl` ImportError（`pip install openpyxl` 并确认 requirements.txt 里有）；② StreamingResponse Content-Disposition 中文文件名 → 本项目用了 RFC 6266 双 header（ASCII fallback + filename*=UTF-8''%XX），浏览器一般没问题；特殊浏览器检查响应头 |
| 学生说全班同月实际需求不一样 | ① 查所有学生 `game_state where month=X` 的 `actual_demand` 是否完全一样；② 检查 `game_config.demand_seed` 是否有值（null 会每次随机，`ensure_schema` 已默认为 `12345`）；③ 已结算月份（is_settled=True）不会重算——**这是强约束**，一旦某学生月 X is_settled，任何情况下不能覆盖 |
| /teacher/reset_class 返回成功但学生还是老月份 | 接口逻辑：删所有 student 的 game_state → 对每个 student 重建 `month=1`；检查后端 `ensure_schema()` 里 `demand_plan` 表是否建对，否则 GET 404 不影响重置 |
| 决策提交后月数不推进 | ① 是否超过 `game_total_months`（封盘了不能提交），看 finishedBanner 是否出现；② 当月是否 `is_settled=True` 了重复提交；③ 看 Network `/submit_decision` 返回是否 200，有 error 前端会红字展示 |

---

## 9. 安全与维护建议

1. **密钥安全**
   - Neon `DATABASE_URL` 只存 Render 环境变量，**绝对不要 commit 进 git**
   - 教师账号不要用 `123` 这种弱密码（教学演示后应改）

2. **鉴权安全**
   - 所有接口 token 校验闭环：学生 6 个 + 教师 N 个接口全部带 `Depends`；测试时可以去掉某一个看是否立即 401
   - 学生越权访问别人 `user_id` 直接 403

3. **版本控制 & 回滚**
   - Render 控制台 → History 可一键回滚到上一个成功部署；出事最快恢复
   - Neon point-in-time restore 按时间回溯数据（比手跑 SQL 备份安全得多）

4. **定期备份**
   - 建议每学期结束：① 先前端导出匿名排名 Excel 归档成绩 ② Neon 备份一次分支 ③ 再重置全班准备下一轮

5. **禁用学生自注册（如需严格管理）**
   - 本项目当前 `POST /users/` 接口默认开放；如果要改成"只有教师能批量建号"，请在 main.py 里给该接口加 `Depends(get_current_teacher)`，并把前端 index.html 注册入口按钮隐藏即可

---

## 附录 A：Render 环境变量清单（最小可用）

| 变量名 | 必填 | 示例值 | 说明 |
|---|---|---|---|
| `DATABASE_URL` | ✅ 是 | `postgresql://xxx:yyy@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require` | Neon 给的完整连接串 |
| `PORT` | ❌ 否 | Render 自动注入（一般 10000） | 代码里写 `--port $PORT` 就不用管 |
| `PYTHON_VERSION` | ❌ 否 | `3.11.8` | Render 自动选；如果 `requirements` 装不上可以显式指定版本 |
| `SECRET_KEY` | ❌ 建议有 | 自己生成 32 位随机串 | JWT 签名密钥；留空会回退到代码里的默认，最好自己设 |

## 附录 B：协作权限管理（多管理员）

- **GitHub 仓库**：Settings → Collaborators → 加协作者给 Write 权限（技术维护）/ Read 权限（老师只读）
- **Render**：个人账号下项目不能直接加人；如果要多人管需要先把项目迁到 **Team**，再发邮箱邀请
- **Neon**：Project Settings → Members → 邀请：技术维护给 Admin，给老师/助教 Viewer（只读，避免手误删数据）
