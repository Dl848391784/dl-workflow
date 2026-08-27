/* dl-workflow 控制台：SSE 驱动，列表 + 详情两视图。 */
"use strict";

const sel = { project: null, name: null, nodeFilter: null };
const $ = (id) => document.getElementById(id);

async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

function fmtDur(s) { return s == null ? "–" : s; }

function banner(text) {
  const b = $("banner");
  if (text) { b.textContent = text; b.classList.remove("hidden"); }
  else b.classList.add("hidden");
}

function renderList(workflows) {
  const tb = document.querySelector("#wf-table tbody");
  tb.innerHTML = "";
  const waiting = [];
  for (const w of workflows) {
    const tr = document.createElement("tr");
    if (w.error) tr.classList.add("err");
    const driver = w.driver_pid ? `🟢 ${w.driver_pid}` : "⚫";
    tr.innerHTML =
      `<td>${w.project.split("/").pop()}</td>` +
      `<td><a href="#">${w.name}</a></td>` +
      `<td>${w.error ? "状态不可读" : w.node}</td>` +
      `<td>${w.gate}${w.held_for_gate ? " 🔒" : ""}</td>` +
      `<td>${driver}</td>` +
      `<td>${w.totals.num_turns}</td><td>${fmtDur(w.totals.duration_s)}</td>` +
      `<td>${w.totals.cost_usd}</td><td>${w.updated_at}</td>`;
    tr.querySelector("a").onclick = (e) => {
      e.preventDefault();
      sel.project = w.project; sel.name = w.name; sel.nodeFilter = null;
      $("list-view").classList.add("hidden");
      $("detail-view").classList.remove("hidden");
      refreshDetail();
    };
    tb.appendChild(tr);
    if (w.need_user || (w.held_for_gate && w.gate === "pending")) {
      waiting.push(`${w.name} @ ${w.node}`);
    }
  }
  if (waiting.length) {
    banner(`等待处理：${waiting.join("、")}`);
    document.title = `(●) dl-workflow 控制台`;
  } else {
    banner(null);
    document.title = "dl-workflow 控制台";
  }
}

function renderNodes(nodes) {
  const strip = $("node-strip");
  strip.innerHTML = "";
  for (const n of nodes) {
    const chip = document.createElement("span");
    chip.className = `chip ${n.status}`;
    chip.textContent = `${n.node_id} ${n.label}`;
    if (sel.nodeFilter === n.node_id) chip.classList.add("active");
    chip.onclick = () => {
      sel.nodeFilter = sel.nodeFilter === n.node_id ? null : n.node_id;
      refreshDetail();
    };
    strip.appendChild(chip);
  }
}

function renderInteract(d) {
  const box = $("interact");
  box.innerHTML = "";
  const proj = sel.project, name = sel.name;
  const mkBtn = (label, fn) => {
    const b = document.createElement("button");
    b.textContent = label; b.onclick = fn; return b;
  };
  if (d.need_user && d.need_user.questions) {
    const h = document.createElement("h3");
    h.textContent = "⏸ 等待输入";
    box.appendChild(h);
    const answers = [];
    d.need_user.questions.forEach((q, i) => {
      const div = document.createElement("div");
      div.className = "q";
      div.innerHTML = `<b>[${q.header || "Q" + (i + 1)}]</b> ${q.question}`;
      (q.options || []).forEach((op) => {
        const l = document.createElement("label");
        l.innerHTML =
          `<input type="radio" name="q${i}" value="${op.label}"> ` +
          `<b>${op.label}</b> — ${op.description || ""}`;
        div.appendChild(l);
      });
      const other = document.createElement("input");
      other.placeholder = "或直接输入答案";
      other.id = `q${i}-other`;
      div.appendChild(other);
      box.appendChild(div);
      answers.push(i);
    });
    box.appendChild(mkBtn("提交答案", async () => {
      const parts = answers.map((i) => {
        const checked = document.querySelector(`input[name=q${i}]:checked`);
        const other = $(`q${i}-other`).value.trim();
        return `问题${i + 1}：${other || (checked ? checked.value : "（未选）")}`;
      });
      const r = await post("/api/inject",
        { project: proj, name, answer: parts.join("\n") });
      alert(r.msg);
      refreshDetail();
    }));
  }
  if (d.info.held_for_gate || d.info.gate === "pending") {
    box.appendChild(mkBtn("✓ gate 放行", async () => {
      const r = await post("/api/gate", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  }
  if (!d.driver_pid) {
    box.appendChild(mkBtn("↻ 重新驱动", async () => {
      const r = await post("/api/drive", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  }
  const form = document.createElement("span");
  form.innerHTML =
    `<select id="dl-cmd"><option>advance</option><option>step-pass</option>` +
    `<option>dispute</option><option>state-reset</option></select>` +
    `<input id="dl-value" placeholder="参数（可空）" size="18">`;
  const go = mkBtn("执行 /dl", async () => {
    const r = await post("/api/dl", { project: proj, name,
      cmd: $("dl-cmd").value, value: $("dl-value").value || null });
    alert(r.msg); refreshDetail();
  });
  box.appendChild(form); box.appendChild(go);
}

function renderSegs(stats) {
  const tb = document.querySelector("#seg-table tbody");
  tb.innerHTML = "";
  for (const s of stats) {
    if (sel.nodeFilter && s.node !== sel.nodeFilter) continue;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${s.node}</td><td>${s.sub_step}</td><td>${s.kind}</td>` +
      `<td>${s.num_turns ?? "–"}</td><td>${s.duration_s ?? "–"}</td>` +
      `<td>${s.cost_usd ?? "–"}</td><td>${s.ts}</td><td>${s.note}</td>`;
    tb.appendChild(tr);
  }
}

async function refreshDetail() {
  if (!sel.project) return;
  const r = await fetch(
    `/api/workflow?project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}`);
  const d = await r.json();
  $("d-title").textContent = `${d.info.name} — ${d.info.node}` +
    (d.driver_pid ? `（driver 🟢 ${d.driver_pid}）` : "（driver ⚫）");
  $("d-statement").textContent = d.info.problem_statement;
  renderNodes(d.info.nodes);
  renderInteract(d);
  renderSegs(d.stats);
  $("log-tail").textContent = d.log_tail;
}

$("back-link").onclick = (e) => {
  e.preventDefault();
  sel.project = null;
  $("detail-view").classList.add("hidden");
  $("list-view").classList.remove("hidden");
};

$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  const r = await post("/api/create", {
    project: $("cf-project").value.trim(),
    name: $("cf-name").value.trim(),
    statement: $("cf-statement").value.trim(),
  });
  alert(r.msg);
};

const es = new EventSource("/api/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (!sel.project) renderList(data.workflows);
  else refreshDetail();
};
