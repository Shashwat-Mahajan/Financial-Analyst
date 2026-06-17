import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

const API = "http://13.126.196.65:8000";

const roleBadge = {
  admin:   "bg-purple-500/20 text-purple-300 border-purple-500/30",
  analyst: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  viewer:  "bg-blue-500/20 text-blue-300 border-blue-500/30",
};

// ── Reusable drag and drop zone ───────────────────────────────────────────────
function DropZone({ accept, multiple = false, files, onFiles, icon, label, hint }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files).filter(f =>
      accept.some(ext => f.name.toLowerCase().endsWith(ext))
    );
    if (dropped.length) onFiles(multiple ? dropped : [dropped[0]]);
  };

  const handleChange = (e) => {
    const selected = Array.from(e.target.files);
    if (selected.length) onFiles(multiple ? selected : [selected[0]]);
  };

  return (
    <div>
      <div
        onClick={() => inputRef.current.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`w-full border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition select-none ${
          dragging
            ? "border-emerald-400 bg-emerald-500/10"
            : "border-slate-700 hover:border-emerald-500/50 hover:bg-slate-800/50"
        }`}
      >
        <div className="text-4xl mb-2">{icon}</div>
        <p className="text-slate-300 text-sm font-semibold">{label}</p>
        <p className="text-slate-500 text-xs mt-1">{hint}</p>
        <p className="text-slate-600 text-xs mt-2">or drag & drop here</p>
        <input
          ref={inputRef}
          type="file"
          accept={accept.join(",")}
          multiple={multiple}
          className="hidden"
          onChange={handleChange}
        />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="mt-3 space-y-1">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 bg-slate-950 rounded-lg px-3 py-2 group">
              <span className="text-emerald-400 text-xs">{accept.includes(".pdf") ? "📄" : "📋"}</span>
              <span className="text-slate-300 text-xs truncate flex-1">{f.name}</span>
              <span className="text-slate-500 text-xs">{(f.size / 1024).toFixed(1)}KB</span>
              <button
                onClick={() => onFiles(files.filter((_, idx) => idx !== i))}
                className="text-slate-600 hover:text-red-400 text-xs ml-1 transition"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [question, setQuestion]     = useState("");
  const [answer, setAnswer]         = useState("");
  const [sources, setSources]       = useState([]);
  const [urls, setUrls]             = useState("");
  const [status, setStatus]         = useState("");
  const [querying, setQuerying]     = useState(false);
  const [ingesting, setIngesting]   = useState(false);
  const [user, setUser]             = useState(null);
  const [ingestMode, setIngestMode] = useState("urls");
  const [files, setFiles]           = useState([]);
  const [ragStatus, setRagStatus]   = useState(null);
  const navigate                    = useNavigate();

  const token     = localStorage.getItem("token");
  const role      = localStorage.getItem("role");
  const canIngest = role === "analyst" || role === "admin";

  const fetchStatus = () =>
    fetch(`${API}/rag/status`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(setRagStatus).catch(() => {});

  useEffect(() => {
    if (!token) { navigate("/"); return; }
    fetch(`${API}/rag/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(setUser)
      .catch(() => { localStorage.clear(); navigate("/"); });
    fetchStatus();
  }, []);

  // ── Query ──────────────────────────────────────────────────────────────────
  const handleQuery = async () => {
    if (!question.trim()) return;
    setQuerying(true); setAnswer(""); setSources([]);
    try {
      const res  = await fetch(`${API}/rag/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setAnswer(data.answer);
      setSources(data.sources);
    } catch (err) {
      setAnswer(`Error: ${err.message}`);
    } finally {
      setQuerying(false);
    }
  };

  // ── Ingest URLs ────────────────────────────────────────────────────────────
  const handleIngestUrls = async () => {
    const urlList = urls.split("\n").map(u => u.trim()).filter(Boolean);
    if (!urlList.length) return;
    setIngesting(true); setStatus("");
    try {
      const res  = await fetch(`${API}/rag/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ urls: urlList }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setStatus(data.message);
      fetchStatus();
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setIngesting(false);
    }
  };

  // ── Ingest Files ──────────────────────────────────────────────────────────
  const handleIngestFiles = async () => {
    if (!files.length) return;
    setIngesting(true); setStatus("");
    try {
      const formData = new FormData();
      files.forEach(f => formData.append("files", f));
      const res  = await fetch(`${API}/rag/ingest-files`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setStatus(data.message);
      setFiles([]);
      fetchStatus();
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setIngesting(false);
    }
  };

  const logout = () => { localStorage.clear(); navigate("/"); };

  const modes = [
    { id: "urls", label: "🔗 URLs"     },
    { id: "pdf",  label: "📄 PDF"      },
    { id: "txt",  label: "📋 TXT File" },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-white">

      {/* Navbar */}
      <nav className="bg-slate-900 border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">💀</span>
          <span className="text-lg font-bold">Financial Analyst AI</span>
        </div>
        <div className="flex items-center gap-4">
          {user && (
            <>
              <span className={`text-xs font-semibold px-3 py-1 rounded-full border ${roleBadge[user.role]}`}>
                {user.role.toUpperCase()}
              </span>
              <span className="text-slate-400 text-sm hidden sm:block">{user.email}</span>
            </>
          )}
          <button onClick={logout} className="text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 px-4 py-1.5 rounded-lg transition">
            Logout
          </button>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto p-6 space-y-6">

        {/* Status Bar */}
        {ragStatus && (
          <div className="bg-slate-900 rounded-2xl border border-slate-800 p-5">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <h2 className="text-sm font-semibold text-slate-300">📊 System Status</h2>
              <div className="flex gap-4 text-xs text-slate-500 flex-wrap">
                <span>🗂 <span className="text-white font-semibold">{ragStatus.total_chunks}</span> chunks</span>
                <span>🔗 <span className="text-white font-semibold">{ragStatus.total_sources}</span> sources</span>
                <span>🔄 {ragStatus.last_refreshed}</span>
              </div>
            </div>

            {ragStatus.companies_detected.length > 0 && (
              <div className="mb-4">
                <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider font-semibold">Companies in system</p>
                <div className="flex flex-wrap gap-2">
                  {ragStatus.companies_detected.map(c => (
                    <span key={c} className="bg-blue-500/10 border border-blue-500/30 text-blue-300 text-xs px-3 py-1 rounded-full">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div>
              <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider font-semibold">Suggested questions — click to use</p>
              <div className="flex flex-wrap gap-2">
                {ragStatus.suggested_questions.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setQuestion(q)}
                    className="bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-500 text-slate-300 text-xs px-3 py-1.5 rounded-lg transition text-left"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Main panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Query Panel */}
          <div className="bg-slate-900 rounded-2xl border border-slate-800 p-6">
            <h2 className="text-lg font-semibold mb-4">💬 Ask a Question</h2>
            <textarea
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) handleQuery(); }}
              placeholder="What was Apple's revenue in Q3 2024?  (Ctrl+Enter to submit)"
              rows={4}
              className="w-full bg-slate-950 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition placeholder-slate-600"
            />
            <button
              onClick={handleQuery}
              disabled={querying || !question.trim()}
              className="mt-3 w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-xl transition text-sm flex items-center justify-center gap-2"
            >
              {querying ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                  </svg>
                  Thinking...
                </>
              ) : "🔍 Get Answer"}
            </button>

            {answer && (
              <div className="mt-5 bg-slate-950 rounded-xl border border-slate-800 p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-2 font-semibold">🧠 Answer</p>
                <p className="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">{answer}</p>
                {sources.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-slate-800">
                    <p className="text-xs text-slate-500 uppercase tracking-wider mb-2 font-semibold">📚 Sources</p>
                    {sources.map((s, i) => (
                      <a key={i} href={s} target="_blank" rel="noreferrer"
                        className="block text-blue-400 hover:text-blue-300 text-xs truncate mt-1 transition">
                        🔗 {s}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Ingest Panel */}
          <div className="bg-slate-900 rounded-2xl border border-slate-800 p-6">
            <h2 className="text-lg font-semibold mb-4">📥 Ingest Data</h2>

            {!canIngest ? (
              <div className="bg-slate-950 border border-slate-700 rounded-xl p-6 text-center">
                <div className="text-4xl mb-3">🔒</div>
                <p className="text-slate-300 font-semibold mb-1">Viewer Access</p>
                <p className="text-slate-500 text-sm mb-4">
                  You can query but cannot ingest new data.<br/>
                  Contact an admin to upgrade your role.
                </p>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  {[
                    { role: "Viewer",  color: "text-blue-400",    can: "Query only"      },
                    { role: "Analyst", color: "text-emerald-400", can: "Query + Ingest"  },
                    { role: "Admin",   color: "text-purple-400",  can: "Full access"     },
                  ].map(r => (
                    <div key={r.role} className="bg-slate-900 rounded-lg p-2 border border-slate-800">
                      <div className={`font-semibold ${r.color}`}>{r.role}</div>
                      <div className="text-slate-500 mt-0.5">{r.can}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {/* Mode tabs */}
                <div className="flex gap-2 mb-4">
                  {modes.map(m => (
                    <button
                      key={m.id}
                      onClick={() => { setIngestMode(m.id); setStatus(""); setFiles([]); }}
                      className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold transition border ${
                        ingestMode === m.id
                          ? "bg-emerald-600/20 border-emerald-500/50 text-emerald-300"
                          : "bg-slate-950 border-slate-700 text-slate-400 hover:border-slate-600"
                      }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>

                {/* URLs mode */}
                {ingestMode === "urls" && (
                  <>
                    <textarea
                      value={urls}
                      onChange={e => setUrls(e.target.value)}
                      placeholder={"https://finance.yahoo.com/...\nhttps://reuters.com/..."}
                      rows={6}
                      className="w-full bg-slate-950 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition placeholder-slate-600"
                    />
                    <button
                      onClick={handleIngestUrls}
                      disabled={ingesting || !urls.trim()}
                      className="mt-3 w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-xl transition text-sm flex items-center justify-center gap-2"
                    >
                      {ingesting ? (
                        <>
                          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                          </svg>
                          Ingesting...
                        </>
                      ) : "🚀 Process URLs"}
                    </button>
                  </>
                )}

                {/* PDF mode */}
                {ingestMode === "pdf" && (
                  <>
                    <DropZone
                      accept={[".pdf"]}
                      multiple={true}
                      files={files}
                      onFiles={setFiles}
                      icon="📄"
                      label="Click or drag & drop PDFs"
                      hint="Multiple PDF files supported"
                    />
                    <button
                      onClick={handleIngestFiles}
                      disabled={ingesting || !files.length}
                      className="mt-3 w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-xl transition text-sm flex items-center justify-center gap-2"
                    >
                      {ingesting ? (
                        <>
                          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                          </svg>
                          Processing...
                        </>
                      ) : `🚀 Process ${files.length || ""} PDF${files.length !== 1 ? "s" : ""}`}
                    </button>
                  </>
                )}

                {/* TXT mode */}
                {ingestMode === "txt" && (
                  <>
                    <DropZone
                      accept={[".txt"]}
                      multiple={false}
                      files={files}
                      onFiles={setFiles}
                      icon="📋"
                      label="Click or drag & drop .txt file"
                      hint="One URL per line inside the file"
                    />
                    <button
                      onClick={handleIngestFiles}
                      disabled={ingesting || !files.length}
                      className="mt-3 w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-xl transition text-sm flex items-center justify-center gap-2"
                    >
                      {ingesting ? (
                        <>
                          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                          </svg>
                          Processing...
                        </>
                      ) : "🚀 Process TXT File"}
                    </button>
                  </>
                )}

                {/* Status message */}
                {status && (
                  <div className={`mt-3 text-sm px-4 py-3 rounded-lg ${
                    status.startsWith("Error")
                      ? "bg-red-500/10 border border-red-500/30 text-red-400"
                      : "bg-emerald-500/10 border border-emerald-500/30 text-emerald-400"
                  }`}>
                    {status}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}