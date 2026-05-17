# 云端系统架构、使用与维护指南

本文档介绍“供应链模拟游戏”云端版本的整体构成、上线方式、日常使用与维护要点。

## 云端项目网址

- 前端地址（GitHub Pages）：https://xiaomiykw.github.io/supply-chain-game/
- 后端服务地址（API）：https://supply-chain-game.onrender.com
- Render 控制台（项目/服务管理）：https://dashboard.render.com/
- Neon 控制台（项目管理）：https://console.neon.tech/app/projects
- GitHub 仓库：https://github.com/XiaomiYKW/supply-chain-game

## 1. 云端系统由哪些部分构成

### 1.1 代码仓库（GitHub）
- 作用：保存前端与后端代码；作为 Render 自动部署的来源；作为 Pages 发布静态站点的来源。
- 分支：通常使用 `main` 作为发布分支。

### 1.2 前端（GitHub Pages：静态网站）
- 作用：对外提供 `index.html/decision.html/report.html/teacher.html` 等页面。
- 特点：纯静态文件（HTML/JS/CSS），不运行服务器逻辑。
- 与后端交互：通过浏览器向后端 API 发起 HTTP 请求。

### 1.3 后端（Render：FastAPI 服务）
- 作用：提供 API（登录、提交决策、结算、报告、教师统计等）；连接数据库；执行结算逻辑。
- 关键点：
  - Render 免费实例可能休眠；首次访问可能需要等待唤醒。
  - 后端启动时会自动建表、并尝试为旧库补齐新增字段（schema 补列）。

### 1.4 数据库（Neon：PostgreSQL）
- 作用：保存 `users`、`game_state`、`game_config` 等数据；实现多账号历史留存与隔离。
- 与后端关系：后端通过 `DATABASE_URL` 连接 Neon；所有读写都由后端完成。

## 2. 云端访问与使用方式

### 2.1 学生端使用
1. 通过 GitHub Pages 打开前端站点：`https://xiaomiykw.github.io/supply-chain-game/` 。
2. 输入用户名密码登录。
3. 进入决策页提交本月决策，系统自动结算并跳转报告页。
4. 在报告页查看：收入、成本拆分、利润、累计利润、趋势图与月度明细表。

### 2.2 教师端使用
1. 访问 `https://supply-chain-game.onrender.com/docs` 。
2. 找到 POST /users/ ，点击 Try it out 。
3. 输入 `{"username": "teacher1", "password": "请设置强密码", "role": "teacher"}` 并执行创建教师账号。
4. 通过 GitHub Pages 打开前端站点：`https://xiaomiykw.github.io/supply-chain-game/` 。
5. 教师端会通过 `/me` 校验 token 与角色；非教师无法进入教师端页面。


## 3. 云端部署与更新（发布流程）
1. 本地修改代码并提交到 GitHub：`git add` → `git commit` → `git push origin main`
2. Render 自动拉取最新提交并重新部署（开启 Auto Deploy 时）。
3. 前端走 GitHub Pages：Pages 来源为 `main` 分支（root）时，push 后会自动更新前端静态文件。

## 4. 云端配置清单（搭建时必看）

### 4.1 GitHub Pages 配置（前端发布）
1. GitHub 仓库 → Settings → Pages
2. Source 选择从 `main` 分支发布（通常为 root 目录）。
3. 访问 Pages 提供的站点链接，确认能打开 `index.html` 并能正常请求后端。

### 4.2 Render 配置（后端发布）
Render Web Service 建议配置要点：
- 代码来源：连接 GitHub 仓库 `XiaomiYKW/supply-chain-game`
- Root Directory：`backend`
- Build Command：`pip install -r requirements.txt`
- Start Command：`uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment Variables：
  - `DATABASE_URL`：Neon 提供的 Postgres 连接串（不要提交到仓库）
  - `PORT`：Render 会自动注入，一般无需手动设置

### 4.3 Neon 配置（数据库）
- 在 Neon 控制台创建项目与数据库，获取连接串（包含用户名、密码、host、db）。
- 将连接串填入 Render 的 `DATABASE_URL` 环境变量。
- 注意：连接账号需要有建表/改表权限（用于首次建表与补列）。

## 5. 常见运维操作（发布后日常维护）

### 5.1 Render 查看服务是否正常
1. Render 控制台 → 进入服务 → 看 Deploy 状态与 Logs。
2. 访问后端根路径 `/`（例如 `https://supply-chain-game.onrender.com`）应返回欢迎信息。

### 5.2 Render 触发重新部署
- Auto Deploy 开启：push 到 GitHub 后自动部署。
- Auto Deploy 关闭：Render 控制台手动点 “Deploy latest commit”。

### 5.3 数据库变更生效（自动建表/补列）
- 更新代码后如新增字段：Render 重启/重新部署会触发后端启动逻辑，自动建表并对旧库补列。
- 若日志出现 ALTER TABLE 失败：通常是权限不足或表不存在，先确认 Neon 连接账号权限与 `DATABASE_URL` 是否正确。

### 5.4 新增/管理账号
- 通过前端登录：
  - 若账号不存在会自动注册为学生（当前前端逻辑）。
- 通过后端接口：
  - 使用 `POST /users/` 创建学生/教师账号。

### 5.5 数据备份/导出（建议）
- 课程关键节点（开课前/期中/期末）建议在 Neon 控制台对数据做一次导出或备份（至少包含 `users`、`game_state`、`game_config`）。
- 若需要“保留成绩但重开新一轮”，建议备份后再执行重置 SQL。

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

不建议长期使用：
- `DROP TABLE game_state;`（会导致后端查询报错；需要重启后端让表自动重建）

## 6. 故障排查清单（最常见问题）

### 6.1 前端提示“操作失败/后端不可用”
排查顺序：
1. Render 是否休眠：等待 10~30 秒再刷新。
2. 后端根路径 `/` 是否能访问。
3. 前端请求的后端地址是否正确（生产环境应指向 Render URL）。
4. CORS 是否允许（本项目已放开 `*`）。

### 6.2 教师端无法加载/403/401
- 先确认教师账号登录成功，并且浏览器 localStorage 里存在 `authToken`。
- 教师接口必须带 `X-Auth-Token`，且 token 对应账号角色为 `teacher`。
- 学生访问教师端页面会被强制跳回首页，这是预期行为。

### 6.3 数据库字段缺失导致报错
1. 确认 Render 已部署到最新代码并重启过（触发补列逻辑）。
2. 查看 Render Logs 中是否有 ALTER TABLE 相关错误（权限不足、表不存在等）。

## 7. 安全与维护建议

- 不要把数据库连接串（Neon `DATABASE_URL`）提交到仓库；只放在 Render 环境变量。
- 教师端权限只依赖 token + 角色校验；请妥善保管教师账号密码。
- token 会在每次登录时刷新；若教师端提示 401，通常重新登录即可。
- 课程结束后建议重置 `game_state`，保留 `users` 或按需要清理账号。
