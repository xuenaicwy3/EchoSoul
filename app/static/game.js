const API_BASE = '';
let activeRole = '日系动漫型';  // 默认角色，可从URL参数获取

// 初始化：根据URL参数获取角色
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('role')) {
  activeRole = urlParams.get('role');
}

// 通用请求函数（与chat.html一致）
async function api(url, options = {}) {
  return fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token')}`,
      ...options.headers,
    }
  });
}

// 加载养成状态
async function loadStatus() {
  try {
    console.log('正在加载 养成状态')
    const res = await api(`/game/status?role_type=${encodeURIComponent(activeRole)}`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();

    const setDisplay = (id, condition) => {
      const el = document.getElementById(id);
      if (el) el.style.display = condition ? 'block' : 'none';
    };

    const setText = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    setText('intimacy-value', data.intimacy || 0);
    setDisplay('unlock-memory', data.memory_expansion);
    setDisplay('unlock-action', data.special_actions);
    setDisplay('unlock-topic', data.new_topics);
  } catch(e) {
    console.error('加载养成状态失败', e);
  }
}
// 加载每日任务
async function loadDailyTasks() {
  try {
    console.log('正在加载 每日任务')
    const res = await api(`/game/daily-tasks?role_type=${encodeURIComponent(activeRole)}`);
    const tasks = await res.json();
    const list = document.getElementById('task-list');
    list.innerHTML = '';
    tasks.forEach(task => {
      const li = document.createElement('li');
      li.innerHTML = `${task.name} - ${task.description}
        ${task.completed ? '✅' : `<button onclick="completeTask(${task.id})">完成</button>`}`;
      list.appendChild(li);
    });
  } catch(e) {
    console.error('加载每日任务失败', e);
  }
}

// 完成每日任务
async function completeTask(taskId) {
  console.log('正在加载 完成每日任务')
  await api(`/game/daily-tasks/${taskId}/complete?role_type=${encodeURIComponent(activeRole)}`, { method: 'POST' });
  loadDailyTasks();
  loadStatus();
}

// 加载成就
async function loadAchievements() {
  try {
    console.log('正在加载 加载成就')
    const res = await api('/game/achievements');
    const data = await res.json();
    const list = document.getElementById('achievement-list');
    list.innerHTML = '';
    data.forEach(ach => {
      const li = document.createElement('li');
      const percent = Math.min(100, (ach.progress / ach.threshold) * 100);
      li.innerHTML = `${ach.name}: ${ach.progress}/${ach.threshold}
        <progress value="${ach.progress}" max="${ach.threshold}"></progress>
        ${ach.completed ? '🏅' : ''}`;
      list.appendChild(li);
    });
  } catch(e) {
    console.error('加载成就失败', e);
  }
}

// 加载皮肤
async function loadSkins() {
  try {
    console.log('正在加载 加载皮肤')
    const res = await api(`/game/skins?role_type=${encodeURIComponent(activeRole)}`);
    const skins = await res.json();
    const gallery = document.getElementById('skin-gallery');
    gallery.innerHTML = '';
    skins.forEach(skin => {
      const div = document.createElement('div');
      div.className = 'skin-card';
      div.innerHTML = `
        <p>${skin.name} - ${skin.description}</p>
        ${skin.unlocked ?
          (skin.equipped ? '<button disabled>已装备</button>' : `<button onclick="equipSkin(${skin.id})">装备</button>`)
          : `<span>🔒 需要${skin.unlock_condition}</span>`}
      `;
      gallery.appendChild(div);
    });
  } catch(e) {
    console.error('加载皮肤失败', e);
  }
}

async function equipSkin(skinId) {
  await api(`/game/skins/equip?role_type=${encodeURIComponent(activeRole)}&skin_id=${skinId}`, { method: 'POST' });
  loadSkins();
  // 可以改变主题，但需要CSS支持
  document.body.className = `theme-${skinId}`;
}

// 页面加载时执行
loadStatus();
loadDailyTasks();
loadAchievements();
loadSkins();