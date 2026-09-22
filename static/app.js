/* 实验室配液约束求解器 —— 前端逻辑（原生 JS） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let META = null;
let stocks = [];
let plans = [];
let lastSolvePayload = null;   // 最近一次求解的配方（保存用）

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg, type = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const opts = Object.assign({ headers: {} }, options);
  if (opts.body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string"
      ? data.detail
      : JSON.stringify(data.detail);
    throw new Error(detail || `请求失败 (${res.status})`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// 单位下拉初始化
// ---------------------------------------------------------------------------
function fillSelect(selectEl, groupsOrList, selected) {
  selectEl.innerHTML = "";
  let items;
  if (Array.isArray(groupsOrList)) {
    items = groupsOrList.map((u) => [u, u]);
  } else {
    items = [];
    const labels = {
      molar: "摩尔浓度", mass: "质量浓度",
      volfrac: "体积分数", ww: "质量分数 (需密度)",
    };
    for (const [fam, units] of Object.entries(groupsOrList)) {
      for (const u of units) items.push([u, `${labels[fam] || fam}：${u}`]);
    }
  }
  for (const [value, label] of items) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    if (value === selected) opt.selected = true;
    selectEl.appendChild(opt);
  }
}

function initForms() {
  fillSelect($("#st-conc-unit"), META.concentration_units, "M");
  fillSelect($("#st-density-unit"), META.density_units, "g/mL");
  fillSelect($("#st-vol-unit"), META.volume_units, "mL");
  fillSelect($("#total-volume-unit"), META.volume_units, "mL");
  // 目标浓度不提供 w/w（服务端也会拦截）
  const targetGroups = {
    molar: META.concentration_units.molar,
    mass: META.concentration_units.mass,
    volfrac: META.concentration_units.volfrac,
  };
  window._targetGroups = targetGroups;
  addTargetRow("NaCl", "mM");
  addTargetRow();
}

// ---------------------------------------------------------------------------
// 库存液
// ---------------------------------------------------------------------------
function resetStockForm() {
  $("#stock-id").value = "";
  $("#stock-form").reset();
  $("#st-conc-unit").value = "M";
  $("#st-density-unit").value = "g/mL";
  $("#st-vol-unit").value = "mL";
  $("#st-submit").textContent = "添加库存液";
  $("#st-cancel").classList.add("hidden");
}

function readStockForm() {
  const densityVal = $("#st-density").value.trim();
  return {
    name: $("#st-name").value.trim(),
    solute: $("#st-solute").value.trim(),
    concentration: parseFloat($("#st-conc").value),
    concentration_unit: $("#st-conc-unit").value,
    density: densityVal === "" ? null : parseFloat(densityVal),
    density_unit: $("#st-density-unit").value,
    available_volume: parseFloat($("#st-avail").value),
    volume_unit: $("#st-vol-unit").value,
  };
}

$("#stock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  let payload;
  try {
    payload = readStockForm();
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  const editId = $("#stock-id").value;
  try {
    if (editId) {
      await api(`/api/stocks/${editId}`, { method: "PUT", body: payload });
      toast("库存液已更新", "success");
    } else {
      await api("/api/stocks", { method: "POST", body: payload });
      toast("库存液已添加", "success");
    }
    resetStockForm();
    await loadStocks();
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#st-cancel").addEventListener("click", resetStockForm);

function editStock(id) {
  const s = stocks.find((x) => x.id === id);
  if (!s) return;
  $("#stock-id").value = s.id;
  $("#st-name").value = s.name;
  $("#st-solute").value = s.solute;
  $("#st-conc").value = s.concentration;
  $("#st-conc-unit").value = s.concentration_unit;
  $("#st-density").value = s.density ?? "";
  $("#st-density-unit").value = s.density_unit || "g/mL";
  $("#st-avail").value = s.available_volume;
  $("#st-vol-unit").value = s.volume_unit;
  $("#st-submit").textContent = "保存修改";
  $("#st-cancel").classList.remove("hidden");
  $("#stocks-section").scrollIntoView({ behavior: "smooth" });
}

async function deleteStock(id) {
  const s = stocks.find((x) => x.id === id);
  if (!confirm(`确定删除库存液「${s.name}」吗？`)) return;
  try {
    await api(`/api/stocks/${id}`, { method: "DELETE" });
    toast("已删除", "success");
    if (String($("#stock-id").value) === String(id)) resetStockForm();
    await loadStocks();
  } catch (err) {
    toast(err.message, "error");
  }
}

function renderStocks() {
  const tbody = $("#stocks-tbody");
  tbody.innerHTML = "";
  for (const s of stocks) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(s.name)}</td>
      <td>${esc(s.solute)}</td>
      <td><code>${esc(s.concentration)} ${esc(s.concentration_unit)}</code></td>
      <td>${s.density == null
        ? '<span class="muted">—</span>'
        : `<code>${esc(s.density)} ${esc(s.density_unit)}</code>`}</td>
      <td>${esc(s.available_volume)} ${esc(s.volume_unit)}</td>
      <td class="col-actions">
        <div class="row-actions">
          <button class="btn btn-ghost" data-act="edit">编辑</button>
          <button class="btn btn-danger" data-act="del">删除</button>
        </div>
      </td>`;
    tr.querySelector('[data-act="edit"]').addEventListener("click", () => editStock(s.id));
    tr.querySelector('[data-act="del"]').addEventListener("click", () => deleteStock(s.id));
    tbody.appendChild(tr);
  }
  $("#stocks-empty").style.display = stocks.length ? "none" : "";
  // 溶质名自动补全
  const names = [...new Set(stocks.map((s) => s.solute))];
  $("#solute-list").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
}

async function loadStocks() {
  stocks = await api("/api/stocks");
  renderStocks();
}

$("#btn-demo").addEventListener("click", async () => {
  try {
    await api("/api/demo", { method: "POST" });
    toast("演示数据已载入", "success");
    await loadStocks();
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#btn-clear-stocks").addEventListener("click", async () => {
  if (!stocks.length) return;
  if (!confirm(`确定清空全部 ${stocks.length} 条库存液吗？此操作不可恢复。`)) return;
  try {
    for (const s of [...stocks]) {
      await api(`/api/stocks/${s.id}`, { method: "DELETE" });
    }
    toast("库存已清空", "success");
    await loadStocks();
  } catch (err) {
    toast(err.message, "error");
  }
});

// ---------------------------------------------------------------------------
// 目标配方行
// ---------------------------------------------------------------------------
function addTargetRow(solute = "", unit = "mM") {
  const tbody = $("#targets-tbody");
  const tr = document.createElement("tr");
  tr.className = "target-row";
  tr.innerHTML = `
    <td><input type="text" class="t-solute" list="solute-list" placeholder="溶质名"
               value="${esc(solute)}" style="min-width:120px"></td>
    <td><input type="number" class="t-conc" min="0" step="any" placeholder="目标浓度"
               style="min-width:110px"></td>
    <td><select class="t-unit" style="min-width:130px"></select></td>
    <td class="col-actions">
      <div class="row-actions">
        <button type="button" class="btn btn-danger" data-act="del">移除</button>
      </div>
    </td>`;
  fillSelect(tr.querySelector(".t-unit"), window._targetGroups, unit);
  tr.querySelector('[data-act="del"]').addEventListener("click", () => {
    tr.remove();
  });
  tbody.appendChild(tr);
}

$("#btn-add-target").addEventListener("click", () => addTargetRow());

function readTargets() {
  const targets = [];
  for (const tr of $$("#targets-tbody .target-row")) {
    const solute = tr.querySelector(".t-solute").value.trim();
    const conc = parseFloat(tr.querySelector(".t-conc").value);
    const unit = tr.querySelector(".t-unit").value;
    if (!solute && Number.isNaN(conc)) continue; // 完全空行：忽略
    if (!solute) throw new Error("存在未填写溶质名称的目标行");
    if (Number.isNaN(conc) || conc <= 0) {
      throw new Error(`溶质「${solute}」的目标浓度必须为正数`);
    }
    targets.push({ solute, concentration: conc, concentration_unit: unit });
  }
  if (!targets.length) throw new Error("请至少添加一种目标溶质");
  // 前端重复名检查
  const seen = new Set();
  for (const t of targets) {
    const k = t.solute.toLowerCase();
    if (seen.has(k)) throw new Error(`目标溶质「${t.solute}」重复`);
    seen.add(k);
  }
  return targets;
}

// ---------------------------------------------------------------------------
// 求解与结果渲染
// ---------------------------------------------------------------------------
$("#btn-solve").addEventListener("click", async () => {
  let targets;
  try {
    targets = readTargets();
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  const totalVolume = parseFloat($("#total-volume").value);
  if (!(totalVolume > 0)) {
    toast("目标总体积必须为正数", "error");
    return;
  }
  const payload = {
    total_volume: totalVolume,
    volume_unit: $("#total-volume-unit").value,
    targets,
  };
  if (!stocks.length) {
    toast("库存为空，请先添加库存液或载入演示数据", "error");
    return;
  }
  try {
    const result = await api("/api/solve", { method: "POST", body: payload });
    lastSolvePayload = payload;
    renderResult(result);
  } catch (err) {
    toast(err.message, "error");
  }
});

function renderResult(r) {
  $("#result-section").classList.remove("hidden");
  const badge = $("#result-badge");
  const body = $("#result-body");

  if (!r.feasible) {
    badge.textContent = "不可行";
    badge.className = "badge-fail";
    let detailHtml = "";
    if (r.details && r.details.length) {
      detailHtml = `
        <div class="detail-block">
          <h4>逐溶质诊断</h4>
          <table>
            <thead><tr><th>溶质</th><th>目标浓度</th><th>需要量</th>
              <th>库存可提供</th><th>缺口</th></tr></thead>
            <tbody>
              ${r.details.map((d) => `
                <tr>
                  <td>${esc(d.solute)}</td>
                  <td>${esc(d.target_concentration)}</td>
                  <td>${esc(d.required_amount)}</td>
                  <td>${esc(d.available_amount)}</td>
                  <td><strong>${esc(d.shortage)}</strong></td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
    }
    body.innerHTML = `
      <div class="result-fail">
        <div class="reason">❌ 不存在可行的配液方案</div>
        <div>${esc(r.reason)}</div>
      </div>
      ${detailHtml}`;
    $("#save-section").classList.add("hidden");
    $("#result-section").scrollIntoView({ behavior: "smooth" });
    return;
  }

  badge.textContent = "可行";
  badge.className = "badge-ok";

  body.innerHTML = `
    <div class="result-ok">
      <div class="big">✅ 已求得可行方案</div>
      <div class="kv-grid">
        <div class="kv"><div class="k">目标总体积</div>
          <div class="v">${esc(r.total_volume_display)}</div></div>
        <div class="kv"><div class="k">库存液取用合计</div>
          <div class="v">${esc(r.total_stock_volume_display)}</div></div>
        <div class="kv"><div class="k">稀释剂补量</div>
          <div class="v" style="color:${r.needs_diluent ? "var(--primary)" : "var(--muted)"}">
            ${r.needs_diluent ? "💧 " + esc(r.diluent_volume_display) : "无需稀释剂"}
          </div></div>
      </div>
    </div>

    <div class="detail-block">
      <h4>各库存液用量</h4>
      <table>
        <thead><tr>
          <th>库存液</th><th>溶质</th><th>原液浓度</th>
          <th>用量</th><th>占该库存</th><th>库存上限</th>
        </tr></thead>
        <tbody>
          ${r.used_stocks.map((u) => `
            <tr>
              <td>${esc(u.stock_name)}</td>
              <td>${esc(u.solute)}</td>
              <td><code>${esc(u.stock_concentration)}</code></td>
              <td><strong>${esc(u.volume_display)}</strong></td>
              <td>${esc(u.utilization_pct)}%</td>
              <td class="muted">≤ ${esc(u.available_ml)} mL</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="detail-block">
      <h4>逐溶质配制明细</h4>
      <table>
        <thead><tr><th>溶质</th><th>目标浓度</th><th>所需溶质量</th>
          <th>取液来源</th><th>小计</th></tr></thead>
        <tbody>
          ${r.per_solute.map((p) => `
            <tr>
              <td>${esc(p.solute)}</td>
              <td>${esc(p.target_concentration)}</td>
              <td>${esc(p.required_amount)}</td>
              <td>${p.sources.map((s) =>
                `${esc(s.stock_name)}：<strong>${esc(s.volume_display)}</strong>`
              ).join("<br>")}</td>
              <td>${esc(p.stock_volume_used)}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="detail-block">
      <h4>回算校验（实际混合浓度）</h4>
      <table>
        <thead><tr><th>溶质</th><th>目标</th><th>回算浓度</th><th>相对误差</th></tr></thead>
        <tbody>
          ${r.verification.map((v) => `
            <tr>
              <td>${esc(v.solute)}</td>
              <td>${esc(v.target)}</td>
              <td>${esc(v.achieved)}</td>
              <td class="muted">${esc(v.relative_error)}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  $("#save-section").classList.remove("hidden");
  $("#plan-name").value = "";
  $("#result-section").scrollIntoView({ behavior: "smooth" });
}

// ---------------------------------------------------------------------------
// 保存方案 / 再计算
// ---------------------------------------------------------------------------
$("#btn-save-plan").addEventListener("click", async () => {
  if (!lastSolvePayload) return;
  const name = $("#plan-name").value.trim();
  if (!name) {
    toast("请填写方案名称", "error");
    return;
  }
  try {
    await api("/api/plans", {
      method: "POST",
      body: {
        name,
        total_volume: lastSolvePayload.total_volume,
        volume_unit: lastSolvePayload.volume_unit,
        targets: lastSolvePayload.targets,
      },
    });
    toast("方案已保存", "success");
    await loadPlans();
  } catch (err) {
    toast(err.message, "error");
  }
});

async function loadPlans() {
  plans = await api("/api/plans");
  const tbody = $("#plans-tbody");
  tbody.innerHTML = "";
  for (const p of plans) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.id}</td>
      <td>${esc(p.name)}</td>
      <td>${esc(p.total_volume)} ${esc(p.volume_unit)}</td>
      <td>${p.targets.length} 种</td>
      <td>${p.feasible
        ? '<span class="pill pill-ok">可行</span>'
        : '<span class="pill pill-fail">不可行</span>'}</td>
      <td class="muted">${esc(p.created_at.replace("T", " ").replace("+00:00", " UTC"))}</td>
      <td class="col-actions">
        <div class="row-actions">
          <button class="btn btn-ghost" data-act="view">查看结果</button>
          <button class="btn btn-primary" data-act="recalc">用最新库存再计算</button>
          <button class="btn btn-danger" data-act="del">删除</button>
        </div>
      </td>`;
    tr.querySelector('[data-act="view"]').addEventListener("click", () => {
      // 恢复配方到表单并展示保存的结果
      $("#total-volume").value = p.total_volume;
      $("#total-volume-unit").value = p.volume_unit;
      $("#targets-tbody").innerHTML = "";
      for (const t of p.targets) addTargetRow(t.solute, t.concentration_unit);
      $$("#targets-tbody .target-row").forEach((tr, i) => {
        tr.querySelector(".t-conc").value = p.targets[i].concentration;
      });
      lastSolvePayload = {
        total_volume: p.total_volume,
        volume_unit: p.volume_unit,
        targets: p.targets,
      };
      renderResult(p.result);
      toast("已载入保存时的结果", "");
    });
    tr.querySelector('[data-act="recalc"]').addEventListener("click", async () => {
      try {
        const updated = await api(`/api/plans/${p.id}/recalculate`, { method: "POST" });
        renderResult(updated);
        toast(updated.feasible ? "再计算完成：方案可行" : "再计算完成：当前不可行",
               updated.feasible ? "success" : "error");
        await loadPlans();
      } catch (err) {
        toast(err.message, "error");
      }
    });
    tr.querySelector('[data-act="del"]').addEventListener("click", async () => {
      if (!confirm(`确定删除方案「${p.name}」吗？`)) return;
      try {
        await api(`/api/plans/${p.id}`, { method: "DELETE" });
        toast("方案已删除", "success");
        await loadPlans();
      } catch (err) {
        toast(err.message, "error");
      }
    });
    tbody.appendChild(tr);
  }
  $("#plans-empty").style.display = plans.length ? "none" : "";
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------
(async function init() {
  try {
    META = await api("/api/meta");
    initForms();
    await loadStocks();
    await loadPlans();
  } catch (err) {
    toast("初始化失败：" + err.message, "error");
  }
})();
