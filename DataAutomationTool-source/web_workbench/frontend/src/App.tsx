import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Download, FileInput, FolderOpen, Play, RotateCcw, Square, TerminalSquare } from "lucide-react";
import packageJson from "../package.json";
import {
  createTask,
  fetchJobs,
  fetchWorkspace,
  runAction,
  selectTask,
  WorkerError,
  type Job,
  type StepResult,
  type Workspace,
} from "./lib/api";

type PomeloItem = { country: string; asin: string; status: string; error: string };
type CurlKind = "wheat" | "pomeloKeywords";
type Notice = { tone: "ok" | "error" | "info"; text: string };

const actionNames: Record<string, string> = {
  pomelo_download: "柚子数据下载",
  wheat_connect: "麦子连通测试",
  wheat_download: "麦子拓展数据下载",
  pomelo_keywords_connect: "柚子关键词连通测试",
  pomelo_keywords_test_two_batches: "柚子关键词两批测试",
  pomelo_keywords_download: "柚子关键词全量下载",
};

function shortPath(value: string | null) {
  if (!value) return "未选择";
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function errorMessage(error: unknown) {
  if (error instanceof WorkerError) return error.message;
  if (error instanceof Error) return error.message;
  return "操作失败";
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [taskName, setTaskName] = useState("");
  const [pomeloInput, setPomeloInput] = useState<string | null>(null);
  const [pomeloItems, setPomeloItems] = useState<PomeloItem[]>([]);
  const [keywordInput, setKeywordInput] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [stoppingJob, setStoppingJob] = useState<string | null>(null);
  const [step0Notice, setStep0Notice] = useState<Notice>({ tone: "info", text: "请新建任务或选择已有任务。" });
  const [step0Expanded, setStep0Expanded] = useState(true);
  const [operationNotice, setOperationNotice] = useState<Notice | null>(null);
  const [curlKind, setCurlKind] = useState<CurlKind | null>(null);
  const [curlText, setCurlText] = useState("");

  const taskDir = workspace?.currentTask || null;
  const activeJob = useMemo(() => jobs.find((job) => ["queued", "running", "stopping"].includes(job.status)), [jobs]);
  const visibleJobs = useMemo(() => {
    const relevant = jobs.filter((job) => ["queued", "running", "stopping"].includes(job.status) || job.allowedAction);
    return Array.from(new Map(relevant.map((job) => [job.id, job])).values());
  }, [jobs]);

  async function refreshWorkspace() {
    setWorkspace(await fetchWorkspace());
  }

  async function refreshJobs() {
    if (!taskDir) return;
    const result = await fetchJobs();
    setJobs(result.items);
  }

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    const connect = async () => {
      while (!cancelled && attempts < 30) {
        attempts += 1;
        try {
          const next = await fetchWorkspace();
          if (!cancelled) setWorkspace(next);
          return;
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 300));
        }
      }
      if (!cancelled) setOperationNotice({ tone: "error", text: "本地服务未连接，请重启程序。" });
    };
    void connect();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!taskDir) return;
    void refreshJobs().catch(() => undefined);
    const timer = window.setInterval(() => void refreshJobs().catch(() => undefined), 1000);
    return () => window.clearInterval(timer);
  }, [taskDir]);

  async function execute(label: string, operation: () => Promise<void>, updateNotice: (notice: Notice) => void = setOperationNotice) {
    if (busy) return;
    setBusy(label);
    updateNotice({ tone: "info", text: `${label}执行中…` });
    try {
      await operation();
    } catch (error) {
      updateNotice({ tone: "error", text: errorMessage(error) });
    } finally {
      setBusy(null);
      void refreshJobs().catch(() => undefined);
    }
  }

  function resetTaskInputs() {
    setPomeloInput(null);
    setPomeloItems([]);
    setKeywordInput(null);
    setJobs([]);
    setOperationNotice(null);
  }

  async function handleCreateTask() {
    const name = taskName.trim();
    if (!name) return;
    const parentDir = await window.automationTool?.selectNewTaskParentDirectory();
    if (!parentDir) return;
    await execute("新建任务", async () => {
      await createTask(name, parentDir);
      await refreshWorkspace();
      setTaskName("");
      resetTaskInputs();
      setStep0Notice({ tone: "ok", text: "任务已创建。请填写 ASIN 输入表。" });
    }, setStep0Notice);
  }

  async function handleSelectTask() {
    const selected = await window.automationTool?.selectTaskDirectory();
    if (!selected) return;
    await execute("选择任务", async () => {
      await selectTask(selected);
      await refreshWorkspace();
      resetTaskInputs();
      setStep0Notice({ tone: "ok", text: "已载入本地任务。" });
    }, setStep0Notice);
  }

  async function choosePomeloInput() {
    if (!taskDir) return;
    const selected = await window.automationTool?.selectInput("pomelo", taskDir);
    if (!selected?.ok || !selected.paths?.[0]) return;
    await execute("读取 Step 1 任务", async () => {
      const result = await runAction("step1", "pomelo_parse", { sourcePath: selected.paths![0] });
      const items = Array.isArray(result.data?.items) ? result.data.items as PomeloItem[] : [];
      setPomeloInput(selected.paths![0]);
      setPomeloItems(items);
      setOperationNotice({ tone: "ok", text: `已读取 ${items.length} 条，其中 ${items.filter((item) => item.status !== "已跳过").length} 条可下载。` });
    });
  }

  async function chooseKeywordInput() {
    if (!taskDir) return;
    const selected = await window.automationTool?.selectInput("pomeloKeywords", taskDir);
    if (selected?.ok && selected.paths?.[0]) {
      setKeywordInput(selected.paths[0]);
      setOperationNotice({ tone: "ok", text: `关键词档案：${shortPath(selected.paths[0])}` });
    }
  }

  async function handleRun(stepId: string, actionId: string, payload: Record<string, unknown> = {}) {
    await execute(actionNames[actionId] || actionId, async () => {
      handleResult(await runAction(stepId, actionId, payload));
    });
  }

  function handleResult(result: StepResult) {
    if (result.data?.items && Array.isArray(result.data.items)) setPomeloItems(result.data.items as PomeloItem[]);
    setOperationNotice({
      tone: result.ok ? "ok" : "error",
      text: result.status === "resumable" ? "下载已暂停，原始档案与断点均已保留。" : result.message,
    });
  }

  async function saveCurl() {
    if (!curlKind || !taskDir || !curlText.trim()) return;
    const result = await window.automationTool?.saveCurl(curlKind, taskDir, curlText);
    if (result?.ok) {
      setCurlKind(null);
      setCurlText("");
      setOperationNotice({ tone: "ok", text: "cURL 已保存到当前本地任务。" });
    } else if (!result?.cancelled) {
      setOperationNotice({ tone: "error", text: "cURL 保存失败，请确认内容以 curl 开头。" });
    }
  }

  async function controlJob(job: Job, action: "stop" | "resume" | "restart") {
    const bridge = window.automationTool;
    if (!bridge) return;
    if (action === "stop") {
      if (stoppingJob) return;
      setStoppingJob(job.id);
      setOperationNotice({ tone: "info", text: "已请求停止；当前分页或 ASIN 保存后会安全停下。" });
      try {
        await bridge.stopJob(job.id);
        await refreshJobs();
      } catch (error) {
        setOperationNotice({ tone: "error", text: errorMessage(error) });
      } finally {
        setStoppingJob(null);
      }
      return;
    }
    await execute(action === "resume" ? "继续任务" : "重启任务", async () => {
      const result = action === "resume" ? await bridge.resumeJob(job.id) : await bridge.restartJob(job.id);
      handleResult(result);
    });
  }

  const disabled = !taskDir || Boolean(busy) || Boolean(activeJob);
  const runnablePomelo = pomeloItems.filter((item) => item.status !== "已跳过");

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-6 py-8">
      <header className="mb-5 flex items-center justify-between gap-6">
        <h1 className="text-3xl font-black tracking-tight text-slate-950">资料自动化工具</h1>
        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-500">v{packageJson.version}</span>
      </header>

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="running-status-title">
        <h2 id="running-status-title" className="text-lg font-black text-slate-950">任务运行状态</h2>
        {operationNotice && <NoticeBanner notice={operationNotice} />}
        <div className={`${operationNotice ? "mt-4 border-t border-slate-100 pt-4" : "mt-3"}`}>
          {visibleJobs.length === 0 ? (
            <p className="text-sm text-slate-500">当前没有运行中或可继续的任务。</p>
          ) : (
            <div role="list" aria-label="可操作任务" className="h-40 space-y-2 overflow-y-auto pr-1">
              {visibleJobs.map((job) => (
                <div key={job.id} role="listitem" className="flex h-12 items-center gap-3 whitespace-nowrap rounded-lg bg-slate-50 px-4 text-sm">
                  <span className="font-semibold text-slate-800">{actionNames[job.actionId] || job.actionId}</span>
                  <span className="text-slate-500">{job.status} · {job.completed}/{job.total || "?"}</span>
                  <div className="ml-auto flex gap-2">
                    {["running", "queued"].includes(job.status) && <ActionButton kind="danger" onClick={() => void controlJob(job, "stop")} disabled={stoppingJob === job.id}><Square className="h-3 w-3" />{stoppingJob === job.id ? "停止中" : "停止"}</ActionButton>}
                    {job.allowedAction === "resume" && <ActionButton kind="secondary" onClick={() => void controlJob(job, "resume")} disabled={Boolean(busy)}><Play className="h-3 w-3" />继续</ActionButton>}
                    {job.allowedAction === "restart" && <ActionButton kind="secondary" onClick={() => void controlJob(job, "restart")} disabled={Boolean(busy)}><RotateCcw className="h-3 w-3" />重启</ActionButton>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="step0-title">
        <div className="flex items-start justify-between gap-4">
          <StepHeading number="0" title="建立项目" id="step0-title" />
          <button
            type="button"
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            onClick={() => setStep0Expanded((expanded) => !expanded)}
            aria-expanded={step0Expanded}
            aria-controls="step0-content"
          >
            {step0Expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            {step0Expanded ? "收合" : "展开"}
          </button>
        </div>
        {step0Expanded && (
          <div id="step0-content">
            <NoticeBanner notice={step0Notice} />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <input className="h-10 min-w-64 flex-1 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-blue-500" value={taskName} onChange={(event) => setTaskName(event.target.value)} placeholder="输入新任务名，例如 iphone_case_us" />
              <ActionButton onClick={() => void handleCreateTask()} disabled={!taskName.trim() || Boolean(busy)}>新建任务并选择位置</ActionButton>
              <ActionButton kind="secondary" onClick={() => void handleSelectTask()} disabled={Boolean(busy)}><FolderOpen className="h-4 w-4" />选择已有任务</ActionButton>
            </div>
            <p className="mt-3 break-all text-xs text-slate-500">当前任务：{taskDir || "未选择"}</p>
            <div className="mt-5 border-t border-slate-200 pt-5">
              <h3 className="text-base font-black text-slate-950">ASIN 输入表</h3>
              <ol className="instruction-list mt-4">
                <li><strong>国家</strong>：填写站点代码，例如 US。</li>
                <li><strong>竞品ASIN</strong>：每行填写一个 ASIN。</li>
                <li><strong>竞品强弱</strong>：填写“强”或“弱”。</li>
              </ol>
              <ActionButton kind="secondary" onClick={() => taskDir && void window.automationTool?.openAsinWorkbook(taskDir)} disabled={!taskDir}><FileInput className="h-4 w-4" />打开 ASIN 输入表</ActionButton>
            </div>
          </div>
        )}
      </section>

      <section className="grid gap-5 lg:grid-cols-3">
        <StepCard number="1" title="柚子数据下载">
          <p className="file-chip">任务档案：{shortPath(pomeloInput)}</p>
          <div className="button-row">
            <ActionButton kind="secondary" onClick={() => void choosePomeloInput()} disabled={disabled}>选择并读取任务</ActionButton>
            <ActionButton kind="secondary" onClick={() => void window.automationTool?.launchDebugChrome()} disabled={Boolean(busy)}><TerminalSquare className="h-4 w-4" />启动 Chrome</ActionButton>
          </div>
          <ActionButton onClick={() => void handleRun("step1", "pomelo_download", { items: runnablePomelo })} disabled={disabled || runnablePomelo.length === 0}><Download className="h-4 w-4" />开始下载（{runnablePomelo.length}）</ActionButton>
          <ActionButton kind="ghost" onClick={() => taskDir && void window.automationTool?.openOutput("pomelo", taskDir)} disabled={!taskDir}>查看下载档案</ActionButton>
        </StepCard>

        <StepCard number="2" title="麦子拓展数据下载">
          <ActionButton kind="secondary" onClick={() => setCurlKind("wheat")} disabled={disabled}>粘贴麦子 cURL</ActionButton>
          <div className="button-row">
            <ActionButton kind="secondary" onClick={() => void handleRun("step2", "wheat_connect")} disabled={disabled}>连通测试</ActionButton>
            <ActionButton onClick={() => void handleRun("step2", "wheat_download")} disabled={disabled}><Download className="h-4 w-4" />全量下载</ActionButton>
          </div>
          <ActionButton kind="ghost" onClick={() => taskDir && void window.automationTool?.openOutput("wheat", taskDir)} disabled={!taskDir}>查看原始档案</ActionButton>
        </StepCard>

        <StepCard number="9" title="柚子关键词下载">
          <p className="file-chip">关键词：{shortPath(keywordInput)}</p>
          <div className="button-row">
            <ActionButton kind="secondary" onClick={() => void chooseKeywordInput()} disabled={disabled}>选择关键词档案</ActionButton>
            <ActionButton kind="secondary" onClick={() => setCurlKind("pomeloKeywords")} disabled={disabled}>粘贴 cURL</ActionButton>
          </div>
          <div className="button-row">
            <ActionButton kind="secondary" onClick={() => keywordInput && void handleRun("step9", "pomelo_keywords_connect", { keywordsPath: keywordInput })} disabled={disabled || !keywordInput}>连通测试</ActionButton>
            <ActionButton kind="secondary" onClick={() => keywordInput && void handleRun("step9", "pomelo_keywords_test_two_batches", { keywordsPath: keywordInput })} disabled={disabled || !keywordInput}>测试 2 批</ActionButton>
          </div>
          <ActionButton onClick={() => {
            if (keywordInput && window.confirm("确认开始全量下载？请求次数取决于关键词数量。")) void handleRun("step9", "pomelo_keywords_download", { keywordsPath: keywordInput, confirmFull: true });
          }} disabled={disabled || !keywordInput}><Download className="h-4 w-4" />全量下载</ActionButton>
          <ActionButton kind="ghost" onClick={() => taskDir && void window.automationTool?.openOutput("pomeloKeywords", taskDir)} disabled={!taskDir}>查看原始档案</ActionButton>
        </StepCard>
      </section>

      {curlKind && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-6" role="dialog" aria-modal="true">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl">
            <h2 className="text-lg font-bold">粘贴 {curlKind === "wheat" ? "麦子拓展" : "柚子关键词"} cURL</h2>
            <p className="mt-2 text-sm text-amber-700">cURL 可能包含 Cookie。它只会写入当前任务，请勿提交到 Git。</p>
            <textarea className="mt-4 h-56 w-full resize-none rounded-lg border border-slate-300 p-3 font-mono text-xs outline-none focus:border-blue-500" value={curlText} onChange={(event) => setCurlText(event.target.value)} placeholder="curl 'https://…' -H '…' --data-raw '…'" />
            <div className="mt-4 flex justify-end gap-2">
              <ActionButton kind="secondary" onClick={() => { setCurlKind(null); setCurlText(""); }}>取消</ActionButton>
              <ActionButton onClick={() => void saveCurl()} disabled={!curlText.trim()}>保存到本机</ActionButton>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function NoticeBanner({ notice }: { notice: Notice }) {
  const tone = notice.tone === "error"
    ? "border-red-200 bg-red-50 text-red-800"
    : notice.tone === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : "border-blue-200 bg-blue-50 text-blue-800";
  return <div className={`mt-3 rounded-xl border px-4 py-3 text-sm ${tone}`}>{notice.text}</div>;
}

function StepHeading({ number, title, id }: { number: string; title: string; id?: string }) {
  return (
    <div>
      <span className="text-xs font-bold uppercase tracking-widest text-blue-700">Step {number}</span>
      <h2 id={id} className="mt-1 text-xl font-black text-slate-950">{title}</h2>
    </div>
  );
}

function StepCard({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return (
    <article className="flex min-h-72 flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <StepHeading number={number} title={title} />
      <div className="mt-2 flex flex-1 flex-col gap-3">{children}</div>
    </article>
  );
}

function ActionButton({ children, onClick, disabled = false, kind = "primary" }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; kind?: "primary" | "secondary" | "ghost" | "danger" }) {
  const styles = kind === "primary"
    ? "bg-blue-700 text-white hover:bg-blue-800"
    : kind === "danger"
      ? "bg-red-600 text-white hover:bg-red-700"
      : kind === "ghost"
        ? "border border-transparent bg-slate-100 text-slate-700 hover:bg-slate-200"
        : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50";
  return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex min-h-9 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}>{children}</button>;
}
