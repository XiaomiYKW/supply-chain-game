// 自动识别环境：如果是本地访问则连本地，如果是云端访问则连 Render 后端
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8005'
    : 'https://supply-chain-game.onrender.com';

let currentUserId = localStorage.getItem('userId') || null;
let currentUsername = localStorage.getItem('username') || '';
let currentRole = localStorage.getItem('role') || 'student';
let currentAuthToken = localStorage.getItem('authToken') || null;
let latestState = null;
let currentGameConfig = null;

function authHeaders() {
    if (currentAuthToken) return { 'X-Auth-Token': currentAuthToken };
    return {};
}

function checkAuthAndRedirect(resp) {
    if (resp && resp.status === 401) {
        localStorage.removeItem('authToken');
        currentAuthToken = null;
        window.location.href = 'index.html';
        return true;
    }
    return false;
}

function logout() {
    localStorage.removeItem('userId');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
    localStorage.removeItem('authToken');
    currentUserId = null;
    window.location.href = 'index.html';
}

const loginForm = document.getElementById('loginForm');
if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;

        try {
            const errorEl = document.getElementById('loginError');
            if (errorEl) errorEl.classList.add('d-none');
            const btn = document.getElementById('loginBtn');
            const spinner = document.getElementById('loginSpinner');
            const btnText = document.getElementById('loginBtnText');
            if (btn) btn.disabled = true;
            if (spinner) spinner.classList.remove('d-none');
            if (btnText) btnText.innerText = '处理中...';

            let response = await fetch(`${API_BASE_URL}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            if (!response.ok) {
                const errorEl2 = document.getElementById('loginError');
                if (errorEl2) {
                    errorEl2.innerText = '登录失败：用户名或密码错误。请向教师索取账号。';
                    errorEl2.classList.remove('d-none');
                } else {
                    alert('登录失败：用户名或密码错误。请向教师索取账号。');
                }
                return;
            }

            const data = await response.json();

            if (data.id) {
                localStorage.setItem('userId', data.id);
                localStorage.setItem('username', data.username);
                localStorage.setItem('role', data.role || 'student');
                if (data.token) {
                    localStorage.setItem('authToken', data.token);
                } else {
                    localStorage.removeItem('authToken');
                }
                currentUserId = data.id;
                currentUsername = data.username;
                currentRole = data.role || 'student';
                currentAuthToken = data.token || null;

                if (currentRole === 'teacher') {
                    window.location.href = 'teacher.html';
                } else {
                    window.location.href = 'decision.html';
                }
            } else {
                const errorEl2 = document.getElementById('loginError');
                if (errorEl2) {
                    errorEl2.innerText = '登录失败：账号或服务状态异常。';
                    errorEl2.classList.remove('d-none');
                } else {
                    alert('登录失败：账号或服务状态异常。');
                }
            }
        } catch (error) {
            console.error('操作失败:', error);
            const errorEl = document.getElementById('loginError');
            if (errorEl) {
                errorEl.innerText = '操作失败，请检查后端是否可访问（云端服务可能在休眠，稍等后刷新重试）。';
                errorEl.classList.remove('d-none');
            } else {
                alert('操作失败，请确保后端已启动');
            }
        } finally {
            const btn = document.getElementById('loginBtn');
            const spinner = document.getElementById('loginSpinner');
            const btnText = document.getElementById('loginBtnText');
            if (btn) btn.disabled = false;
            if (spinner) spinner.classList.add('d-none');
            if (btnText) btnText.innerText = '登录';
        }
    });
}

const decisionForm = document.getElementById('decisionForm');
if (decisionForm) {
    decisionForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!currentUserId) {
            alert('请先登录');
            window.location.href = 'index.html';
            return;
        }

        const decisionData = {
            user_id: parseInt(currentUserId),
            forecast_demand: parseFloat(document.getElementById('forecastDemand').value),
            purchase_supplier_1: parseFloat(document.getElementById('purchase1').value || 0),
            purchase_supplier_2: parseFloat(document.getElementById('purchase2').value || 0),
            production_quantity: parseFloat(document.getElementById('productionQuantity').value)
        };

        try {
            const errorEl = document.getElementById('decisionError');
            if (errorEl) errorEl.classList.add('d-none');
            const btn = document.getElementById('submitDecisionBtn');
            const spinner = document.getElementById('decisionSpinner');
            const btnText = document.getElementById('submitDecisionText');
            if (btn) btn.disabled = true;
            if (spinner) spinner.classList.remove('d-none');
            if (btnText) btnText.innerText = '提交中...';

            const submitRes = await fetch(`${API_BASE_URL}/submit_decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify(decisionData)
            });
            if (checkAuthAndRedirect(submitRes)) return;

            const submitJson = await submitRes.json().catch(() => null);
            if (!submitRes.ok) {
                const detail = submitJson && submitJson.detail ? submitJson.detail : '提交失败';
                const errorEl2 = document.getElementById('decisionError');
                if (errorEl2) {
                    errorEl2.innerText = detail;
                    errorEl2.classList.remove('d-none');
                } else {
                    alert(detail);
                }
                return;
            }

            if (submitJson && submitJson.adjusted) {
                alert(
                    `现金不足，系统已自动调整采购量。\n` +
                    `供应商1: ${submitJson.accepted.purchase_supplier_1}\n` +
                    `供应商2: ${submitJson.accepted.purchase_supplier_2}`
                );
            }

            const settleRes = await fetch(`${API_BASE_URL}/settle_month/${currentUserId}`, {
                method: 'POST',
                headers: authHeaders()
            });
            if (checkAuthAndRedirect(settleRes)) return;

            if (settleRes.ok) {
                window.location.href = 'report.html';
            } else {
                const err = await settleRes.json();
                const msg = '结算失败: ' + (err && err.detail ? err.detail : '请稍后重试');
                const errorEl2 = document.getElementById('decisionError');
                if (errorEl2) {
                    errorEl2.innerText = msg;
                    errorEl2.classList.remove('d-none');
                } else {
                    alert(msg);
                }
            }
        } catch (error) {
            console.error('提交失败:', error);
            const errorEl = document.getElementById('decisionError');
            if (errorEl) {
                errorEl.innerText = '提交失败，请检查网络或后端状态后重试。';
                errorEl.classList.remove('d-none');
            } else {
                alert('提交决策失败');
            }
        } finally {
            const btn = document.getElementById('submitDecisionBtn');
            const spinner = document.getElementById('decisionSpinner');
            const btnText = document.getElementById('submitDecisionText');
            if (btn) btn.disabled = false;
            if (spinner) spinner.classList.add('d-none');
            if (btnText) btnText.innerText = '提交并结算';
        }
    });
}

async function loadGameConfig(month) {
    try {
        const url = month ? `${API_BASE_URL}/game-config?month=${month}` : `${API_BASE_URL}/game-config`;
        const r = await fetch(url, { method: 'GET', headers: authHeaders() });
        if (checkAuthAndRedirect(r)) return;
        if (!r.ok) return;
        currentGameConfig = await r.json();
        return currentGameConfig;
    } catch (err) {
        console.error('加载游戏参数失败:', err);
        return null;
    }
}

function renderGameConfigOnDecision(cfg, state) {
    if (!cfg) return;
    const el = (id) => document.getElementById(id);

    const setText = (id, val) => { const e = el(id); if (e) e.innerText = val; };

    setText('supplier1Price', `¥${Number(cfg.supplier1_price || 0).toLocaleString()}/个`);
    const lt1 = Number(cfg.supplier1_lead_time ?? 1);
    setText('supplier1LeadTime', `交期 ${lt1} 月`);
    const s1Hint = el('supplier1Hint'); if (s1Hint) s1Hint.innerText = lt1 === 0 ? '当月到货可用于生产' : `${lt1} 个月后到货`;
    const p1Label = el('purchase1Label'); if (p1Label) p1Label.innerText = lt1 === 0 ? `供应商1采购（当月到货）` : `供应商1采购（${lt1}月后到货）`;
    const p1Help = el('purchase1Help'); if (p1Help) p1Help.innerText = lt1 === 0 ? '适合当月到货，可用于本月生产。' : '适合做计划性补货。';

    setText('supplier2Price', `¥${Number(cfg.supplier2_price || 0).toLocaleString()}/个`);
    const lt2 = Number(cfg.supplier2_lead_time ?? 0);
    setText('supplier2LeadTime', lt2 === 0 ? '当月到货' : `交期 ${lt2} 月`);
    const s2Hint = el('supplier2Hint'); if (s2Hint) s2Hint.innerText = lt2 === 0 ? '当月到货可用于生产' : `${lt2} 个月后到货`;
    const p2Label = el('purchase2Label'); if (p2Label) p2Label.innerText = lt2 === 0 ? '供应商2采购（当月到货）' : `供应商2采购（${lt2}月后到货）`;

    setText('sellingPrice', `¥${Number(cfg.selling_price || 0).toLocaleString()}/个`);
    setText('factoryCapacity', `产能 ${Number(cfg.factory_capacity || 0).toLocaleString()} 个/月`);

    setText('rawHoldingCost', `¥${Number(cfg.raw_holding_cost || 0).toLocaleString()}/个/月`);
    setText('fgHoldingCost', `¥${Number(cfg.fg_holding_cost || 0).toLocaleString()}/个/月`);
    setText('rawOverflowCost', `¥${Number(cfg.raw_overflow_cost || 0).toLocaleString()}/个/月`);
    setText('fgOverflowCost', `¥${Number(cfg.fg_overflow_cost || 0).toLocaleString()}/个/月`);
    setText('fixedCostPerMonth', `¥${Number(cfg.fixed_cost_per_month || 0).toLocaleString()}/月`);
    setText('stockoutPenalty', `¥${Number(cfg.stockout_penalty_per_unit || 0).toLocaleString()}/缺货`);
    const rate = Number(cfg.negative_cash_interest_rate || 0) * 100;
    setText('negativeCashInterest', `${rate.toFixed(2)}%/月`);
    const low = Number(cfg.demand_variation_low || 0);
    const high = Number(cfg.demand_variation_high || 0);
    setText('demandRange', `${low.toFixed(2)}x ~ ${high.toFixed(2)}x`);

    // ============ 本轮新增：需求模式 Banner + 本月基准提示 / 封盘 Banner ============
    const mode = (cfg.demand_mode || 'curve_preset').toLowerCase();
    const totalMonths = Number(cfg.game_total_months || 12);
    const curMonth = state ? Number(state.month || 1) : 1;
    const banner = el('demandModeBanner');
    const forecastHint = el('forecastDemandHint');
    const predSub = el('demandPredSub');
    if (banner) {
        banner.classList.remove('d-none', 'alert-info', 'alert-success', 'alert-primary', 'alert-warning');
        // 默认 banner：curve_preset 或 excel_import —— 教师预设模式，不泄露具体数值
        banner.classList.add('alert-primary');
        const suffix = mode === 'excel_import' ? '（Excel导入）' : '（曲线预设）';
        banner.innerHTML = `<b>🎯 当前模式：教师预设需求${suffix} · 全班同卷对比</b>。教师已在课堂公布本月需求曲线 / 基准表，请根据老师课上给的参数、结合你自己的判断，填写下方「需求预测」（仅你的策略记录，不影响系统实际需求）。实际需求由「教师预设基准 × 固定波动」生成，<u>全班同月完全一致</u>，报告页可对比「你预测 vs 全班实际」。`;
        if (forecastHint) forecastHint.innerText = '仅记录你自己的主观预测；系统实际需求由教师课前发布的曲线/表格决定，全班同月一致。';
        if (predSub) predSub.innerText = '(你的策略记录 · 实际需求由教师公布)';
    }
    // 顶部「第X月 / 共Y月」提示
    const userInfo = el('userInfo');
    if (userInfo && state) {
        userInfo.innerText = `学生: ${currentUsername} | 第 ${state.month} 月 / 共 ${totalMonths} 月`;
    }
    // 封盘 Banner + 禁用表单
    const finishedBanner = el('finishedBanner');
    const decisionSubmitBtn = el('submitDecisionBtn');
    const decisionForm = document.getElementById('decisionForm');
    const gameFinished = curMonth >= totalMonths && state && state.is_settled;
    if (finishedBanner) {
        if (gameFinished) {
            finishedBanner.classList.remove('d-none');
            el('finishedTotalMonths').innerText = totalMonths;
            if (decisionForm) [...decisionForm.querySelectorAll('input,button')].forEach(n => n.setAttribute('disabled','disabled'));
            if (decisionSubmitBtn) { decisionSubmitBtn.classList.remove('btn-success'); decisionSubmitBtn.classList.add('btn-secondary'); decisionSubmitBtn.querySelector('#submitDecisionText').innerText = '游戏已结束'; }
        } else {
            finishedBanner.classList.add('d-none');
        }
    }
    // 决策页 Hint：显示是否为最后一月
    const hintEl = el('decisionHint');
    if (hintEl && state) {
        if (curMonth >= totalMonths) hintEl.innerText = `最后一月（共${totalMonths}月），结算后游戏封盘`;
        else hintEl.innerText = `第 ${curMonth}/${totalMonths} 月 · 提交后自动结算并生成下月`;
    }

    if (state) {
        const rawStock = Number(state.raw_material_stock || 0);
        const rawCap = Number(cfg.raw_warehouse_capacity || 0);
        const rawCapEl = el('rawCapacity');
        if (rawCapEl) rawCapEl.innerText = rawCap > 0 ? `当前 ${rawStock.toLocaleString()} / 容量 ${rawCap.toLocaleString()}` : `当前 ${rawStock.toLocaleString()}`;
        const fgStock = Number(state.finished_goods_stock || 0);
        const fgCap = Number(cfg.fg_warehouse_capacity || 0);
        const fgCapEl = el('fgCapacity');
        if (fgCapEl) fgCapEl.innerText = fgCap > 0 ? `当前 ${fgStock.toLocaleString()} / 容量 ${fgCap.toLocaleString()}` : `当前 ${fgStock.toLocaleString()}`;
    }
}

async function loadGameState() {
    if (!currentUserId) return;

    try {
        const firstResp = await fetch(`${API_BASE_URL}/game_state/${currentUserId}`, { method: 'GET', headers: authHeaders() });
        if (checkAuthAndRedirect(firstResp)) return;
        if (firstResp.status === 404) {
            alert('当前游戏已结束所有月份，请联系教师重置');
            return;
        }

        const state = await firstResp.json();
        latestState = state;

        // 并发拉 config，带 month 获取本月基准
        const cfg = await loadGameConfig(state.month);
        renderGameConfigOnDecision(cfg, state);

        const userInfo = document.getElementById('userInfo');
        if (userInfo && !document.getElementById('currentCash')) {
            const totalMonths = Number(cfg?.game_total_months || 12);
            userInfo.innerText = `学生: ${currentUsername} | 第 ${state.month} 月 / 共 ${totalMonths} 月`;
        }

        if (document.getElementById('currentCash')) {
            document.getElementById('currentCash').innerText = `¥${state.cash.toLocaleString()}`;
            document.getElementById('rawStock').innerText = state.raw_material_stock;
            document.getElementById('fgStock').innerText = state.finished_goods_stock;
        }

    } catch (error) {
        console.error('加载状态失败:', error);
    }
}

async function loadReport() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`${API_BASE_URL}/report/${currentUserId}`, { method: 'GET', headers: authHeaders() });
        if (checkAuthAndRedirect(response)) return;
        if (!response.ok) throw new Error('No report found');
        const state = await response.json();

        if (document.getElementById('actualDemand')) {
            document.getElementById('reportMonth').innerText = state.month;
            document.getElementById('actualDemand').innerText = Math.round(state.actual_demand || 0).toLocaleString();
            const fEl = document.getElementById('forecastDemand');
            if (fEl) fEl.innerText = Math.round(state.forecast_demand || 0).toLocaleString();
            const devEl = document.getElementById('forecastDeviation');
            const devNote = document.getElementById('forecastDeviationNote');
            const card = document.getElementById('forecastCompareCard');
            const fc = Math.round(state.forecast_demand || 0);
            const ad = Math.round(state.actual_demand || 0);
            if (devEl && ad > 0) {
                const pct = ((fc - ad) / ad) * 100;  // 正=预测过高，负=预测不足
                devEl.innerText = (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
                if (Math.abs(pct) <= 10) { devEl.className = 'h4 mb-0 kpi text-success'; if (card) { card.classList.add('border-success'); card.classList.remove('border-danger','border-warning'); }
                    if (devNote) devNote.innerText = '✅ 预测优秀，偏差在 ±10% 以内'; }
                else if (Math.abs(pct) <= 25) { devEl.className = 'h4 mb-0 kpi text-warning'; if (card) { card.classList.add('border-warning'); card.classList.remove('border-danger','border-success'); }
                    if (devNote) devNote.innerText = '⚠️ 预测中等偏差（' + (pct>0?'生产过多占用资金':'库存不足可能缺货') + '）'; }
                else { devEl.className = 'h4 mb-0 kpi text-danger'; if (card) { card.classList.add('border-danger'); card.classList.remove('border-success','border-warning'); }
                    if (devNote) devNote.innerText = '❌ 预测大幅偏离（' + (pct>0?'严重超产，库存积压':'预测太低，严重缺货') + '），下月请结合教师给的基准区间调整'; }
            } else if (devEl) { devEl.innerText = '-'; if (devNote) devNote.innerText = '无数据'; }
            const actualSalesEl = document.getElementById('actualSales'); if (actualSalesEl) actualSalesEl.innerText = state.actual_sales || '-';
            document.getElementById('revenue').innerText = `¥${(state.revenue || 0).toLocaleString()}`;
            document.getElementById('totalCost').innerText = `¥${(state.total_cost || 0).toLocaleString()}`;
            const purchaseCostEl = document.getElementById('purchaseCost');
            if (purchaseCostEl) purchaseCostEl.innerText = `¥${(state.purchase_cost || 0).toLocaleString()}`;
            const holdingCostEl = document.getElementById('holdingCost');
            if (holdingCostEl) holdingCostEl.innerText = `¥${(state.holding_cost || 0).toLocaleString()}`;
            const overflowCostEl = document.getElementById('overflowCost');
            if (overflowCostEl) overflowCostEl.innerText = `¥${(state.overflow_cost || 0).toLocaleString()}`;
            const fixedCostEl = document.getElementById('fixedCost');
            if (fixedCostEl) fixedCostEl.innerText = `¥${(state.fixed_cost || 0).toLocaleString()}`;
            const stockoutCostEl = document.getElementById('stockoutCost');
            if (stockoutCostEl) stockoutCostEl.innerText = `¥${(state.stockout_cost || 0).toLocaleString()}`;
            const interestCostEl = document.getElementById('interestCost');
            if (interestCostEl) interestCostEl.innerText = `¥${(state.interest_cost || 0).toLocaleString()}`;
            const profitEl = document.getElementById('profit');
            profitEl.innerText = `¥${(state.profit || 0).toLocaleString()}`;
            profitEl.className = state.profit >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger';
            const cumulativeEl = document.getElementById('cumulativeProfit');
            if (cumulativeEl) {
                cumulativeEl.innerText = `¥${(state.cumulative_profit || 0).toLocaleString()}`;
                cumulativeEl.className = (state.cumulative_profit || 0) >= 0 ? 'h4 mb-0 kpi fw-semibold text-success' : 'h4 mb-0 kpi fw-semibold text-danger';
            }
        }

        loadHistoryChart();

    } catch (error) {
        console.error('加载报告失败:', error);
    }
}

async function loadHistoryChart() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`${API_BASE_URL}/history/${currentUserId}`, { method: 'GET', headers: authHeaders() });
        if (checkAuthAndRedirect(response)) return;
        const data = await response.json();

        if (data.length === 0) return;

        const ctx = document.getElementById('historyChart');
        if (!ctx) return;

        if (window.historyChartInstance) {
            window.historyChartInstance.destroy();
        }

        const labels = data.map(s => `第 ${s.month} 月`);
        const profits = data.map(s => s.profit || 0);
        const revenues = data.map(s => s.revenue || 0);
        const costs = data.map(s => s.total_cost || 0);

        window.historyChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '利润',
                        data: profits,
                        borderColor: 'rgb(75, 192, 192)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        tension: 0.3,
                        fill: true
                    },
                    {
                        label: '收入',
                        data: revenues,
                        borderColor: 'rgb(54, 162, 235)',
                        tension: 0.3
                    },
                    {
                        label: '成本',
                        data: costs,
                        borderColor: 'rgb(255, 99, 132)',
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: '历史利润/收入/成本趋势'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: '金额 (¥)' }
                    }
                }
            }
        });

        const tbody = document.getElementById('monthlyBreakdownTable');
        if (tbody) {
            let running = 0;
            tbody.innerHTML = data.map(s => {
                const profit = Number(s.profit || 0);
                const cumulative = (s.cumulative_profit !== undefined && s.cumulative_profit !== null)
                    ? Number(s.cumulative_profit || 0)
                    : (running += profit);
                if (s.cumulative_profit === undefined || s.cumulative_profit === null) {
                    running = cumulative;
                }
                return `
                    <tr>
                        <td>第 ${s.month} 月</td>
                        <td class="kpi">¥${Number(s.revenue || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.purchase_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.holding_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.overflow_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.fixed_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.stockout_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.interest_cost || 0).toLocaleString()}</td>
                        <td class="kpi">¥${Number(s.total_cost || 0).toLocaleString()}</td>
                        <td class="kpi ${profit >= 0 ? 'text-success' : 'text-danger'}">¥${profit.toLocaleString()}</td>
                        <td class="kpi ${cumulative >= 0 ? 'text-success' : 'text-danger'}">¥${cumulative.toLocaleString()}</td>
                    </tr>
                `;
            }).join('');
        }

        loadRankingAndCompareChart(data);

    } catch (error) {
        console.error('加载历史图表失败:', error);
    }
}

async function loadRankingAndCompareChart(myHistoryData) {
    const compareCtx = document.getElementById('compareChart');
    const myRankEl = document.getElementById('myRank');
    if (!compareCtx && !myRankEl) return;
    if (!currentAuthToken) return;

    try {
        const res = await fetch(`${API_BASE_URL}/student/my-ranking`, {
            method: 'GET',
            headers: { 'X-Auth-Token': currentAuthToken }
        });
        if (!res.ok) return;
        const info = await res.json();
        const fp = info.first_place || {};
        const firstHistory = fp.history || [];

        if (myRankEl) {
            myRankEl.innerText = info.my_rank !== null && info.my_rank !== undefined ? `第 ${info.my_rank} 名` : '暂无数据';
        }
        const totalEl = document.getElementById('totalStudents');
        if (totalEl) totalEl.innerText = info.total_students || 0;
        const firstProfitEl = document.getElementById('firstTotalProfit');
        if (firstProfitEl) firstProfitEl.innerText = fp.total_profit !== undefined ? `¥${Number(fp.total_profit).toLocaleString()}` : '-';
        const firstMonthsEl = document.getElementById('firstMonthsPlayed');
        if (firstMonthsEl) firstMonthsEl.innerText = fp.months_played !== undefined ? fp.months_played : 0;

        const myCum = Number(info.my_total_profit || 0);
        const firstCum = Number(fp.total_profit || 0);
        const gap = firstCum - myCum;
        const gapEl = document.getElementById('profitGap');
        const gapDescEl = document.getElementById('profitGapDesc');
        if (gapEl) {
            if (info.my_rank === 1) {
                gapEl.innerText = '🎉 我就是第一名';
                gapEl.className = 'h3 kpi fw-semibold text-success';
            } else {
                gapEl.innerText = `¥${gap.toLocaleString()}`;
                gapEl.className = 'h3 kpi fw-semibold text-danger';
            }
        }
        if (gapDescEl) {
            if (info.my_rank === 1) {
                gapDescEl.innerText = '恭喜！保持优势继续加油';
            } else if (gap > 0) {
                gapDescEl.innerText = `落后第一名 ${gap.toLocaleString()} 元，加油追赶！`;
            } else if (gap < 0) {
                gapDescEl.innerText = `已超出第一名 ${Math.abs(gap).toLocaleString()} 元`;
            } else {
                gapDescEl.innerText = '与第一名持平';
            }
        }

        if (!compareCtx || !myHistoryData || myHistoryData.length === 0) return;

        if (window.compareChartInstance) {
            window.compareChartInstance.destroy();
        }

        const myMap = new Map();
        for (const s of myHistoryData) {
            const c = (s.cumulative_profit !== undefined && s.cumulative_profit !== null)
                ? Number(s.cumulative_profit)
                : Number(s.profit || 0);
            myMap.set(Number(s.month), c);
        }
        let runningMine = 0;
        for (const s of myHistoryData) {
            if (s.cumulative_profit === undefined || s.cumulative_profit === null) {
                runningMine += Number(s.profit || 0);
                myMap.set(Number(s.month), runningMine);
            }
        }

        const firstMap = new Map();
        for (const s of firstHistory) {
            firstMap.set(Number(s.month), Number(s.cumulative_profit || 0));
        }

        const allMonths = new Set([...myMap.keys(), ...firstMap.keys()]);
        const months = Array.from(allMonths).sort((a, b) => a - b);
        if (months.length === 0) return;

        const labels = months.map(m => `第 ${m} 月`);
        const myData = months.map(m => myMap.has(m) ? myMap.get(m) : null);
        const firstData = months.map(m => firstMap.has(m) ? firstMap.get(m) : null);

        window.compareChartInstance = new Chart(compareCtx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '我的累计利润',
                        data: myData,
                        borderColor: 'rgb(54, 162, 235)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        tension: 0.3,
                        fill: true,
                        spanGaps: false,
                        pointRadius: 3
                    },
                    {
                        label: fp.display_name || '当前第一名（匿名）',
                        data: firstData,
                        borderColor: 'rgb(234, 179, 8)',
                        backgroundColor: 'rgba(234, 179, 8, 0.1)',
                        borderDash: [6, 3],
                        tension: 0.3,
                        fill: false,
                        spanGaps: false,
                        pointRadius: 3
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    title: {
                        display: true,
                        text: '我 vs 当前第一名 累计利润对比'
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                const val = ctx.parsed.y;
                                if (val === null || val === undefined) return ctx.dataset.label + ': 暂无数据';
                                return ctx.dataset.label + ': ¥' + Number(val).toLocaleString();
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        title: { display: true, text: '累计利润 (¥)' }
                    }
                }
            }
        });

    } catch (err) {
        console.error('加载排名与对比图失败:', err);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const apiBaseRow = document.getElementById('apiBaseRow');
    if (apiBaseRow) apiBaseRow.remove();

    const backendBadge = document.getElementById('backendStatusBadge');
    if (backendBadge) {
        fetch(`${API_BASE_URL}/`, { method: 'GET' })
            .then(r => {
                if (!backendBadge) return;
                if (r.ok) {
                    backendBadge.className = 'badge rounded-pill text-bg-success';
                    backendBadge.innerText = '后端正常';
                } else {
                    backendBadge.className = 'badge rounded-pill text-bg-danger';
                    backendBadge.innerText = '后端不可用';
                }
            })
            .catch(() => {
                backendBadge.className = 'badge rounded-pill text-bg-danger';
                backendBadge.innerText = '后端不可用';
            });
    }

    if (document.getElementById('actualDemand')) {
        loadReport();
    } else if (document.getElementById('currentCash')) {
        loadGameState();
    }

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    const quickSafeBtn = document.getElementById('quickSafeBtn');
    const quickConservativeBtn = document.getElementById('quickConservativeBtn');
    const quickAggressiveBtn = document.getElementById('quickAggressiveBtn');
    if (quickSafeBtn || quickConservativeBtn || quickAggressiveBtn) {
        const fill = (mode) => {
            const raw = latestState ? Number(latestState.raw_material_stock || 0) : 0;
            const fg = latestState ? Number(latestState.finished_goods_stock || 0) : 0;

            let forecast = 400;
            let production = 300;
            let p1 = 400;
            let p2 = 0;

            if (mode === 'conservative') {
                forecast = Math.max(200, Math.round(fg * 0.8));
                production = Math.min(raw, 200);
                p1 = 200;
                p2 = 0;
            } else if (mode === 'aggressive') {
                forecast = Math.max(500, Math.round(fg + 300));
                production = Math.min(raw, 500);
                p1 = 600;
                p2 = 100;
            } else {
                forecast = Math.max(300, Math.round(fg + 200));
                production = Math.min(raw, 400);
                p1 = 500;
                p2 = 0;
            }

            const fd = document.getElementById('forecastDemand');
            const pq = document.getElementById('productionQuantity');
            const pp1 = document.getElementById('purchase1');
            const pp2 = document.getElementById('purchase2');
            if (fd) fd.value = String(Math.max(0, Math.round(forecast)));
            if (pq) pq.value = String(Math.max(0, Math.round(production)));
            if (pp1) pp1.value = String(Math.max(0, Math.round(p1)));
            if (pp2) pp2.value = String(Math.max(0, Math.round(p2)));
        };
        quickSafeBtn?.addEventListener('click', () => fill('safe'));
        quickConservativeBtn?.addEventListener('click', () => fill('conservative'));
        quickAggressiveBtn?.addEventListener('click', () => fill('aggressive'));
    }
});
