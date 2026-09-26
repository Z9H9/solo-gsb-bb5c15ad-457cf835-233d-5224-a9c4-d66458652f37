/* 实验室配液约束求解器 - 前端逻辑（原生 JS） */
"use strict";

const VOLUME_UNITS = ["mL", "L", "µL"];
const DENSITY_UNITS = ["g/mL", "g/cm³", "kg/m³", "kg/L", "g/L"];
const CONC_UNITS = [
  "mg/mL", "g/L", "mg/L", "µg/mL", "g/100mL",
  "%(w/v)", "%(w/w)", "mol/L", "mmol/L",
];
const MOLAR_UNITS = ["mol/l", "mmol/l"];
const NEEDS_DENSITY = ["%(w/w)"];

/* ---------------- 默认示例 ---------------- */
function defaultState() {
  return {
    planName: "500 mL Tris 缓冲液（20 mM Tris + 150 mM NaCl）",
    targetVolume: 500,
    targetVolumeUnit: "mL",
    targets: [
      { solute: "Tris", concentration: 20, conc_unit: "mmol/L", molar_mass: 121.14 },
      { solute: "NaCl", concentration: 150, conc_unit: "mmol/L", molar_mass: 58.44 },
    ],
    stocks: [
      {
        name: "Tris 母液 1 mol/L", available_volume: 100, volume_unit: "mL",
        density: null, density_unit: "g/mL",
        compositions: [{ solute: "Tris", concentration: 1, conc_unit: "mol/L", molar_mass: 121.14 }],
      },
      {
        name: "NaCl 母液 5 mol/L", available_volume: 100, volume_unit: "mL",
        density: null, density_unit: "g/mL",
        compositions: [{ solute: "NaCl", concentration: 5, conc_unit: "mol/L", molar_mass: 58.44 }],
      },
      {
        name: "纯水", available_volume: 2000, volume_unit: "mL",
        density: null, density_unit: "g/mL", compositions: [],
      },
    ],
    allow_extra_diluent: true,
    extra_diluent_name: "纯水（补充稀释剂）",
    allow_foreign_solutes: false,
    strategy: "min_stock",
  };
}

let state = defaultState();

/* ---------------- 小工具 ---------------- */
const $ = (id) => document.getElementById(id);
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function optionTags(selected, units) {
  return units.map((u) =>
    `<option value="${u}"${u === selected ? " selected" : ""}>${u}</option>`
  ).join("");
}
const isMolar = (u) => MOLAR_UNITS.includes((u || "").toLowerCase());
const needsDensity = (u) => NEEDS_DENSITY.includes(u);
function fmt(x, digits = 6) {
  if (x === null || x === undefined) return "-";
  const n = Number(x);
  if (Math.abs(n) >= 10000 || (Math.abs(n) > 0 && Math.abs(n) < 0.0001))
    return n.toExponential(3);
  return Number(n.toFixed(digits)).toString();
}

/* ---------------- 渲染：单位下拉（静态） ---------------- */
function initStaticSelects() {
  $("targetVolumeUnit").innerHTML = optionTags(state.targetVolumeUnit, VOLUME_UNITS);
}

/* ---------------- 渲染：目标溶质 ---------------- */
function renderTargets() {
  const box = $("targetList");
  box.innerHTML = "";
  state.targets.forEach((t, ti) => {
    const card = el("div", "target-card");
    card.innerHTML = `
      <div class="card-head">
        <label>溶质
          <input data-k="solute" type="text" value="${escapeAttr(t.solute)}" placeholder="如 NaCl" />
        </label>
        <label style="flex:0 0 120px">目标浓度
          <input data-k="concentration" type="number" min="0" step="any" value="${t.concentration}" />
        </label>
        <label style="flex:0 0 110px">单位
          <select data-k="conc_unit">${optionTags(t.conc_unit, CONC_UNITS)}</select>
        </label>
        <label style="flex:0 0 120px; display:${isMolar(t.conc_unit) ? "block" : "none"}" data-molar>
          摩尔质量(g/mol)
          <input data-k="molar_mass" type="number" min="0" step="any"
            value="${t.molar_mass ?? ""}" placeholder="如 58.44" />
        </label>
        <button class="btn danger small" data-del style="flex:0 0 auto">删除</button>
      </div>`;
    card.querySelectorAll("[data-k]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const k = inp.dataset.k;
        state.targets[ti][k] = inp.type === "number" ? Number(inp.value) : inp.value;
        if (k === "conc_unit") renderTargets();
      });
    });
    card.querySelector("[data-del]").addEventListener("click", () => {
      state.targets.splice(ti, 1);
      renderTargets();
    });
    box.appendChild(card);
  });
}
function escapeAttr(s) {
  return String(s ?? "").replace(/"/g, "&quot;");
}

/* ---------------- 渲染：库存溶液 ---------------- */
function renderStocks() {
  const box = $("stockList");
  box.innerHTML = "";
  state.stocks.forEach((s, si) => {
    const card = el("div", "stock-card");
    const hasMolar = s.compositions.some((c) => isMolar(c.conc_unit));
    card.innerHTML = `
      <div class="card-head">
        <label>库存液名称
          <input data-k="name" type="text" value="${escapeAttr(s.name)}" />
        </label>
        <label style="flex:0 0 120px">可用体积
          <input data-k="available_volume" type="number" min="0" step="any"
            value="${s.available_volume}" />
        </label>
        <label style="flex:0 0 90px">单位
          <select data-k="volume_unit">${optionTags(s.volume_unit, VOLUME_UNITS)}</select>
        </label>
        <button class="btn danger small" data-del style="flex:0 0 auto">删除</button>
      </div>
      <div class="card-head" style="margin-top:8px">
        <label style="flex:0 0 160px">密度（%(w/w) 时必填）
          <input data-k="density" type="number" min="0" step="any"
            value="${s.density ?? ""}" placeholder="可留空，如 1.05" />
        </label>
        <label style="flex:0 0 100px">密度单位
          <select data-k="density_unit">${optionTags(s.density_unit, DENSITY_UNITS)}</select>
        </label>
      </div>
      <table class="comp-table${hasMolar ? " has-molar" : ""}">
        <thead>
          <tr>
            <th>溶质</th><th style="width:120px">浓度</th><th style="width:100px">单位</th>
            <th class="col-molar" style="width:120px">摩尔质量(g/mol)</th><th style="width:50px"></th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
      <span class="diluent-tag" data-diluent-tag
        style="display:${s.compositions.length === 0 ? "inline-block" : "none"}">
        无溶质组分 → 作为纯稀释剂使用
      </span>
      <button class="btn small" data-addcomp>＋ 添加溶质组分</button>`;

    const tbody = card.querySelector("tbody");
    s.compositions.forEach((c, ci) => {
      const tr = el("tr");
      tr.innerHTML = `
        <td><input data-ck="solute" type="text" value="${escapeAttr(c.solute)}" /></td>
        <td><input data-ck="concentration" type="number" min="0" step="any" value="${c.concentration}" /></td>
        <td><select data-ck="conc_unit">${optionTags(c.conc_unit, CONC_UNITS)}</select></td>
        <td class="col-molar"><input data-ck="molar_mass" type="number" min="0" step="any"
          value="${c.molar_mass ?? ""}" placeholder="如 58.44" /></td>
        <td><button class="btn link danger" data-ccdel>删</button></td>`;
      tr.querySelectorAll("[data-ck]").forEach((inp) => {
        inp.addEventListener("change", () => {
          const k = inp.dataset.ck;
          state.stocks[si].compositions[ci][k] =
            inp.tagName === "SELECT" || inp.type !== "number"
              ? inp.value
              : Number(inp.value);
          if (k === "conc_unit") renderStocks();
        });
      });
      tr.querySelector("[data-ccdel]").addEventListener("click", () => {
        s.compositions.splice(ci, 1);
        renderStocks();
      });
      tbody.appendChild(tr);
    });

    card.querySelectorAll("[data-k]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const k = inp.dataset.k;
        state.stocks[si][k] =
          inp.tagName === "SELECT" || inp.type !== "number"
            ? inp.value
            : (inp.value === "" ? null : Number(inp.value));
      });
    });
    card.querySelector("[data-addcomp]").addEventListener("click", () => {
      s.compositions.push({
        solute: "", concentration: 0, conc_unit: "mg/mL", molar_mass: null,
      });
      renderStocks();
    });
    card.querySelector("[data-del]").addEventListener("click", () => {
      state.stocks.splice(si, 1);
      renderStocks();
    });
    box.appendChild(card);
  });
}

/* ---------------- 收集表单 ---------------- */
function collectState() {
  state.planName = $("planName").value.trim();
  state.targetVolume = Number($("targetVolume").value);
  state.targetVolumeUnit = $("targetVolumeUnit").value;
  state.allow_extra_diluent = $("allowDiluent").checked;
  state.extra_diluent_name = $("diluentName").value.trim() || "纯水（补充稀释剂）";
  state.allow_foreign_solutes = $("allowForeign").checked;
  state.strategy = $("strategy").value;
  return state;
}

function fillForm(s) {
  state = JSON.parse(JSON.stringify(s));
  if (!state.stocks) state.stocks = [];
  $("planName").value = state.planName || "";
  $("targetVolume").value = state.targetVolume ?? "";
  $("targetVolumeUnit").value = state.targetVolumeUnit || "mL";
  $("allowDiluent").checked = state.allow_extra_diluent !== false;
  $("diluentName").value = state.extra_diluent_name || "纯水（补充稀释剂）";
  $("allowForeign").checked = !!state.allow_foreign_solutes;
  $("strategy").value = state.strategy || "min_stock";
  renderTargets();
  renderStocks();
}

/* ---------------- 求解 ---------------- */
async function solve() {
  collectState();
  const resultBox = $("result");
  resultBox.classList.add("loading");
  resultBox.innerHTML = `<p class="muted">求解中…</p>`;

  // 前端快速校验
  if (!(state.targetVolume > 0)) {
    return showInputError("目标总体积必须为正数");
  }
  if (state.targets.length === 0) {
    return showInputError("请至少添加一种目标溶质");
  }
  for (const t of state.targets) {
    if (!t.solute.trim()) return showInputError("目标溶质名称不能为空");
    if (isMolar(t.conc_unit) && !(Number(t.molar_mass) > 0))
      return showInputError(`溶质“${t.solute}”使用摩尔浓度，必须填写摩尔质量`);
  }
  if (state.stocks.length === 0) {
    return showInputError("请至少添加一种库存溶液");
  }
  for (const s of state.stocks) {
    if (!s.name.trim()) return showInputError("库存液名称不能为空");
    if (!(s.available_volume > 0))
      return showInputError(`库存液“${s.name}”的可用体积必须为正数`);
    for (const c of s.compositions) {
      if (!c.solute.trim())
        return showInputError(`库存液“${s.name}”存在空名称的组分`);
      if (isMolar(c.conc_unit) && !(Number(c.molar_mass) > 0))
        return showInputError(`库存液“${s.name}”中“${c.solute}”使用摩尔浓度，必须填写摩尔质量`);
      if (needsDensity(c.conc_unit) && !(Number(s.density) > 0))
        return showInputError(`库存液“${s.name}”中“${c.solute}”为 %(w/w)，必须填写密度`);
    }
  }

  const payload = {
    target_volume: state.targetVolume,
    volume_unit: state.targetVolumeUnit,
    targets: state.targets,
    stocks: state.stocks,
    allow_extra_diluent: state.allow_extra_diluent,
    extra_diluent_name: state.extra_diluent_name,
    allow_foreign_solutes: state.allow_foreign_solutes,
    strategy: state.strategy,
  };

  try {
    const resp = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (resp.status === 422) {
      const err = await resp.json();
      return showInputError(err.detail || "输入参数有误");
    }
    if (!resp.ok) {
      return showInputError(`服务端错误：HTTP ${resp.status}`);
    }
    const data = await resp.json();
    state.lastResult = data;
    renderResult(data);
  } catch (e) {
    resultBox.classList.remove("loading");
    resultBox.innerHTML = "";
    resultBox.appendChild(callout("err", `请求失败：${e.message}`));
  }
}

function showInputError(msg) {
  const box = $("result");
  box.classList.remove("loading");
  box.innerHTML = "";
  box.appendChild(callout("err", msg));
}

function callout(cls, msg) {
  return el("div", `callout ${cls}`, msg);
}

function renderResult(data) {
  const box = $("result");
  box.classList.remove("loading");
  box.innerHTML = "";

  if (!data.feasible) {
    const c = el("div", "callout err");
    c.innerHTML = `<b>✗ 无可行取液方案</b><ul>${
      (data.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("")
    }</ul>`;
    box.appendChild(c);
    return;
  }

  box.appendChild(
    el("div", "", `<span class="badge ok">✓ 方案可行</span>`)
  );

  // 取液量表
  const t = el("table");
  t.style.marginTop = "10px";
  const vu = data.volume_unit;
  let rows = data.usages.map((u) =>
    `<tr><td>${escapeHtml(u.stock_name)}</td>
       <td class="num">${fmt(u.volume_display)}</td>
       <td>${vu}</td></tr>`
  ).join("");
  if (data.extra_diluent.used) {
    rows += `<tr style="color:var(--warn)">
      <td>${escapeHtml(data.extra_diluent.name)} <span class="muted">（额外补充）</span></td>
      <td class="num">${fmt(data.extra_diluent.volume_display)}</td><td>${vu}</td></tr>`;
  }
  t.innerHTML = `
    <thead><tr><th>取用库存液</th><th class="num">用量</th><th>单位</th></tr></thead>
    <tbody>${rows}</tbody>
    <tfoot><tr style="font-weight:600">
      <td>合计（目标总体积）</td>
      <td class="num">${fmt(data.target_volume)}</td><td>${vu}</td>
    </tr></tfoot>`;
  box.appendChild(t);

  if (!data.extra_diluent.used) {
    box.appendChild(callout(
      "ok",
      `体积完全由库存溶液凑足，库存取液合计 ${fmt(data.total_stock_volume_display)} ${vu}，无需额外补水。`
    ));
  } else {
    box.appendChild(callout(
      "warn",
      `库存液合计 ${fmt(data.total_stock_volume_display)} ${vu}，` +
      `需额外加入 ${escapeHtml(data.extra_diluent.name)} ${fmt(data.extra_diluent.volume_display)} ${vu}。`
    ));
  }

  // 浓度核验
  const ct = el("table");
  ct.innerHTML = `
    <thead><tr><th>溶质</th><th class="num">目标浓度</th>
      <th class="num">实际浓度</th><th>单位</th><th class="num">相对误差</th></tr></thead>
    <tbody>${data.concentration_check.map((r) =>
      `<tr><td>${escapeHtml(r.solute)}</td>
        <td class="num">${fmt(r.target_concentration, 8)}</td>
        <td class="num">${fmt(r.actual_concentration, 8)}</td>
        <td>${r.conc_unit}</td>
        <td class="num">${(r.relative_error * 100).toExponential(1)}%</td></tr>`
    ).join("")}</tbody>`;
  box.appendChild(el("h3", "", "浓度核验"));
  box.appendChild(ct);
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

/* ---------------- 保存 / 载入 ---------------- */
async function savePlan() {
  collectState();
  if (!state.planName) {
    $("planName").focus();
    return showInputError("请先填写配方名称再保存");
  }
  const resp = await fetch("/api/plans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: state.planName, input: buildPayload() }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    return showInputError(err.detail || `保存失败 HTTP ${resp.status}`);
  }
  await loadSavedPlans();
  toast("方案已保存", "ok");
}

function toast(msg, cls = "ok") {
  const c = callout(cls, `💾 ${msg}`);
  $("result").prepend(c);
  setTimeout(() => c.remove(), 2500);
}

function buildPayload() {
  return {
    target_volume: state.targetVolume,
    volume_unit: state.targetVolumeUnit,
    targets: state.targets,
    stocks: state.stocks,
    allow_extra_diluent: state.allow_extra_diluent,
    extra_diluent_name: state.extra_diluent_name,
    allow_foreign_solutes: state.allow_foreign_solutes,
    strategy: state.strategy,
  };
}

async function loadSavedPlans() {
  const box = $("savedList");
  const resp = await fetch("/api/plans");
  const plans = await resp.json();
  box.innerHTML = "";
  if (plans.length === 0) {
    box.appendChild(el("p", "muted", "暂无保存方案。"));
    return;
  }
  for (const p of plans) {
    const item = el("div", "saved-item");
    item.innerHTML = `
      <div>
        <b>${escapeHtml(p.name)}</b>
        <span class="meta">更新于 ${formatTime(p.updated_at)}</span>
      </div>
      <div class="ops">
        <button class="btn small" data-load>载入并计算</button>
        <button class="btn small danger" data-del>删除</button>
      </div>`;
    item.querySelector("[data-load]").addEventListener("click", () => loadPlan(p.id));
    item.querySelector("[data-del]").addEventListener("click", async () => {
      if (!confirm(`确定删除方案“${p.name}”？`)) return;
      await fetch(`/api/plans/${p.id}`, { method: "DELETE" });
      loadSavedPlans();
    });
    box.appendChild(item);
  }
}

async function loadPlan(id) {
  const resp = await fetch(`/api/plans/${id}`);
  if (!resp.ok) return;
  const plan = await resp.json();
  fillForm({ ...plan.input, planName: plan.name });
  await solve();
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

/* ---------------- 初始化 ---------------- */
function init() {
  initStaticSelects();
  fillForm(state);

  $("addTarget").addEventListener("click", () => {
    state.targets.push({
      solute: "", concentration: 0, conc_unit: "mg/mL", molar_mass: null,
    });
    renderTargets();
  });
  $("addStock").addEventListener("click", () => {
    state.stocks.push({
      name: "", available_volume: 100, volume_unit: "mL",
      density: null, density_unit: "g/mL", compositions: [],
    });
    renderStocks();
  });
  $("solveBtn").addEventListener("click", solve);
  $("saveBtn").addEventListener("click", savePlan);
  $("resetBtn").addEventListener("click", () => {
    fillForm(defaultState());
    $("result").innerHTML = `<p class="muted">已重置为示例数据，点击“求解取液方案”。</p>`;
  });

  loadSavedPlans();
}

document.addEventListener("DOMContentLoaded", init);
