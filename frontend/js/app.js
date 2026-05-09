// 云端部署地址
const API_BASE_URL = window.location.hostname.includes('github.io') || window.location.hostname.includes('vercel.app')
    ? 'https://supply-chain-game.onrender.com' 
    : 'http://localhost:8005';

let currentUserId = localStorage.getItem('userId') || null;
let currentUsername = localStorage.getItem('username') || '';
let currentRole = localStorage.getItem('role') || 'student';

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
            }
        } catch (error) {
            console.error('操作失败:', error);
            alert('操作失败，请确保后端已启动');
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
            await fetch(`${API_BASE_URL}/submit_decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(decisionData)
            });

            const settleRes = await fetch(`${API_BASE_URL}/settle_month/${currentUserId}`, {
                method: 'POST'
            });

            if (settleRes.ok) {
                window.location.href = 'report.html';
            } else {
                const err = await settleRes.json();
                alert('提交失败: ' + err.detail);
            }
        } catch (error) {
            console.error('提交失败:', error);
            alert('提交决策失败');
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
    if (document.getElementById('actualDemand')) {
        loadReport();
    } else if (document.getElementById('currentCash')) {
        loadGameState();
    }

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
});
