// const API_BASE = "";   // 同源
// const USER_ID = "web_user_" + Math.random().toString(36).substr(2, 8);
// const chatArea = document.getElementById('chatArea');
// const userInput = document.getElementById('userInput');
// const sendBtn = document.getElementById('sendBtn');
// const roleSelect = document.getElementById('roleSelect');
// const affectionEls = {
//     intimacy: document.getElementById('intimacy'),
//     trust: document.getElementById('trust'),
//     fun: document.getElementById('fun'),
//     growth: document.getElementById('growth'),
//     level: document.getElementById('level'),
// };
//
// let currentRole = localStorage.getItem('currentRole') || '';
// if (currentRole) {
//     roleSelect.value = currentRole;
//     fetchAffection(currentRole);
// }
//
// roleSelect.addEventListener('change', function () {
//     const role = this.value;
//     if (!role) return;
//     localStorage.setItem('currentRole', role);
//     currentRole = role;
//     const autoMsg = `我想要一个${role}`;
//     addMessage('user', autoMsg, formatTime());
//     sendMessage(autoMsg);
//     fetchAffection(role);
// });
//
// sendBtn.addEventListener('click', sendUserMessage);
// userInput.addEventListener('keypress', (e) => {
//     if (e.key === 'Enter') sendUserMessage();
// });
//
// function sendUserMessage() {
//     const text = userInput.value.trim();
//     if (!text) return;
//     addMessage('user', text, formatTime());
//     userInput.value = '';
//     sendMessage(text);
// }
//
// async function sendMessage(message) {
//     const typingId = addTypingIndicator();
//     try {
//         const res = await fetch(`${API_BASE}/chat`, {
//             method: 'POST',
//             headers: { 'Content-Type': 'application/json' },
//             body: JSON.stringify({ user_id: USER_ID, message: message })
//         });
//         if (!res.ok) throw new Error(`HTTP ${res.status}`);
//         const data = await res.json();
//         removeTypingIndicator(typingId);
//         addMessage('ai', data.reply, formatTime());
//         if (currentRole) fetchAffection(currentRole);
//     } catch (err) {
//         removeTypingIndicator(typingId);
//         addMessage('ai', '😢 网络出小差了，请稍后再试~', formatTime());
//     }
// }
//
// function addMessage(type, text, time) {
//     const msgDiv = document.createElement('div');
//     msgDiv.className = `message ${type}`;
//     const avatar = document.createElement('div');
//     avatar.className = 'avatar';
//     avatar.innerText = type === 'ai' ? '🌸' : '😊';
//     const bubble = document.createElement('div');
//     bubble.className = 'bubble';
//     bubble.innerHTML = `<div>${escapeHtml(text)}</div><div class="time">${time}</div>`;
//     msgDiv.appendChild(avatar);
//     msgDiv.appendChild(bubble);
//     chatArea.appendChild(msgDiv);
//     chatArea.scrollTop = chatArea.scrollHeight;
// }
//
// function addTypingIndicator() {
//     const id = 'typing_' + Date.now();
//     const msgDiv = document.createElement('div');
//     msgDiv.className = 'message ai';
//     msgDiv.id = id;
//     const avatar = document.createElement('div');
//     avatar.className = 'avatar';
//     avatar.innerText = '🌸';
//     const bubble = document.createElement('div');
//     bubble.className = 'bubble';
//     bubble.innerText = '对方正在输入...';
//     msgDiv.appendChild(avatar);
//     msgDiv.appendChild(bubble);
//     chatArea.appendChild(msgDiv);
//     chatArea.scrollTop = chatArea.scrollHeight;
//     return id;
// }
//
// function removeTypingIndicator(id) {
//     const el = document.getElementById(id);
//     if (el) el.remove();
// }
//
// function formatTime() {
//     const now = new Date();
//     return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
// }
//
// function escapeHtml(text) {
//     const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
//     return text.replace(/[&<>"']/g, m => map[m]);
// }
//
// async function fetchAffection(role) {
//     if (!role) return;
//     try {
//         const res = await fetch(`${API_BASE}/affection/${USER_ID}/${encodeURIComponent(role)}`);
//         if (res.ok) {
//             const data = await res.json();
//             affectionEls.intimacy.textContent = Math.round(data.intimacy);
//             affectionEls.trust.textContent = Math.round(data.trust);
//             affectionEls.fun.textContent = Math.round(data.fun);
//             affectionEls.growth.textContent = Math.round(data.growth);
//             affectionEls.level.textContent = data.level;
//         }
//     } catch (e) {
//         console.warn('好感度获取失败', e);
//     }
// }



const API_BASE = "";
const USER_ID = "web_user_" + Math.random().toString(36).substr(2, 8);

// 角色定义（图片目前用大 emoji 展示，后续可替换为真实图片 URL）
const ROLES = [
  { type: "日系动漫型", name: "小樱", emoji: "🌸", desc: "二次元少女，精通动漫", img: "", colorClass: "img-sakura" },
  { type: "高冷御姐型", name: "雪乃", emoji: "❄️", desc: "成熟冷静的职场精英", img: "", colorClass: "img-yukino" },
  { type: "傲娇辣妹型", name: "凛", emoji: "💢", desc: "嘴硬心软的傲娇少女", img: "", colorClass: "img-rin" },
  { type: "甜美校花型", name: "甜甜", emoji: "🍬", desc: "温柔甜美的校园女神", img: "", colorClass: "img-tiantian" },
  { type: "软萌可爱型", name: "团子", emoji: "🍡", desc: "软萌胆小的小可爱", img: "", colorClass: "img-dango" },
  { type: "温柔贤淑型", name: "若兰", emoji: "🌿", desc: "大姐姐般温柔体贴", img: "", colorClass: "img-ruolan" }
];

let currentRoleType = null;

const homeView = document.getElementById('homeView');
const chatView = document.getElementById('chatView');
const roleCardsContainer = document.getElementById('roleCards');
const roleListEl = document.getElementById('roleList');
const chatArea = document.getElementById('chatArea');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const backBtn = document.getElementById('backBtn');
const newChatBtn = document.getElementById('newChatBtn');
const chatHeaderName = document.querySelector('.active-role-name');

// 渲染首页卡片
function renderHomeCards() {
  roleCardsContainer.innerHTML = '';
  ROLES.forEach(role => {
    const card = document.createElement('div');
    card.className = 'role-card-big';
    card.dataset.roleType = role.type;
    // 图片区域：如果有图片链接则显示图片，否则显示大 emoji
    const imgContent = role.img
      ? `<img class="card-img ${role.colorClass}" src="${role.img}" alt="${role.name}" onerror="this.style.display='none'; this.parentNode.innerHTML='<div class=\\'card-img ${role.colorClass}\\'>${role.emoji}</div>'">`
      : `<div class="card-img ${role.colorClass}">${role.emoji}</div>`;
    card.innerHTML = `
      ${imgContent}
      <div class="card-info">
        <div class="name">${role.emoji} ${role.name}</div>
        <div class="desc">${role.desc}</div>
      </div>
    `;
    card.addEventListener('click', () => enterChat(role.type));
    roleCardsContainer.appendChild(card);
  });
}

// 进入聊天
function enterChat(roleType) {
  const role = ROLES.find(r => r.type === roleType);
  if (!role) return;
  currentRoleType = roleType;
  homeView.classList.remove('active');
  chatView.classList.add('active');
  chatView.style.display = 'flex';  // 确保显示
  chatHeaderName.textContent = `与 ${role.name} 的对话`;
  chatArea.innerHTML = '';
  renderSidebarRoles();
  const autoMsg = `我想要一个${roleType}`;
  sendMessage(autoMsg, true);
}

// 返回首页
function goHome() {
  chatView.classList.remove('active');
  chatView.style.display = 'none';
  homeView.classList.add('active');
  currentRoleType = null;
  chatArea.innerHTML = '';
}

// 左侧角色列表
function renderSidebarRoles() {
  roleListEl.innerHTML = '';
  ROLES.forEach(role => {
    const card = document.createElement('div');
    card.className = `role-card${currentRoleType === role.type ? ' active' : ''}`;
    card.dataset.roleType = role.type;
    card.innerHTML = `
      <div class="role-avatar">${role.emoji}</div>
      <div class="role-info">
        <div class="role-name">${role.name}</div>
        <div class="role-preview">${role.desc}</div>
      </div>
    `;
    card.addEventListener('click', () => {
      if (currentRoleType === role.type) return;
      enterChat(role.type);
    });
    roleListEl.appendChild(card);
  });
}

// 新建对话
function newChat() {
  if (!currentRoleType) return;
  chatArea.innerHTML = '';
  const autoMsg = `我想要一个${currentRoleType}`;
  sendMessage(autoMsg, true);
}

// 发送消息（通用）
async function sendMessage(message, isSystem = false) {
  if (!isSystem) {
    addMessage('user', message, formatTime());
  }
  const typingEl = document.createElement('div');
  typingEl.className = 'typing-center';
  typingEl.innerText = '对方正在输入...';
  chatArea.appendChild(typingEl);
  chatArea.scrollTop = chatArea.scrollHeight;
  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: USER_ID, message: message })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    typingEl.remove();
    addMessage('ai', data.reply, formatTime());
    if (currentRoleType) fetchAffection(currentRoleType);
  } catch (err) {
    typingEl.remove();
    addMessage('ai', '😢 网络开小差了，请稍后再试~', formatTime());
  }
}

function sendUserMessage() {
  const text = userInput.value.trim();
  if (!text) return;
  if (!currentRoleType) {
    alert('请先选择一个角色');
    return;
  }
  userInput.value = '';
  sendMessage(text);
}

function addMessage(type, text, time) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${type}`;
  const avatarEmoji = type === 'ai'
    ? (ROLES.find(r => r.type === currentRoleType)?.emoji || '🌸')
    : '😊';
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.innerText = avatarEmoji;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<div>${escapeHtml(text)}</div><div class="time">${time}</div>`;
  msgDiv.appendChild(avatar);
  msgDiv.appendChild(bubble);
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
async function fetchAffection(roleType) {
  try { await fetch(`${API_BASE}/affection/${USER_ID}/${encodeURIComponent(roleType)}`); } catch(e){}
}

// 事件绑定
sendBtn.addEventListener('click', sendUserMessage);
userInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendUserMessage(); });
backBtn.addEventListener('click', goHome);
newChatBtn.addEventListener('click', newChat);

// 启动
renderHomeCards();
homeView.classList.add('active');