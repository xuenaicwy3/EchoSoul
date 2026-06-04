const API_BASE = '';
const TOKEN = localStorage.getItem('token');
if (!TOKEN) window.location.href = '/login';

async function api(url, options = {}) {
  const controller = new AbortController();
  const timeout = 25000;
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${TOKEN}`,
        ...options.headers,
      }
    });
    clearTimeout(id);
    return res;
  } catch (e) {
    clearTimeout(id);
    throw e;
  }
}

let currentStoryId = null;

// ---------- 加载状态 ----------
function showLoading(show) {
  document.getElementById('loadingSkeleton').style.display = show ? 'flex' : 'none';
  const elems = ['storyMessages', 'storySuggestions', 'storyFreeInput', 'autoContinueBtn'];
  elems.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? 'none' : '';
  });
  const btns = document.querySelectorAll('.story-actions button');
  btns.forEach(b => b.disabled = show);
}

// ---------- 起点加载 ----------
async function loadStarters() {
  try {
    const res = await api(`${API_BASE}/story/starters`);
    const starters = await res.json();
    const grid = document.getElementById('startersGrid');
    grid.innerHTML = '';
    starters.forEach(starter => {
      const card = document.createElement('div');
      card.className = 'starter-card';
      card.innerHTML = `
        <span class="category">${starter.category}</span>
        <h3>${starter.title}</h3>
        <p>${starter.description}</p>
      `;
      card.addEventListener('click', () => startStory(starter));
      grid.appendChild(card);
    });
  } catch (e) {
    console.error('加载起点失败', e);
  }
}

// ---------- 开始故事 ----------
async function startStory(starter) {
  document.getElementById('startersView').classList.add('story-view-hidden');
  document.getElementById('storyView').classList.remove('story-view-hidden');
  showLoading(true);
  try {
    const res = await api(`${API_BASE}/story/start`, {
      method: 'POST',
      body: JSON.stringify({
        role_type: '日系动漫型',
        title: starter.title,
        starter_text: starter.starter_text,
        options: starter.options
      })
    });
    const data = await res.json();
    currentStoryId = data.story_id;
    showLoading(false);
    document.getElementById('storyMessages').innerHTML = '';
    renderNode(data.first_node);
  } catch (e) {
    showLoading(false);
    document.getElementById('storyMessages').innerHTML =
      '<p style="color:#888;text-align:center;">😢 故事创建失败，请返回重试</p>';
  }
}

// ---------- 渲染节点（剧情+选项） ----------
function renderNode(node) {
  // 添加剧情
  const msgDiv = document.getElementById('storyMessages');
  const aiDiv = document.createElement('div');
  aiDiv.className = 'story-message ai';
  aiDiv.innerHTML = `<div class="label">📖 剧情</div><div class="text">${escapeHtml(node.content || node.story_text)}</div>`;
  msgDiv.appendChild(aiDiv);
  msgDiv.scrollTop = msgDiv.scrollHeight;

  // 渲染选项
  const choices = node.choices || node.suggestions || [];
  const suggestionsDiv = document.getElementById('storySuggestions');
  suggestionsDiv.innerHTML = '';
  if (choices.length) {
    choices.forEach(choice => {
      const btn = document.createElement('button');
      btn.className = 'suggestion-btn';
      btn.textContent = choice.text;
      btn.addEventListener('click', () => progressStory('choice', choice.id));
      suggestionsDiv.appendChild(btn);
    });
  }
}

// ---------- 推进故事 ----------
async function progressStory(type, choiceId = null, freeText = null) {
  const btns = document.querySelectorAll('.suggestion-btn, .btn-auto, .btn-send');
  btns.forEach(b => b.disabled = true);
  const suggestionsDiv = document.getElementById('storySuggestions');
  const loadingMsg = document.createElement('p');
  loadingMsg.textContent = '⏳ 正在生成剧情...';
  loadingMsg.style.textAlign = 'center';
  suggestionsDiv.appendChild(loadingMsg);

  try {
    const body = { type };
    if (type === 'choice') body.choice_id = choiceId;
    if (type === 'free_text') body.free_text = freeText;
    if (type === 'auto') body.auto_hint = null;

    const res = await api(`${API_BASE}/story/${currentStoryId}/progress`, {
      method: 'POST',
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (loadingMsg.parentNode) loadingMsg.remove();
    // 添加用户行动
    if (type === 'choice' || type === 'free_text') {
      addUserAction(type === 'choice' ? getChoiceText(choiceId) : freeText);
    }
    renderNode(data);
  } catch (e) {
    if (loadingMsg.parentNode) loadingMsg.remove();
    alert('故事推进失败，请重试');
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

function addUserAction(text) {
  const msgDiv = document.getElementById('storyMessages');
  const div = document.createElement('div');
  div.className = 'story-message user';
  div.innerHTML = `<div class="label">👤 你的行动</div><div class="text">${escapeHtml(text)}</div>`;
  msgDiv.appendChild(div);
  msgDiv.scrollTop = msgDiv.scrollHeight;
}

function getChoiceText(choiceId) {
  const btns = document.querySelectorAll('.suggestion-btn');
  for (let btn of btns) {
    if (btn.textContent.includes(choiceId)) return btn.textContent;
  }
  return `选项 ${choiceId}`;
}

// ---------- 自由输入 ----------
document.getElementById('sendFreeTextBtn').addEventListener('click', () => {
  const input = document.getElementById('freeTextInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  progressStory('free_text', null, text);
});
document.getElementById('freeTextInput').addEventListener('keypress', e => {
  if (e.key === 'Enter') {
    const text = e.target.value.trim();
    if (!text) return;
    e.target.value = '';
    progressStory('free_text', null, text);
  }
});

// ---------- AI自动续写 ----------
document.getElementById('autoContinueBtn').addEventListener('click', () => {
  progressStory('auto');
});

// ---------- 存档 ----------
document.getElementById('archiveBtn').addEventListener('click', async () => {
  if (!currentStoryId) return;
  await api(`${API_BASE}/story/${currentStoryId}/archive`, { method: 'PUT' });
  alert('故事已存档');
});

// ---------- 回放 ----------
document.getElementById('replayBtn').addEventListener('click', async () => {
  if (!currentStoryId) return;
  const res = await api(`${API_BASE}/story/${currentStoryId}`);
  const data = await res.json();
  const container = document.getElementById('replayContainer');
  container.innerHTML = '';
  data.nodes.forEach(node => {
    const div = document.createElement('div');
    div.className = 'story-message';
    const label = node.type === 'user_input' ? '👤 选择' : '📖 剧情';
    div.innerHTML = `<div class="label">${label}</div><div class="text">${escapeHtml(node.content)}</div>`;
    container.appendChild(div);
  });
  document.getElementById('storyView').classList.add('story-view-hidden');
  document.getElementById('replayView').classList.remove('story-view-hidden');
});

document.getElementById('closeReplayBtn').addEventListener('click', () => {
  document.getElementById('replayView').classList.add('story-view-hidden');
  document.getElementById('storyView').classList.remove('story-view-hidden');
});

// ---------- 删除故事 ----------
document.getElementById('deleteBtn').addEventListener('click', async () => {
  if (!currentStoryId) return;
  if (!confirm('确定要删除这个故事吗？删除后无法恢复。')) return;
  try {
    const res = await api(`${API_BASE}/story/${currentStoryId}`, { method: 'DELETE' });
    if (res.ok) {
      alert('故事已删除');
      // 返回起点视图
      document.getElementById('storyView').classList.add('story-view-hidden');
      document.getElementById('startersView').classList.remove('story-view-hidden');
      document.getElementById('storyMessages').innerHTML = '';
      document.getElementById('storySuggestions').innerHTML = '';
      currentStoryId = null;
    } else {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || '未知错误'));
    }
  } catch (e) {
    alert('删除请求失败，请稍后重试');
  }
});

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

// 初始化
loadStarters();