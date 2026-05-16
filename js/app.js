// 自动识别环境：如果是本地访问则连本地，如果是云端访问则连 Render 后端
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8005'
    : 'https://supply-chain-game.onrender.com';

let currentUserId = localStorage.getItem('userId') || null;
let currentUsername = localStorage.getItem('username') || '';
let currentRole = localStorage.getItem('role') || 'student';
let latestState = null;

function logout() {
    localStorage.removeItem('userId');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
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

            if (response.status === 401) {
                response = await fetch(`${API_BASE_URL}/users/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password, role: 'student' })
                });
            }

            const data = await response.json();

            if (data.id) {
                localStorage.setItem('userId', data.id);
                localStorage.setItem('username', data.username);
                localStorage.setItem('role', data.role || 'student');
                currentUserId = data.id;
                currentUsername = data.username;
                currentRole = data.role || 'student';

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
            if (btnText) btnText.innerText = '登录 / 注册';
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
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(decisionData)
            });

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
                method: 'POST'
            });

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

async function loadGameState() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`${API_BASE_URL}/game_state/${currentUserId}`);
        if (response.status === 404) {
            alert('当前游戏已结束所有月份，请联系教师重置');
            return;
        }

        const state = await response.json();
        latestState = state;

        const userInfo = document.getElementById('userInfo');
        if (userInfo) {
            userInfo.innerText = `学生: ${currentUsername} | 第 ${state.month} 月`;
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
        const response = await fetch(`${API_BASE_URL}/report/${currentUserId}`);
        if (!response.ok) throw new Error('No report found');
        const state = await response.json();

        if (document.getElementById('actualDemand')) {
            document.getElementById('reportMonth').innerText = state.month;
            document.getElementById('actualDemand').innerText = state.actual_demand || '-';
            document.getElementById('actualSales').innerText = state.actual_sales || '-';
            document.getElementById('revenue').innerText = `¥${(state.revenue || 0).toLocaleString()}`;
            document.getElementById('totalCost').innerText = `¥${(state.total_cost || 0).toLocaleString()}`;
            const profitEl = document.getElementById('profit');
            profitEl.innerText = `¥${(state.profit || 0).toLocaleString()}`;
            profitEl.className = state.profit >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger';
        }

        loadHistoryChart();

    } catch (error) {
        console.error('加载报告失败:', error);
    }
}

async function loadHistoryChart() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`${API_BASE_URL}/history/${currentUserId}`);
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
    } catch (error) {
        console.error('加载历史图表失败:', error);
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
