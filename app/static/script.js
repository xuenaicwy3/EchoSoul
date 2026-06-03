(function() {
  const API_BASE = "";
  let USER_ID = null;
  let AUTH_TOKEN = null;

  // ===================== 认证相关 =====================
  const authView = document.getElementById('authView');
  const homeView = document.getElementById('homeView');
  const authUsername = document.getElementById('authUsername');
  const authPassword = document.getElementById('authPassword');
  const authSubmitBtn = document.getElementById('authSubmitBtn');
  const authToggleLink = document.getElementById('authToggleLink');
  const authSubtitle = document.getElementById('authSubtitle');
  const authError = document.getElementById('authError');
  const authToggleText = document.getElementById('authToggleText');

  let isLoginMode = true;

  function setAuthMode(login) {
    isLoginMode = login;
    authSubtitle.textContent = login ? '登录你的账号' : '创建新账号';
    authSubmitBtn.textContent = login ? '登 录' : '注 册';
    authToggleText.textContent = login ? '还没有账号？' : '已有账号？';
    authToggleLink.textContent = login ? '立即注册' : '返回登录';
    authError.style.display = 'none';
  }

  authToggleLink.addEventListener('click', (e) => {
    e.preventDefault();
    setAuthMode(!isLoginMode);
  });

  authSubmitBtn.addEventListener('click', async () => {
    const username = authUsername.value.trim();
    const password = authPassword.value.trim();
    if (!username || !password) {
      authError.textContent = '用户名和密码不能为空';
      authError.style.display = 'block';
      return;
    }
    const url = isLoginMode ? `${API_BASE}/auth/login` : `${API_BASE}/auth/register`;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        authError.textContent = data.detail || '操作失败';
        authError.style.display = 'block';
        return;
      }
      // 保存 token
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user_id', data.user_id);
      AUTH_TOKEN = data.access_token;
      USER_ID = data.user_id;
      // 跳转到首页
      authView.classList.remove('active');
      homeView.classList.add('active');
      authUsername.value = '';
      authPassword.value = '';
    } catch (err) {
      authError.textContent = '网络错误，请稍后重试';
      authError.style.display = 'block';
    }
  });

  // ===================== 通用请求函数 =====================
  async function api(url, options = {}) {
    const token = localStorage.getItem('token');
    return fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : '',
        ...options.headers,
      }
    });
  }

  // ===================== 初始化 =====================
  AUTH_TOKEN = localStorage.getItem('token');
  USER_ID = localStorage.getItem('user_id');
  if (AUTH_TOKEN && USER_ID) {
    authView.classList.remove('active');
    homeView.classList.add('active');
  } else {
    authView.classList.add('active');
  }

  // ===================== 角色与聊天功能 =====================
  const ALL_ROLES = [
    { type: "日系动漫型", name: "小樱", emoji: "🌸", desc: "二次元少女" },
    { type: "高冷御姐型", name: "雪乃", emoji: "❄️", desc: "职场精英" },
    { type: "傲娇辣妹型", name: "凛", emoji: "💢", desc: "傲娇少女" },
    { type: "甜美校花型", name: "甜甜", emoji: "🍬", desc: "校园女神" },
    { type: "软萌可爱型", name: "团子", emoji: "🍡", desc: "软萌可爱" },
    { type: "温柔贤淑型", name: "若兰", emoji: "🌿", desc: "温柔姐姐" },
    { type: "元气少女型", name: "葵", emoji: "☀️", desc: "阳光少女" },
    { type: "清冷仙气型", name: "清歌", emoji: "🌙", desc: "清冷仙女" }
  ];

  let sessions = [];
  let activeSessionRole = null;
  const chatView = document.getElementById('chatView');
  const roleCards = document.querySelectorAll('.role-card');
  const chatArea = document.getElementById('chatArea');
  const userInput = document.getElementById('userInput');
  const sendBtn = document.getElementById('sendBtn');
  const backBtn = document.getElementById('backBtn');
  const sessionListEl = document.getElementById('sessionList');
  const chatHeaderName = document.querySelector('.active-role-name');
  const typingHint = document.getElementById('typingHint');
  const customSelect = document.getElementById('customSelect');
  const customSelectText = document.getElementById('customSelectText');
  const customOptions = document.getElementById('customOptions');
  const addRoleBtn = document.getElementById('addRoleBtn');
  let selectedRoleType = null;

  function buildCustomOptions() {
    customOptions.innerHTML = '';
    ALL_ROLES.forEach(role => {
      const div = document.createElement('div');
      div.className = 'custom-option';
      div.dataset.roleType = role.type;
      div.textContent = `${role.emoji} ${role.name}`;
      div.addEventListener('click', () => {
        selectedRoleType = role.type;
        customSelectText.textContent = `${role.emoji} ${role.name}`;
        customOptions.classList.remove('show');
        customSelect.classList.remove('open');
        document.querySelectorAll('.custom-option').forEach(opt => opt.classList.remove('selected'));
        div.classList.add('selected');
      });
      customOptions.appendChild(div);
    });
  }
  buildCustomOptions();
  customSelect.addEventListener('click', (e) => { e.stopPropagation(); customOptions.classList.toggle('show'); customSelect.classList.toggle('open'); });
  document.addEventListener('click', () => { customOptions.classList.remove('show'); customSelect.classList.remove('open'); });
  addRoleBtn.addEventListener('click', () => {
    if (!selectedRoleType) { alert('请先选择一个角色'); return; }
    createSession(selectedRoleType);
    selectedRoleType = null;
    customSelectText.textContent = '+ 选择角色';
    document.querySelectorAll('.custom-option').forEach(opt => opt.classList.remove('selected'));
  });

  function renderSessionList() {
    sessionListEl.innerHTML = '';
    sessions.forEach(session => {
      const item = document.createElement('div');
      item.className = `session-item${activeSessionRole === session.roleType ? ' active' : ''}`;
      item.innerHTML = `
        <div class="session-avatar">${session.emoji}</div>
        <div class="session-info"><div class="session-name">${session.name}</div></div>
        <button class="delete-session" data-role="${session.roleType}">×</button>
      `;
      item.querySelector('.session-info').addEventListener('click', () => switchSession(session.roleType));
      item.querySelector('.delete-session').addEventListener('click', (e) => { e.stopPropagation(); deleteSession(session.roleType); });
      sessionListEl.appendChild(item);
    });
  }

  function createSession(roleType) {
    const role = ALL_ROLES.find(r => r.type === roleType);
    if (!role) return;
    if (sessions.some(s => s.roleType === roleType)) { switchSession(roleType); return; }
    sessions.push({ roleType: role.type, name: role.name, emoji: role.emoji });
    switchSession(roleType);
    sendMessage(`[ROLE_SELECT]${roleType}`, true);
  }

  async function switchSession(roleType) {
    activeSessionRole = roleType;
    const session = sessions.find(s => s.roleType === roleType);
    if (session) chatHeaderName.textContent = `与 ${session.name} 的对话`;
    await loadHistory(roleType);
    renderSessionList();
  }

  async function deleteSession(roleType) {
    await api(`${API_BASE}/chat_history/${encodeURIComponent(roleType)}`, { method: 'DELETE' });
    sessions = sessions.filter(s => s.roleType !== roleType);
    if (activeSessionRole === roleType) {
      if (sessions.length > 0) switchSession(sessions[0].roleType);
      else { activeSessionRole = null; chatHeaderName.textContent = '选择一个会话开始聊天'; chatArea.innerHTML = ''; }
    }
    renderSessionList();
  }

  async function loadHistory(roleType) {
    try {
      const res = await api(`${API_BASE}/chat_history/${encodeURIComponent(roleType)}`);
      if (res.ok) {
        const data = await res.json();
        chatArea.innerHTML = '';
        data.history.forEach(msg => addMessage(msg.sender, msg.message, formatTime(msg.timestamp)));
        chatArea.scrollTop = chatArea.scrollHeight;
      }
    } catch (e) { console.warn('加载历史失败', e); }
  }

  async function sendMessage(message, isSystem = false) {
      if (!activeSessionRole) { alert('请先选择一个会话'); return; }
      if (!isSystem) addMessage('user', message, formatTime());
      typingHint.style.display = 'block';
      try {
          // 1. 发送消息，获取 task_id
          const res = await api(`${API_BASE}/chat`, {
              method: 'POST',
              body: JSON.stringify({ message, role_type: activeSessionRole })
          });
          const data = await res.json();
          const taskId = data.task_id;

          // 2. 轮询结果
          let replyData = null;
          for (let i = 0; i < 30; i++) {
              await new Promise(r => setTimeout(r, 500));
              const pollRes = await api(`${API_BASE}/chat/result/${taskId}`);
              const pollData = await pollRes.json();
              if (pollData.reply) {   // 关键：检查是否有回复
                  replyData = pollData;
                  break;
              }
          }

          typingHint.style.display = 'none';

          if (replyData) {
              addMessage('ai', replyData.reply, formatTime());
          } else {
              addMessage('ai', '😢 AI 回复超时，请稍后再试~', formatTime());
          }
      } catch (err) {
          typingHint.style.display = 'none';
          addMessage('ai', '😢 网络出小差了，请稍后再试~', formatTime());
      }
  }
  function sendUserMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    if (!activeSessionRole) { alert('请先选择一个会话'); return; }
    userInput.value = '';
    sendMessage(text);
  }

  function addMessage(type, text, time) {
    const session = sessions.find(s => s.roleType === activeSessionRole);
    const avatarEmoji = type === 'ai' ? (session?.emoji || '🌸') : '😊';
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${type}`;
    msgDiv.innerHTML = `
      <div class="avatar">${avatarEmoji}</div>
      <div class="bubble"><div>${escapeHtml(text)}</div><div class="time">${time}</div></div>
    `;
    chatArea.appendChild(msgDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  function formatTime(timestamp) {
    if (timestamp) { const date = new Date(timestamp); return `${date.getHours().toString().padStart(2,'0')}:${date.getMinutes().toString().padStart(2,'0')}`; }
    const now = new Date(); return `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
  }
  function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return text.replace(/[&<>"']/g, m => map[m]);
  }

  sendBtn.addEventListener('click', sendUserMessage);
  userInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendUserMessage(); });
  backBtn.addEventListener('click', () => {
    chatView.classList.remove('chat-active');
    homeView.classList.add('active');
  });
  roleCards.forEach(card => {
    card.addEventListener('click', () => {
      const roleType = card.dataset.role;
      if (!roleType) return;
      homeView.classList.remove('active');
      chatView.classList.add('chat-active');
      createSession(roleType);
    });
  });
})();