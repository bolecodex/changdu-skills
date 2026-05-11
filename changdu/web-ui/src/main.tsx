import React from "react";
import { createRoot } from "react-dom/client";
import { Play, RefreshCw, Save, Search } from "lucide-react";
import "./styles.css";

type Clip = { index: number; label: string; promptPath: string; status: "missing" | "ready" | "done" };
type Artifact = { name: string; path: string; kind: "video" | "image" | "text" | "other"; url?: string };
type Project = { id: string; root: string; promptDir: string; outputDir: string; clips: Clip[]; artifacts: Artifact[] };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function listFromText(value: string): string[] {
  return value.split(/\n+/).map((item) => item.trim()).filter(Boolean);
}

function App() {
  const [projectName, setProjectName] = React.useState("我的短剧");
  const [script, setScript] = React.useState("");
  const [outputRoot, setOutputRoot] = React.useState("outputs/web-projects");
  const [root, setRoot] = React.useState("");
  const [project, setProject] = React.useState<Project | null>(null);
  const [selected, setSelected] = React.useState<Clip | null>(null);
  const [prompt, setPrompt] = React.useState("");
  const [issues, setIssues] = React.useState("先创建或加载一个项目。");
  const [log, setLog] = React.useState("");
  const [jobState, setJobState] = React.useState("暂无任务。");
  const [images, setImages] = React.useState("");
  const [assets, setAssets] = React.useState("");
  const [promptHeader, setPromptHeader] = React.useState("");

  async function createFromScript() {
    if (!script.trim()) throw new Error("请先输入剧本。");
    const data = await api<Project>("/api/projects/from-script", {
      method: "POST",
      body: JSON.stringify({
        projectName,
        script,
        outputRoot,
        targetClipCount: Number((document.getElementById("targetClipCount") as HTMLInputElement).value),
        style: (document.getElementById("scriptStyle") as HTMLInputElement).value
      })
    });
    setProject(data);
    setRoot(data.promptDir);
    setSelected(data.clips[0] || null);
    if (data.clips[0]) await chooseClip(data, data.clips[0]);
  }

  async function loadProject() {
    const data = await api<Project>(`/api/projects?root=${encodeURIComponent(root)}`);
    setProject(data);
    setSelected(data.clips[0] || null);
    if (data.clips[0]) await chooseClip(data, data.clips[0]);
  }

  async function chooseClip(activeProject: Project, clip: Clip) {
    setSelected(clip);
    const body = await api<{ text: string }>(`/api/prompts/${activeProject.id}/${clip.label}`);
    setPrompt(body.text);
  }

  async function savePrompt() {
    if (!project || !selected) return;
    await api(`/api/prompts/${project.id}/${selected.label}`, {
      method: "PUT",
      body: JSON.stringify({ text: prompt })
    });
  }

  async function checkPrompts() {
    if (!project) return;
    setIssues("检查中...");
    const body = await api<{ raw: string }>("/api/prompt-check", {
      method: "POST",
      body: JSON.stringify({ promptDir: project.promptDir })
    });
    setIssues(body.raw || "无输出。");
  }

  async function startGenerate() {
    if (!project) return;
    const job = await api<{ id: string }>("/api/jobs/sequential-generate", {
      method: "POST",
      body: JSON.stringify({
        promptDir: project.promptDir,
        outputDir: project.outputDir,
        images: listFromText(images),
        assets: listFromText(assets),
        ratio: (document.getElementById("ratio") as HTMLSelectElement).value,
        duration: Number((document.getElementById("duration") as HTMLInputElement).value),
        continuityMode: (document.getElementById("continuity") as HTMLSelectElement).value,
        prevTailSeconds: Number((document.getElementById("tailSeconds") as HTMLInputElement).value),
        promptHeader
      })
    });
    setLog("");
    pollJob(job.id);
  }

  async function pollJob(id: string, offset = 0) {
    const job = await api<{ type: string; status: string; exitCode?: number }>(`/api/jobs/${id}`);
    const logs = await api<{ chunk: string; nextOffset: number }>(`/api/jobs/${id}/logs?offset=${offset}`);
    setJobState(`${job.type} · ${job.status}${job.exitCode == null ? "" : ` · exit ${job.exitCode}`}`);
    setLog((prev) => prev + logs.chunk);
    if (job.status === "queued" || job.status === "running") {
      window.setTimeout(() => pollJob(id, logs.nextOffset), 1500);
    }
  }

  return (
    <main>
      <section className="panel">
        <h1>Changdu Web 制作台</h1>
        <p>输入剧本，生成中间产物、分镜 prompt、视频片段和最终成片。</p>
      </section>
      <section className="layout">
        <aside className="panel">
          <h2>新建制作项目</h2>
          <input value={projectName} onChange={(e) => setProjectName(e.target.value)} />
          <input value={outputRoot} onChange={(e) => setOutputRoot(e.target.value)} />
          <input id="targetClipCount" type="number" defaultValue={6} min={1} max={30} />
          <input id="scriptStyle" defaultValue="电影写实" />
          <textarea value={script} onChange={(e) => setScript(e.target.value)} placeholder="粘贴完整剧本" />
          <button onClick={createFromScript}><Play size={16} />从剧本创建项目</button>
          <h2>打开已有项目</h2>
          <div className="toolbar">
            <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder="项目目录" />
            <button onClick={loadProject}><RefreshCw size={16} />加载</button>
          </div>
          {project?.clips.map((clip) => (
            <button key={clip.label} className={selected?.label === clip.label ? "active" : ""} onClick={() => chooseClip(project, clip)}>
              {clip.label}<span>{clip.status}</span>
            </button>
          ))}
          <button onClick={checkPrompts}><Search size={16} />批量检查</button>
          <pre>{issues}</pre>
        </aside>
        <section className="panel">
          <h2>{selected?.label || "Prompt 工作区"}</h2>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button onClick={savePrompt}><Save size={16} />保存 Prompt</button>
        </section>
        <aside className="panel">
          <h2>生成 Clip</h2>
          <select id="ratio"><option>16:9</option><option>9:16</option><option>1:1</option></select>
          <input id="duration" type="number" defaultValue={15} />
          <select id="continuity"><option value="auto">auto</option><option value="ref_video">ref_video</option><option value="first_frame">first_frame</option></select>
          <input id="tailSeconds" type="number" defaultValue={5} />
          <textarea value={images} onChange={(e) => setImages(e.target.value)} placeholder="共享图片路径，每行一个" />
          <textarea value={assets} onChange={(e) => setAssets(e.target.value)} placeholder="Asset ID，每行一个" />
          <textarea value={promptHeader} onChange={(e) => setPromptHeader(e.target.value)} placeholder="Prompt Header" />
          <button onClick={startGenerate}><Play size={16} />开始连续生成</button>
          <h2>任务日志</h2>
          <p>{jobState}</p>
          <pre>{log}</pre>
          <h2>中间产物与成片</h2>
          {project?.artifacts.slice(-10).map((artifact) => (
            <div key={artifact.path} className="artifact">
              <strong>{artifact.name}</strong>
              {artifact.kind === "video" && <video src={artifact.url} controls />}
              {artifact.kind === "image" && <img src={artifact.url} alt={artifact.name} />}
              {artifact.kind === "text" && <a href={artifact.url} target="_blank">打开文本</a>}
            </div>
          ))}
        </aside>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
