# 云端系统架构、使用与维护指南

本文档介绍“供应链模拟游戏”云端版本的整体构成、上线方式、日常使用与维护要点。

## 云端项目网址

- 前端地址（GitHub Pages）：https://xiaomiykw.github.io/supply-chain-game/
- 后端服务地址（API）：https://supply-chain-game.onrender.com
- 后端接口文档 + 在线调试（Swagger UI）：https://supply-chain-game.onrender.com/docs#/
- Render 控制台（具体后端服务页）：https://dashboard.render.com/web/srv-d7v9sa3eo5us73egoe30
- Neon 控制台（具体数据库项目页）：https://console.neon.tech/app/projects/ancient-morning-17856711
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

### B. 删除已有用户（Neon SQL Editor 使用）

#### 1）先查一下有哪些用户（避免删错）
```sql
SELECT id, username, role FROM users ORDER BY id;
```

#### 2）删除单个指定用户（按用户名，最常用）
把 `student1` 换成你要删的用户名即可：
```sql
-- 先删该用户的游戏历史（game_state 有外键指向 users，必须先删）
DELETE FROM game_state
WHERE user_id = (SELECT id FROM users WHERE username = 'student1');

-- 再删该用户本身
DELETE FROM users
WHERE username = 'student1';
```

#### 3）删除单个指定用户（按 user_id）
把 `123` 换成对应用户的 `id`：
```sql
DELETE FROM game_state WHERE user_id = 123;
DELETE FROM users WHERE id = 123;
```

#### 4）删除所有学生账号（保留教师账号）
适合新学期开学清理往届学生：
```sql
-- 先删所有学生的历史数据
DELETE FROM game_state
WHERE user_id IN (SELECT id FROM users WHERE role = 'student');

-- 再删所有学生账号
DELETE FROM users WHERE role = 'student';
```

#### 5）删除所有账号（包含教师，慎用！）
删完之后教师账号也会消失，需要重新创建：
```sql
TRUNCATE TABLE game_state RESTART IDENTITY;
TRUNCATE TABLE users RESTART IDENTITY CASCADE;
```

> ⚠️ 不推荐直接用 `DROP TABLE users;`，会导致表结构丢失，后续还要重启后端重建表，容易出问题。

#### 6）只重置学生的游戏进度（保留学生账号，推荐每轮结束用）
只清空历史决策和成绩，账号仍可直接登录：
```sql
DELETE FROM game_state
WHERE user_id IN (SELECT id FROM users WHERE role = 'student');

-- 给所有学生重新插入第 1 月初始状态
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
CROSS JOIN (SELECT * FROM game_config ORDER BY id LIMIT 1) c
WHERE u.role = 'student';
```

## 后端 Swagger UI 使用手册（https://supply-chain-game.onrender.com/docs#/）

`https://supply-chain-game.onrender.com/docs#/` 是后端 FastAPI 自动生成的「接口说明书 + 在线调试工具（Swagger UI）」。

### 1）它是干什么的
- 看所有后端接口（GET/POST）、要传哪些参数、返回哪些字段。
- 直接在网页里点 `Try it out` → 填参数 → `Execute` 就能调用接口测试（不用 Postman / curl）。
- 常用于创建教师账号、查游戏状态、看配置、验证接口是否正常。

### 2）常用接口一览
| 接口 | 用途 |
|---|---|
| `POST /users/` | 创建账号（学生或教师）。body 示例：`{"username":"...","password":"...","role":"student"}` 或 `"teacher"` |
| `POST /login` | 登录，返回 `token`（前端存到 localStorage） |
| `GET /me` | 用 token 反查当前登录用户是谁、角色是什么（`X-Auth-Token` 请求头） |
| `GET /game_state/{user_id}` | 查看某学生当前处于第几月、现金/库存/决策情况 |
| `POST /submit_decision` | 学生提交本月决策（前端决策页调用） |
| `GET /report/{user_id}` | 查看某学生最新已结算报告（含累计利润） |
| `GET /history/{user_id}` | 查看某学生全部已结算月份历史（含逐月成本拆分） |
| `GET /teacher/ranking` | 教师：全班累计利润排行榜（需要教师 token） |
| `GET /teacher/students` | 教师：学生账号列表（需要教师 token） |
| `GET /teacher/student/{user_id}/history` | 教师：单个学生全部历史（需要教师 token） |
| `GET /game_config` | 查看当前全部游戏参数（售价/仓库/难度/固定成本/缺货惩罚等） |

### 3）怎么用（举例：创建教师账号）
1. 打开 `https://supply-chain-game.onrender.com/docs#/`。
2. 找到 **Users** 分组下的 `POST /users/`。
3. 点右边 **Try it out**。
4. 在 Request body 里粘贴（把密码换成强密码）：
   ```json
   {"username":"teacher1","password":"请设置强密码","role":"teacher"}
   ```
5. 点 **Execute**；返回 `200` 和用户对象即创建成功。
6. 随后到前端 `https://xiaomiykw.github.io/supply-chain-game/` 用这个账号登录即可进入教师端。

### 4）怎么调用需要鉴权的教师接口
1. 先在 `POST /login` 用教师账号登录，拿到返回的 `token`。
2. 点页面右上角 **Authorize**（小锁图标），在 value 里填入这个 `token` → 授权。
3. 再调用 `/teacher/*` 接口就会自动带上 `X-Auth-Token` 请求头。
4. 若出现 401：重新登录换 token；出现 403：当前账号不是 teacher 角色。

### 5）注意点
- 如果页面打开一直转圈/加载不出来：Render 免费实例可能休眠，等 10~30 秒刷新。
- 学生玩游戏不需要访问这个 `/docs` 页面，只用前端 Pages 地址即可。

## 让其他人也能管理 Render / Neon 项目（协作者共享）


### 1）Neon 项目加协作者
项目地址：https://console.neon.tech/app/projects/ancient-morning-17856711

1. 进入项目页面，找到 **Members** / **Invite**（或 Project settings → Members）。
2. 点 **Invite member / Add member**，输入对方的 Neon 登录邮箱。
3. 建议角色：
   - 技术维护：`Admin` 或 `Owner`（能改连接串、重置、备份）
   - 助教/老师：`Viewer`（只读，避免误删）
4. 对方收到邮箱邀请链接后确认即可加入。

### 2）Render 项目加协作者
项目地址：https://dashboard.render.com/web/srv-d7v9sa3eo5us73egoe30

Render 分「个人账号项目」和「Team 项目」：
- **个人账号下的项目**：不能直接加协作者，需要先升级/转移到 **Team**，再在 Team 里发邮箱邀请。
- **Team 下的项目**：进入 Team → **Team Members** → **Invite Member**，分配角色后发送。
- 免费版 Team 通常支持少数协作者，具体以 Render 当前政策为准。

### 3）GitHub 仓库加协作者（可选，方便一起改代码）
1. 进入 https://github.com/XiaomiYKW/supply-chain-game
2. **Settings → Collaborators and teams → Add people**
3. 输入对方 GitHub 用户名，给 `Write` 权限即可（尽量不要给 `Admin`）。

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
