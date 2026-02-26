let colorScale, xScale, yScale, gMain;

async function init() {
  showLoading(true);
  try {
    const res = await fetch('/api/graph');
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const { nodes } = await res.json();

    if (!nodes || nodes.length === 0) {
      showEmpty();
      return;
    }

    document.getElementById('node-count').textContent = `${nodes.length} notes`;
    renderGraph(nodes);
    showLoading(false);
  } catch (e) {
    document.getElementById('loading').textContent = 'Error: ' + e.message;
  }
}

function renderGraph(nodes) {
  const container = document.getElementById('graph');
  const W = container.clientWidth;
  const H = container.clientHeight;
  const PAD = 60;

  // Scales: UMAP coords → pixel space
  const xExt = d3.extent(nodes, d => d.x);
  const yExt = d3.extent(nodes, d => d.y);
  xScale = d3.scaleLinear().domain(xExt).range([PAD, W - PAD]);
  yScale = d3.scaleLinear().domain(yExt).range([PAD, H - PAD]);

  // Color by first tag
  const allTags = [...new Set(nodes.flatMap(n => n.tags))].filter(Boolean).sort();
  colorScale = d3.scaleOrdinal(d3.schemeTableau10).domain(allTags);

  const svg = d3.select('#graph').append('svg');

  // Zoom & pan
  const zoom = d3.zoom()
    .scaleExtent([0.15, 12])
    .on('zoom', e => gMain.attr('transform', e.transform));

  svg.call(zoom);
  svg.on('click', e => { if (e.target === svg.node()) closeSidebar(); });

  gMain = svg.append('g');

  // One <g> per node
  const nodeG = gMain.selectAll('g.node')
    .data(nodes)
    .join('g')
    .attr('class', 'node')
    .attr('transform', d => `translate(${xScale(d.x)},${yScale(d.y)})`)
    .style('cursor', 'pointer')
    .on('click', (e, d) => { e.stopPropagation(); selectNode(d); })
    .on('mouseover', showTooltip)
    .on('mousemove', moveTooltip)
    .on('mouseout', hideTooltip);

  // Selection ring (hidden by default)
  nodeG.append('circle')
    .attr('class', 'ring')
    .attr('r', 14)
    .attr('fill', 'none')
    .attr('stroke', '#ffffff')
    .attr('stroke-width', 2)
    .attr('opacity', 0);

  // Main dot
  nodeG.append('circle')
    .attr('class', 'dot')
    .attr('r', 7)
    .attr('fill', d => colorScale(d.tags[0] || 'untagged'))
    .attr('stroke', '#0f0f1a')
    .attr('stroke-width', 1.5);

  // Label: last segment of key
  nodeG.append('text')
    .attr('class', 'node-label')
    .attr('dy', 19)
    .attr('text-anchor', 'middle')
    .text(d => d.key.split('/').pop());
}

// ── Node selection ──────────────────────────────────────────────────────────

function selectNode(d) {
  gMain.selectAll('circle.ring').attr('opacity', 0);
  gMain.selectAll('g.node')
    .filter(n => n.key === d.key)
    .select('circle.ring')
    .attr('opacity', 1);

  openSidebar(d.key);
}

async function openSidebar(key) {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.add('open');

  document.getElementById('note-loading').style.display = 'block';
  document.getElementById('note-content').style.display = 'none';

  try {
    const res = await fetch(`/api/notes/${encodeURIComponent(key)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const note = await res.json();

    document.getElementById('note-key').textContent = note.key;
    document.getElementById('note-tags').innerHTML =
      note.tags.map(t => `<span class="tag">${t}</span>`).join('');
    document.getElementById('note-meta').textContent =
      `Updated ${note.updated_at}`;
    document.getElementById('note-body').innerHTML = marked.parse(note.body);

    document.getElementById('note-loading').style.display = 'none';
    document.getElementById('note-content').style.display = 'block';
  } catch (e) {
    document.getElementById('note-loading').textContent = 'Failed to load note: ' + e.message;
  }
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  if (gMain) gMain.selectAll('circle.ring').attr('opacity', 0);
}

// ── Tooltip ─────────────────────────────────────────────────────────────────

const tooltip = document.getElementById('tooltip');

function showTooltip(e, d) {
  tooltip.style.display = 'block';
  tooltip.innerHTML = `<strong>${d.key}</strong>${d.snippet || ''}`;
  moveTooltip(e);
}

function moveTooltip(e) {
  const x = e.clientX + 14;
  const y = e.clientY - 10;
  tooltip.style.left = x + 'px';
  tooltip.style.top  = y + 'px';
}

function hideTooltip() {
  tooltip.style.display = 'none';
}

// ── Loading / empty states ───────────────────────────────────────────────────

function showLoading(on) {
  document.getElementById('loading').style.display = on ? 'flex' : 'none';
}

function showEmpty() {
  showLoading(false);
  document.getElementById('empty').style.display = 'flex';
}

init();
