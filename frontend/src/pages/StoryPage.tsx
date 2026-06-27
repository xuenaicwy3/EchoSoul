import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useRoleStore } from "../store/roleStore";

interface Starter { category: string; title: string; description: string; starter_text: string; options: { id: number; text: string }[]; }
interface StoryNode { content?: string; story_text?: string; choices?: { id: number; text: string }[]; suggestions?: { id: number; text: string }[]; }
interface ReplayNode { content: string; type?: string; }

const TOKEN = () => localStorage.getItem("echosoul_token") || "";
const api = async (url: string, opts: RequestInit = {}) => {
  const ctrl = new AbortController(); const id = setTimeout(() => ctrl.abort(), 25000);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal, headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN()}`, ...opts.headers } });
    clearTimeout(id); return res;
  } catch { clearTimeout(id); throw Error(); }
};
const escapeHtml = (t: string) => String(t).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" } as Record<string,string>)[m]);

export default function StoryPage() {
  const navigate = useNavigate();
  const { selectedRole } = useRoleStore();
  const role = selectedRole || "日系动漫型";

  const [starters, setStarters] = useState<Starter[]>([]);
  const [storyId, setStoryId] = useState<number | null>(null);
  const [nodes, setNodes] = useState<StoryNode[]>([]);
  const [userActions, setUserActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [showReplay, setShowReplay] = useState(false);
  const [replayNodes, setReplayNodes] = useState<ReplayNode[]>([]);
  const msgRef = useRef<HTMLDivElement>(null);

  useEffect(() => { loadStarters(); }, []);
  useEffect(() => { if (msgRef.current) msgRef.current.scrollTop = msgRef.current.scrollHeight; }, [nodes, userActions]);

  const loadStarters = async () => {
    try { const r = await api("/story/starters"); if (r.ok) setStarters(await r.json()); } catch {}
  };

  const startStory = async (s: Starter) => {
    setLoading(true); setUserActions([]);
    try {
      const r = await api("/story/start", { method: "POST", body: JSON.stringify({ role_type: role, title: s.title, starter_text: s.starter_text, options: s.options }) });
      const d = await r.json(); setStoryId(d.story_id); setNodes([d.first_node]); setLoading(false);
    } catch { setLoading(false); }
  };

  const progress = async (type: string, choiceId?: number, freeText?: string) => {
    if (!storyId) return;
    if (type === "choice") {
      const last = nodes[nodes.length - 1];
      const opts = last?.choices || last?.suggestions || [];
      const c = opts.find((x) => x.id === choiceId);
      if (c) setUserActions((a) => [...a, c.text]);
    } else if (type === "free_text" && freeText) {
      setUserActions((a) => [...a, freeText]);
    }
    setLoading(true);
    try {
      const body: Record<string,unknown> = { type };
      if (type === "choice") body.choice_id = choiceId;
      if (type === "free_text") body.free_text = freeText;
      if (type === "auto") body.auto_hint = null;
      const r = await api(`/story/${storyId}/progress`, { method: "POST", body: JSON.stringify(body) });
      const d = await r.json(); setNodes((p) => [...p, d]); setLoading(false);
    } catch { setLoading(false); }
  };

  const doArchive = async () => { if (!storyId) return; await api(`/story/${storyId}/archive`, { method: "PUT" }); alert("已存档"); };
  const doReplay = async () => {
    if (!storyId) return;
    const r = await api(`/story/${storyId}`);
    if (r.ok) { const d = await r.json(); setReplayNodes(d.nodes || []); setShowReplay(true); }
  };
  const doDelete = async () => {
    if (!storyId || !confirm("确定删除？")) return;
    await api(`/story/${storyId}`, { method: "DELETE" });
    setStoryId(null); setNodes([]); setUserActions([]);
  };

  const lastNode = nodes[nodes.length - 1];
  const choices = lastNode?.choices || lastNode?.suggestions || [];

  // 回放视图
  if (showReplay) {
    return (
      <div style={{ minHeight:"100vh", background:"linear-gradient(135deg,#ffd6e0 0%,#ffb3c6 100%)", display:"flex", justifyContent:"center", alignItems:"center" }}>
        <div className="story-app">
          <header className="story-header"><a href="#" onClick={(e)=>{e.preventDefault();setShowReplay(false);}}>← 返回故事</a><h1>📖 故事回放</h1><div className="header-placeholder"/></header>
          <div className="replay-container">
            {replayNodes.map((n,i)=>(
              <div key={i} className="story-msg">
                <div className="label">{n.type==="user_input"?"👤 选择":"📖 剧情"}</div>
                <div className="text" dangerouslySetInnerHTML={{__html:escapeHtml(n.content)}}/>
              </div>
            ))}
          </div>
          <button className="btn-primary" style={{margin:"20px auto",display:"block",background:"#e5989b",color:"#fff",border:"none",padding:"10px 24px",borderRadius:"24px",fontSize:"1rem",cursor:"pointer"}} onClick={()=>setShowReplay(false)}>返回故事</button>
        </div>
      </div>
    );
  }

  // 起点视图
  if (!storyId) {
    return (
      <div style={{ minHeight:"100vh", background:"linear-gradient(135deg,#ffd6e0 0%,#ffb3c6 100%)", display:"flex", justifyContent:"center", alignItems:"center" }}>
        <div className="story-app">
          <header className="story-header">
            <a href="#" onClick={(e)=>{e.preventDefault();navigate("/chat");}}>← 返回聊天</a>
            <h1>📖 故事工坊</h1>
            <div className="header-placeholder"/>
          </header>
          <div className="story-view-active">
            <div className="starters-grid">
              {starters.map((s,i)=>(
                <div key={i} className="starter-card" onClick={()=>startStory(s)}>
                  <span className="category">{s.category}</span>
                  <h3>{s.title}</h3>
                  <p>{s.description}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 故事进行中
  return (
    <div style={{ minHeight:"100vh", background:"linear-gradient(135deg,#ffd6e0 0%,#ffb3c6 100%)", display:"flex", justifyContent:"center", alignItems:"center" }}>
      <div className="story-app">
        <header className="story-header">
          <a href="#" onClick={(e)=>{e.preventDefault();navigate("/chat");}}>← 返回聊天</a>
          <h1>📖 故事工坊</h1>
          <div className="header-placeholder"/>
        </header>

        {loading ? (
          <div className="loading-skeleton">
            <div className="skeleton-line long"/><div className="skeleton-line"/><div className="skeleton-line medium"/><div className="skeleton-line short"/>
            <div className="skeleton-choices">
              <div className="skeleton-btn"/><div className="skeleton-btn"/><div className="skeleton-btn"/>
            </div>
          </div>
        ) : (
          <>
            <div className="story-messages" ref={msgRef}>
              {nodes.map((n,i)=>(
                <div key={i} className="story-msg">
                  <div className="label">📖 剧情</div>
                  <div className="text" dangerouslySetInnerHTML={{__html:escapeHtml(n.content||n.story_text||"")}}/>
                </div>
              ))}
              {userActions.map((a,i)=>(
                <div key={`ua-${i}`} className="story-msg user_action">
                  <div className="label">👤 你的行动</div>
                  <div className="text">{escapeHtml(a)}</div>
                </div>
              ))}
            </div>

            {choices.length > 0 && (
              <div className="story-suggestions">
                {choices.map((c)=>(
                  <button key={c.id} className="suggestion-btn" onClick={()=>progress("choice",c.id)} disabled={loading}>{c.text}</button>
                ))}
              </div>
            )}

            <div className="story-free-input">
              <input type="text" placeholder="✍️ 输入你想说的话或行动..." onKeyDown={(e)=>{if(e.key==="Enter"){progress("free_text",undefined,e.currentTarget.value);e.currentTarget.value="";}}}/>
              <button className="btn-send" onClick={()=>{const el=document.querySelector(".story-free-input input") as HTMLInputElement;if(el?.value){progress("free_text",undefined,el.value);el.value="";}}}>发送</button>
            </div>

            <button className="btn-auto" onClick={()=>progress("auto")} disabled={loading}>✨ AI 自动续写</button>

            <div className="story-actions">
              <button className="btn-secondary" onClick={doArchive}>📁 存档</button>
              <button className="btn-secondary" onClick={doReplay}>🔄 回放</button>
              <button className="btn-secondary btn-danger" onClick={doDelete}>🗑️ 删除</button>
            </div>

            <button className="btn-back" onClick={()=>{setStoryId(null);setNodes([]);setUserActions([]);}}>← 返回故事列表</button>
          </>
        )}
      </div>
    </div>
  );
}
