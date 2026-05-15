"""
AgentOS Gateway — External HTTP Interface

Provides a web dashboard and REST API for the approval queue.
Humans can review and decide on pending approvals from any browser.

Usage:
    python gateway.py

Default: http://localhost:8080
Configure via .env: GATEWAY_HOST, GATEWAY_PORT, GATEWAY_SECRET
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import sqlite3
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config import settings
from database import init_db, DB_PATH
from approval.queue import (
    init_approval_queue,
    list_pending,
    list_history,
    get_item,
    submit_decision,
    get_pending_count,
    enqueue,
    calculate_risk,
)
from approval.webhook import notify


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_approval_queue()
    yield

app = FastAPI(
    title="AgentOS Gateway",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helper ───────────────────────────────────────────────────────────────

def _check_secret(x_agentos_secret: str = None):
    secret = getattr(settings, "gateway_secret", "")
    if secret and x_agentos_secret != secret:
        raise HTTPException(status_code=401, detail="Invalid secret")


# ── Models ────────────────────────────────────────────────────────────────────

class DecisionRequest(BaseModel):
    decision: str       # "approved" | "rejected"
    notes: str = ""
    decided_by: str = "human_via_gateway"


class EnqueueRequest(BaseModel):
    agent_id: str
    title: str
    description: str
    action_type: str
    action_payload: dict = {}


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/approvals/{agent_id}")
async def get_approvals(
    agent_id: str,
    status: str = "pending",
    limit: int = 50,
    x_agentos_secret: str = Header(default=None)
):
    _check_secret(x_agentos_secret)
    if status == "pending":
        items = list_pending(agent_id=agent_id, limit=limit)
    else:
        items = list_history(agent_id=agent_id, status=status, limit=limit)
    return {"agent_id": agent_id, "count": len(items), "items": items}


@app.get("/api/approvals/{agent_id}/{item_id}")
async def get_approval_detail(
    agent_id: str,
    item_id: str,
    x_agentos_secret: str = Header(default=None)
):
    _check_secret(x_agentos_secret)
    item = get_item(item_id=item_id, agent_id=agent_id)
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return item


@app.post("/api/approvals/{agent_id}/{item_id}/decide")
async def decide(
    agent_id: str,
    item_id: str,
    body: DecisionRequest,
    x_agentos_secret: str = Header(default=None)
):
    _check_secret(x_agentos_secret)
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    result = submit_decision(
        item_id=item_id,
        agent_id=agent_id,
        decision=body.decision,
        notes=body.notes,
        decided_by=body.decided_by
    )
    if not result:
        raise HTTPException(status_code=404, detail="Item not found or already decided")

    return {"success": True, "decision": body.decision, "item_id": item_id}


@app.post("/api/approvals/enqueue")
async def api_enqueue(
    body: EnqueueRequest,
    x_agentos_secret: str = Header(default=None)
):
    """External systems can enqueue approvals via this endpoint."""
    _check_secret(x_agentos_secret)
    risk_score, risk_level = calculate_risk(body.action_type, body.action_payload)
    item = enqueue(
        agent_id=body.agent_id,
        title=body.title,
        description=body.description,
        action_type=body.action_type,
        action_payload=body.action_payload,
        risk_score=risk_score,
        risk_level=risk_level,
        source="external_api"
    )
    notify(item)
    return {"success": True, "item": item}


@app.get("/api/stats/{agent_id}")
async def get_stats(
    agent_id: str,
    x_agentos_secret: str = Header(default=None)
):
    _check_secret(x_agentos_secret)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='pending'  THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected
            FROM approval_queue WHERE agent_id = ?
            """,
            (agent_id,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


# ── HTML Dashboard ────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgentOS — لوحة الموافقات</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .header { background: #1e293b; border-bottom: 1px solid #334155; padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; }
  .header h1 { font-size: 1.25rem; font-weight: 600; color: #f1f5f9; }
  .badge { background: #3b82f6; color: white; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
  .badge.red { background: #ef4444; }
  .container { max-width: 1000px; margin: 0 auto; padding: 2rem; }
  .controls { display: flex; gap: 1rem; margin-bottom: 2rem; align-items: center; flex-wrap: wrap; }
  .controls input, .controls select { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem 1rem; border-radius: 0.5rem; font-size: 0.9rem; }
  .controls button { background: #3b82f6; color: white; border: none; padding: 0.5rem 1.25rem; border-radius: 0.5rem; cursor: pointer; font-size: 0.9rem; }
  .controls button:hover { background: #2563eb; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1rem; transition: border-color 0.2s; }
  .card:hover { border-color: #475569; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 0.75rem; }
  .card-title { font-weight: 600; color: #f1f5f9; font-size: 1rem; }
  .card-meta { color: #94a3b8; font-size: 0.8rem; margin-top: 0.25rem; }
  .card-desc { color: #cbd5e1; font-size: 0.875rem; line-height: 1.6; margin-bottom: 1rem; }
  .risk-badge { padding: 0.2rem 0.7rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; white-space: nowrap; }
  .risk-approve { background: #7f1d1d; color: #fca5a5; }
  .risk-notify  { background: #78350f; color: #fcd34d; }
  .risk-auto    { background: #14532d; color: #86efac; }
  .actions { display: flex; gap: 0.75rem; flex-wrap: wrap; }
  .btn { padding: 0.4rem 1rem; border-radius: 0.4rem; border: none; cursor: pointer; font-size: 0.85rem; font-weight: 500; transition: opacity 0.2s; }
  .btn:hover { opacity: 0.85; }
  .btn-approve { background: #16a34a; color: white; }
  .btn-reject  { background: #dc2626; color: white; }
  .btn-detail  { background: #334155; color: #e2e8f0; }
  .empty { text-align: center; color: #475569; padding: 4rem 2rem; font-size: 1rem; }
  .stats { display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }
  .stat { background: #1e293b; border: 1px solid #334155; border-radius: 0.5rem; padding: 1rem 1.5rem; flex: 1; min-width: 120px; }
  .stat-value { font-size: 1.75rem; font-weight: 700; color: #f1f5f9; }
  .stat-label { color: #64748b; font-size: 0.8rem; margin-top: 0.25rem; }
  .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100; align-items: center; justify-content: center; }
  .modal.open { display: flex; }
  .modal-box { background: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; padding: 1.5rem; max-width: 500px; width: 90%; }
  .modal-box h3 { margin-bottom: 1rem; color: #f1f5f9; }
  .modal-box textarea { width: 100%; background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.75rem; border-radius: 0.5rem; font-size: 0.9rem; resize: vertical; min-height: 80px; margin-bottom: 1rem; }
  .modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; }
  .toast { position: fixed; bottom: 2rem; left: 50%; transform: translateX(-50%); background: #16a34a; color: white; padding: 0.75rem 1.5rem; border-radius: 0.5rem; font-size: 0.9rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 200; }
  .toast.show { opacity: 1; }
  .toast.error { background: #dc2626; }
  .tab-bar { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
  .tab { padding: 0.4rem 1rem; border-radius: 0.4rem; cursor: pointer; font-size: 0.85rem; color: #94a3b8; background: transparent; border: 1px solid transparent; }
  .tab.active { background: #334155; color: #f1f5f9; border-color: #475569; }
</style>
</head>
<body>

<div class="header">
  <h1>🧠 AgentOS</h1>
  <span>لوحة الموافقات</span>
  <span class="badge red" id="pending-badge">...</span>
</div>

<div class="container">
  <div class="controls">
    <input id="agent-input" placeholder="agent_id" value="default-agent" />
    <input id="secret-input" type="password" placeholder="Secret (اختياري)" />
    <button onclick="load()">تحميل</button>
  </div>

  <div class="stats">
    <div class="stat"><div class="stat-value" id="stat-pending">—</div><div class="stat-label">معلق</div></div>
    <div class="stat"><div class="stat-value" id="stat-approved">—</div><div class="stat-label">موافق عليه</div></div>
    <div class="stat"><div class="stat-value" id="stat-rejected">—</div><div class="stat-label">مرفوض</div></div>
    <div class="stat"><div class="stat-value" id="stat-total">—</div><div class="stat-label">الإجمالي</div></div>
  </div>

  <div class="tab-bar">
    <div class="tab active" onclick="switchTab('pending')">معلق</div>
    <div class="tab" onclick="switchTab('approved')">موافق عليه</div>
    <div class="tab" onclick="switchTab('rejected')">مرفوض</div>
  </div>

  <div id="list-container">
    <div class="empty">أدخل agent_id واضغط تحميل</div>
  </div>
</div>

<!-- Decision Modal -->
<div class="modal" id="modal">
  <div class="modal-box">
    <h3 id="modal-title">تأكيد القرار</h3>
    <p id="modal-desc" style="color:#94a3b8;font-size:0.85rem;margin-bottom:1rem;"></p>
    <textarea id="modal-notes" placeholder="ملاحظات (اختياري)..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-detail" onclick="closeModal()">إلغاء</button>
      <button class="btn" id="modal-confirm-btn" onclick="confirmDecision()">تأكيد</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentAgent = '';
let currentSecret = '';
let currentTab = 'pending';
let pendingDecision = null;

function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (currentSecret) h['X-AgentOS-Secret'] = currentSecret;
  return h;
}

async function load() {
  currentAgent = document.getElementById('agent-input').value.trim();
  currentSecret = document.getElementById('secret-input').value.trim();
  if (!currentAgent) return toast('أدخل agent_id', true);
  await Promise.all([loadItems(), loadStats()]);
}

async function loadStats() {
  try {
    const r = await fetch(`/api/stats/${currentAgent}`, { headers: headers() });
    const d = await r.json();
    document.getElementById('stat-pending').textContent = d.pending ?? 0;
    document.getElementById('stat-approved').textContent = d.approved ?? 0;
    document.getElementById('stat-rejected').textContent = d.rejected ?? 0;
    document.getElementById('stat-total').textContent = d.total ?? 0;
    document.getElementById('pending-badge').textContent = d.pending ?? 0;
  } catch(e) {}
}

async function loadItems() {
  const url = `/api/approvals/${currentAgent}?status=${currentTab}&limit=50`;
  try {
    const r = await fetch(url, { headers: headers() });
    const d = await r.json();
    renderItems(d.items || []);
  } catch(e) {
    toast('فشل في التحميل', true);
  }
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', ['pending','approved','rejected'][i] === tab);
  });
  if (currentAgent) loadItems();
}

function riskBadge(level, score) {
  const labels = { approve: 'عالي الخطورة', notify: 'متوسط', auto: 'منخفض' };
  return `<span class="risk-badge risk-${level}">${labels[level] || level} (${score})</span>`;
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'منذ لحظات';
  if (diff < 3600) return `منذ ${Math.floor(diff/60)} د`;
  if (diff < 86400) return `منذ ${Math.floor(diff/3600)} س`;
  return `منذ ${Math.floor(diff/86400)} يوم`;
}

function renderItems(items) {
  const el = document.getElementById('list-container');
  if (!items.length) {
    el.innerHTML = '<div class="empty">لا توجد عناصر</div>';
    return;
  }
  el.innerHTML = items.map(item => `
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">${item.title}</div>
          <div class="card-meta">${item.action_type} · ${timeAgo(item.created_at)} · ${item.source || ''}</div>
        </div>
        ${riskBadge(item.risk_level, item.risk_score)}
      </div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="actions">
        ${currentTab === 'pending' ? `
          <button class="btn btn-approve" onclick="openDecision('${item.id}','${escHtml(item.title)}','approved')">✅ موافقة</button>
          <button class="btn btn-reject"  onclick="openDecision('${item.id}','${escHtml(item.title)}','rejected')">❌ رفض</button>
        ` : ''}
        <button class="btn btn-detail" onclick="showDetail('${item.id}')">التفاصيل</button>
      </div>
    </div>
  `).join('');
}

function escHtml(s) { return s.replace(/'/g, "\\'"); }

function openDecision(id, title, decision) {
  pendingDecision = { id, decision };
  document.getElementById('modal-title').textContent =
    decision === 'approved' ? `موافقة على: ${title}` : `رفض: ${title}`;
  document.getElementById('modal-desc').textContent =
    decision === 'approved'
      ? 'سيُنفذ هذا الإجراء في الدورة القادمة للـ daemon.'
      : 'لن يُنفذ هذا الإجراء.';
  const btn = document.getElementById('modal-confirm-btn');
  btn.textContent = decision === 'approved' ? 'موافقة' : 'رفض';
  btn.className = `btn ${decision === 'approved' ? 'btn-approve' : 'btn-reject'}`;
  document.getElementById('modal-notes').value = '';
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
  pendingDecision = null;
}

async function confirmDecision() {
  if (!pendingDecision) return;
  const notes = document.getElementById('modal-notes').value;
  try {
    const r = await fetch(
      `/api/approvals/${currentAgent}/${pendingDecision.id}/decide`,
      {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ decision: pendingDecision.decision, notes, decided_by: 'human_via_gateway' })
      }
    );
    const d = await r.json();
    if (d.success) {
      toast(pendingDecision.decision === 'approved' ? '✅ تمت الموافقة' : '❌ تم الرفض');
      closeModal();
      await load();
    } else {
      toast(d.detail || 'حدث خطأ', true);
    }
  } catch(e) {
    toast('فشل الاتصال', true);
  }
}

async function showDetail(id) {
  try {
    const r = await fetch(`/api/approvals/${currentAgent}/${id}`, { headers: headers() });
    const d = await r.json();
    alert(JSON.stringify(d, null, 2));
  } catch(e) {}
}

function toast(msg, isError=false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show${isError ? ' error' : ''}`;
  setTimeout(() => el.className = 'toast', 3000);
}

// Auto-refresh every 30s
setInterval(() => { if (currentAgent) load(); }, 30000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = getattr(settings, "gateway_host", "127.0.0.1")
    port = getattr(settings, "gateway_port", 8080)
    print(f"AgentOS Gateway → http://{host}:{port}")
    uvicorn.run("gateway:app", host=host, port=port, reload=False)
