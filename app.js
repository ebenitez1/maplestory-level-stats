const DATA_URL = "data/stats.json";

async function load() {
  const status = document.getElementById("status");
  const updated = document.getElementById("updated");
  try {
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    render(data);
    if (data.generated_at) {
      const d = new Date(data.generated_at);
      updated.textContent = `Last updated ${d.toLocaleString()}.`;
    } else {
      updated.textContent = `Waiting for first scrape — trigger the GitHub Action.`;
    }
    const n = Object.keys(data.classes || {}).length;
    status.textContent = n === 0
      ? `No class data yet. The scraper hasn't produced output.`
      : `Showing ${n} classes.`;
  } catch (err) {
    status.textContent = `Failed to load data: ${err.message}.`;
  }
}

function render(data) {
  const thresholds = data.thresholds || [];
  const classes = data.classes || {};
  const max = thresholds.length ? Math.max(...thresholds) : 0;

  const thead = document.querySelector("#stats-table thead");
  const tbody = document.querySelector("#stats-table tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const headRow = document.createElement("tr");
  headRow.appendChild(makeTh("class", -1));
  thresholds.forEach((t, i) => {
    const label = t === max ? `${t}` : `${t}+`;
    headRow.appendChild(makeTh(label, i + 1));
  });
  thead.appendChild(headRow);

  const classNames = Object.keys(classes).sort((a, b) => a.localeCompare(b));
  for (const name of classNames) {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    nameCell.textContent = name;
    row.appendChild(nameCell);
    for (const t of thresholds) {
      const td = document.createElement("td");
      const v = classes[name]?.[String(t)] ?? 0;
      td.textContent = v.toLocaleString();
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }

  attachSort(thead, tbody);
}

function makeTh(label, idx) {
  const el = document.createElement("th");
  el.dataset.col = idx;
  el.innerHTML = `${label}<span class="arrow"></span>`;
  return el;
}

function attachSort(thead, tbody) {
  let activeCol = -1, asc = false;
  thead.querySelectorAll("th").forEach((th, idx) => {
    th.addEventListener("click", () => {
      asc = activeCol === idx ? !asc : false;
      activeCol = idx;
      thead.querySelectorAll("th").forEach((h) => {
        h.classList.remove("sorted");
        h.querySelector(".arrow").textContent = "";
      });
      th.classList.add("sorted");
      th.querySelector(".arrow").textContent = asc ? "▲" : "▼";

      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {
        const av = a.cells[idx].textContent;
        const bv = b.cells[idx].textContent;
        if (idx === 0) return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        const an = Number(av.replace(/,/g, "")) || 0;
        const bn = Number(bv.replace(/,/g, "")) || 0;
        return asc ? an - bn : bn - an;
      });
      tbody.replaceChildren(...rows);
    });
  });
}

load();
