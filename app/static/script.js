(function() {
  const API_BASE = "";
  //const USER_ID = "web_user_" + Math.random().toString(36).substr(2, 8);
  // 从 localStorage 获取或创建持久化的 user_id
  let USER_ID = localStorage.getItem('echo_user_id');
  if (!USER_ID) {
      USER_ID = "web_user_" + Math.random().toString(36).substr(2, 8);
      localStorage.setItem('echo_user_id', USER_ID);
  }
  console.log('当前用户ID:', USER_ID);

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
  let sessionMessages = {};

  const homeView = document.getElementById('homeView');
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

  customSelect.addEventListener('click', (e) => {
    e.stopPropagation();
    customOptions.classList.toggle('show');
    customSelect.classList.toggle('open');
  });

  document.addEventListener('click', () => {
    customOptions.classList.remove('show');
    customSelect.classList.remove('open');
  });

  addRoleBtn.addEventListener('click', () => {
    if (!selectedRoleType) { alert('请先选择一个角色'); return; }
    createSession(selectedRoleType);
    selectedRoleType = null;
    customSelectText.textContent = '+ 选择角色';
    document.querySelectorAll('.custom-option').forEach(opt => opt.classList.remove('selected'));
  });

  buildCustomOptions();

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
      item.querySelector('.delete-session').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(session.roleType);
      });
      sessionListEl.appendChild(item);
    });
  }

  function createSession(roleType) {
    const role = ALL_ROLES.find(r => r.type === roleType);
    if (!role) return;
    if (sessions.some(s => s.roleType === roleType)) {
      switchSession(roleType);
      return;
    }
    sessions.push({ roleType: role.type, name: role.name, emoji: role.emoji });
    sessionMessages[roleType] = '';
    switchSession(roleType);
    // 发送带标识的角色选择消息，确保后端精准识别
    sendMessage(`[ROLE_SELECT]${roleType}`, true);
  }

  function switchSession(roleType) {
    if (activeSessionRole) { sessionMessages[activeSessionRole] = chatArea.innerHTML; }
    activeSessionRole = roleType;
    const session = sessions.find(s => s.roleType === roleType);
    if (session) { chatHeaderName.textContent = `与 ${session.name} 的对话`; }
    chatArea.innerHTML = sessionMessages[roleType] || '';
    chatArea.scrollTop = chatArea.scrollHeight;
    renderSessionList();
  }

  function deleteSession(roleType) {
    sessions = sessions.filter(s => s.roleType !== roleType);
    delete sessionMessages[roleType];
    if (activeSessionRole === roleType) {
      if (sessions.length > 0) { switchSession(sessions[0].roleType); }
      else {
        activeSessionRole = null;
        chatHeaderName.textContent = '选择一个会话开始聊天';
        chatArea.innerHTML = '';
      }
    }
    renderSessionList();
  }

  roleCards.forEach(card => {
    card.addEventListener('click', () => {
      const roleType = card.dataset.role;
      if (!roleType) return;
      homeView.classList.remove('active');
      chatView.classList.add('chat-active');
      createSession(roleType);
    });
  });

  backBtn.addEventListener('click', () => {
    chatView.classList.remove('chat-active');
    homeView.classList.add('active');
  });

  async function sendMessage(message, isSystem = false) {
    if (!activeSessionRole) { alert('请先选择一个会话'); return; }
    if (!isSystem) addMessage('user', message, formatTime());
    typingHint.style.display = 'block';
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: USER_ID,
            message: message,
            role_type:activeSessionRole  // 新增：传递当前活跃角色
        })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.role) {
        const role = ALL_ROLES.find(r => r.type === data.role);
        if (role) chatHeaderName.textContent = `与 ${role.name} 的对话`;
      }
      typingHint.style.display = 'none';
      addMessage('ai', data.reply, formatTime());
      if (activeSessionRole) { sessionMessages[activeSessionRole] = chatArea.innerHTML; }
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

  function formatTime() {
    const now = new Date();
    return `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
  }
  function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return text.replace(/[&<>"']/g, m => map[m]);
  }

  sendBtn.addEventListener('click', sendUserMessage);
  userInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendUserMessage(); });
})();