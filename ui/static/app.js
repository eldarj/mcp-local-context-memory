// Tags too generic to use for colouring
const GENERIC_TAGS = new Set(['conversation', 'context', 'mcp']);

let colorScale, gMain, simulation;

async function init() {
  showLoading(true);
  try {
    const res = await fetch('/api/graph');
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const { nodes, links } = await res.json();

    if (!nodes || nodes.length === 0) {
      showEmpty();
      return;
    }

    document.getElementById('node-count').textContent = `${nodes.length} notes`;
    renderGraph(nodes, links);
    showLoading(false);
  } catch (e) {
    document.getElementById('loading').textContent = 'Error: ' + e.message;
  }
}

// First tag that isn't a generic one
function specificTag(tags) {
  return tags.find(t => !GENERIC_TAGS.has(t)) || tags[0] || 'untagged';
}

function renderGraph(nodes, links) {
  const container = document.getElementById('graph');
  const W = container.clientWidth;
  const H = container.clientHeight;

  const specificTags = [...new Set(nodes.map(n => specificTag(n.tags)))].sort();
  colorScale = d3.scaleOrdinal(d3.schemeTableau10).domain(specificTags);

  // Node radius scaled by body length (sqrt so area is proportional)
  const lenExtent = d3.extent(nodes, d => d.body_length);
  const radiusScale = d3.scaleSqrt().domain(lenExtent).range([7, 18]);
  const r = d => radiusScale(d.body_length);

  // Line width + opacity normalised to actual similarity range (not 0–1)
  const simExtent = d3.extent(links, d => d.similarity);
  const widthScale   = d3.scaleLinear().domain(simExtent).range([0.8, 5]);
  const opacityScale = d3.scaleLinear().domain(simExtent).range([0.15, 0.75]);

  const svg = d3.select('#graph').append('svg');

  const zoom = d3.zoom()
    .scaleExtent([0.15, 12])
    .on('zoom', e => gMain.attr('transform', e.transform));

  svg.call(zoom);
  svg.on('click', e => { if (e.target === svg.node()) closeSidebar(); });

  gMain = svg.append('g');

  // Edges
  const linkEl = gMain.selectAll('line.link')
    .data(links)
    .join('line')
    .attr('class', 'link')
    .attr('stroke', '#bbb')
    .attr('stroke-width', d => widthScale(d.similarity))
    .attr('stroke-opacity', d => opacityScale(d.similarity));

  // Node groups
  const nodeG = gMain.selectAll('g.node')
    .data(nodes)
    .join('g')
    .attr('class', 'node')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', dragStart)
      .on('drag',  dragged)
      .on('end',   dragEnd))
    .on('click',     (e, d) => { e.stopPropagation(); selectNode(d); })
    .on('mouseover', showTooltip)
    .on('mousemove', moveTooltip)
    .on('mouseout',  hideTooltip);

  // Selection ring (hidden by default)
  nodeG.append('circle')
    .attr('class', 'ring')
    .attr('r', d => r(d) + 6)
    .attr('fill', 'none')
    .attr('stroke', '#333')
    .attr('stroke-width', 2)
    .attr('opacity', 0);

  // Main dot — size by body length, colour by specific tag
  nodeG.append('circle')
    .attr('class', 'dot')
    .attr('r', r)
    .attr('fill', d => colorScale(specificTag(d.tags)))
    .attr('stroke', '#f5f5f0')
    .attr('stroke-width', 1.5);

  // Label: title (truncated) or key as fallback
  nodeG.append('text')
    .attr('class', 'node-label')
    .attr('dy', d => r(d) + 12)
    .attr('text-anchor', 'middle')
    .text(d => {
      const raw = d.title || d.key.split('/').pop();
      return raw.length > 40 ? raw.slice(0, 40) + '…' : raw;
    });

  // Force simulation: link strength ∝ cosine similarity, distance ∝ dissimilarity
  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links)
      .id((d, i) => i)
      .strength(d => d.similarity * 0.7)
      .distance(d => (1 - d.similarity) * 260 + 40))
    .force('charge', d3.forceManyBody().strength(-280))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(d => r(d) + 6))
    .on('tick', () => {
      linkEl
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      nodeG.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}

// ── Drag ─────────────────────────────────────────────────────────────────────

function dragStart(event, d) {
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x; d.fy = d.y;
}
function dragged(event, d)  { d.fx = event.x; d.fy = event.y; }
function dragEnd(event, d)  {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}

// ── Node selection ───────────────────────────────────────────────────────────

function selectNode(d) {
  gMain.selectAll('circle.ring').attr('opacity', 0);
  gMain.selectAll('g.node')
    .filter(n => n.key === d.key)
    .select('circle.ring')
    .attr('opacity', 1);
  openSidebar(d.key);
}

async function openSidebar(key) {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('note-loading').style.display = 'block';
  document.getElementById('note-content').style.display = 'none';

  try {
    const res = await fetch(`/api/notes/${encodeURIComponent(key)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const note = await res.json();

    document.getElementById('note-key').textContent = note.key;
    document.getElementById('note-tags').innerHTML =
      note.tags.map(t => `<span class="tag">${t}</span>`).join('');
    document.getElementById('note-meta').textContent = `Updated ${note.updated_at}`;
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

// ── Tooltip ──────────────────────────────────────────────────────────────────

const tooltip = document.getElementById('tooltip');

function showTooltip(e, d) {
  tooltip.style.display = 'block';
  tooltip.innerHTML = `<strong>${d.key}</strong>${d.snippet || ''}`;
  moveTooltip(e);
}
function moveTooltip(e) {
  tooltip.style.left = (e.clientX + 14) + 'px';
  tooltip.style.top  = (e.clientY - 10) + 'px';
}
function hideTooltip() { tooltip.style.display = 'none'; }

// ── Loading / empty ──────────────────────────────────────────────────────────

function showLoading(on) {
  document.getElementById('loading').style.display = on ? 'flex' : 'none';
}
function showEmpty() {
  showLoading(false);
  document.getElementById('empty').style.display = 'flex';
}

init();
