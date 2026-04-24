"use client";

import {
  Activity,
  Captions,
  CheckCircle2,
  ChevronRight,
  Clapperboard,
  Clock3,
  Film,
  FolderOpen,
  ImagePlus,
  Layers3,
  Music2,
  Play,
  Plus,
  Settings2,
  Sparkles,
  Upload
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Project = {
  id: string;
  title: string;
  topic: string;
  target_duration: number;
  target_ratio: string;
  language: string;
  style: string;
  platform: string;
  status: string;
  script_text: string | null;
  optimized_prompt: string | null;
  prompt_optimization_notes: string[];
};

type Shot = {
  id: string;
  order_index: number;
  title: string;
  prompt: string;
  duration_seconds: number;
  status: string;
};

type GenerationTask = {
  id: string;
  shot_id: string | null;
  model: string;
  status: string;
  provider_task_id: string | null;
  result_asset_id: string | null;
  error_message: string | null;
  request_payload: Record<string, unknown>;
};

type Timeline = {
  id: string;
  version: number;
  duration_seconds: number;
  segments: Array<Record<string, unknown>>;
};

type RenderJob = {
  id: string;
  status: string;
  profile: string;
  output_uri: string | null;
  error_message: string | null;
  ffmpeg_plan: {
    profile?: string;
    commands?: Array<{ name: string; argv: string[] }>;
  };
};

const services = [
  { label: "后端 API", value: "localhost:8000" },
  { label: "Redis", value: "localhost:6379" },
  { label: "MinIO", value: "localhost:9001" },
  { label: "PostgreSQL", value: "localhost:5432" }
];

const statusLabels: Record<string, string> = {
  draft: "草稿",
  planning: "规划中",
  generating: "生成中",
  assembling: "组装中",
  rendering: "渲染中",
  completed: "已完成",
  failed: "失败",
  planned: "已规划",
  queued: "已排队",
  running: "运行中",
  succeeded: "成功"
};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return (await response.json()) as T;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [tasks, setTasks] = useState<GenerationTask[]>([]);
  const [timelines, setTimelines] = useState<Timeline[]>([]);
  const [renderJobs, setRenderJobs] = useState<RenderJob[]>([]);
  const [isLoadingProjects, setIsLoadingProjects] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPipelineBusy, setIsPipelineBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? projects[0] ?? null,
    [projects, selectedProjectId]
  );

  const workflow = [
    { label: "项目", detail: "标题、主题、脚本和画幅", icon: Clapperboard, done: Boolean(selectedProject) },
    { label: "提示词优化", detail: "生成适合 Seedance 的主提示词", icon: Sparkles, done: Boolean(selectedProject?.optimized_prompt) },
    { label: "Seedance 分镜", detail: "自动拆成可生成的镜头提示词", icon: Layers3, done: shots.length > 0 },
    { label: "生成任务", detail: "火山方舟 Seedance 提交与轮询", icon: Sparkles, done: tasks.length > 0 },
    { label: "时间线", detail: "镜头顺序、字幕、音乐和转场", icon: Film, done: timelines.length > 0 },
    { label: "FFmpeg 渲染", detail: "生成可执行的专业剪辑渲染计划", icon: Play, done: renderJobs.length > 0 }
  ];

  async function loadProjects() {
    try {
      const data = await fetchJson<Project[]>(`${apiBaseUrl}/projects`);
      setProjects(data);
      const nextSelectedId = selectedProjectId ?? data[0]?.id ?? null;
      setSelectedProjectId(nextSelectedId);
      if (nextSelectedId) {
        await refreshPipeline(nextSelectedId);
      }
    } catch {
      setError("无法连接后端 API，请确认 FastAPI 已在 8000 端口启动。");
    } finally {
      setIsLoadingProjects(false);
    }
  }

  async function refreshPipeline(projectId: string) {
    const [nextShots, nextTasks, nextTimelines, nextRenderJobs] = await Promise.all([
      fetchJson<Shot[]>(`${apiBaseUrl}/projects/${projectId}/shots`),
      fetchJson<GenerationTask[]>(`${apiBaseUrl}/projects/${projectId}/generation-tasks`),
      fetchJson<Timeline[]>(`${apiBaseUrl}/projects/${projectId}/timelines`),
      fetchJson<RenderJob[]>(`${apiBaseUrl}/projects/${projectId}/render-jobs`)
    ]);
    setShots(nextShots);
    setTasks(nextTasks);
    setTimelines(nextTimelines);
    setRenderJobs(nextRenderJobs);
  }

  useEffect(() => {
    loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setNotice(null);

    const formData = new FormData(event.currentTarget);
    const payload = {
      title: String(formData.get("title") ?? ""),
      topic: String(formData.get("topic") ?? ""),
      target_duration: Number(formData.get("target_duration") ?? 45),
      target_ratio: String(formData.get("target_ratio") ?? "9:16"),
      language: String(formData.get("language") ?? "zh"),
      style: String(formData.get("style") ?? "documentary"),
      platform: String(formData.get("platform") ?? "douyin"),
      script_text: String(formData.get("script_text") ?? "")
    };

    try {
      const project = await fetchJson<Project>(`${apiBaseUrl}/projects`, {
        method: "POST",
        body: JSON.stringify(payload)
      });

      setProjects((current) => [project, ...current]);
      setSelectedProjectId(project.id);
      setShots([]);
      setTasks([]);
      setTimelines([]);
      setRenderJobs([]);
      setNotice(`已创建：${project.title}`);
    } catch {
      setError("项目创建失败，请检查后端服务和数据库。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function runPipelineStep(step: "optimize" | "plan" | "tasks" | "submitTasks" | "timeline" | "render" | "runRender") {
    if (!selectedProject) {
      setError("请先创建或选择一个项目。");
      return;
    }

    setIsPipelineBusy(true);
    setError(null);
    setNotice(null);

    try {
      if (step === "optimize") {
        await fetchJson(`${apiBaseUrl}/projects/${selectedProject.id}/prompt/optimize`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已优化 Seedance 主提示词。");
      }

      if (step === "plan") {
        await fetchJson<Shot[]>(`${apiBaseUrl}/projects/${selectedProject.id}/shots/plan`, {
          method: "POST",
          body: JSON.stringify({ shot_count: 4, replace_existing: true })
        });
        setNotice("已生成 Seedance 分镜。");
      }

      if (step === "tasks") {
        await fetchJson<GenerationTask[]>(`${apiBaseUrl}/projects/${selectedProject.id}/generation-tasks`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已创建 Seedance 生成任务；如果 worker 正在运行，会自动提交。");
      }

      if (step === "submitTasks") {
        await Promise.all(
          tasks
            .filter((task) => task.status === "queued" || task.status === "failed")
            .map((task) =>
              fetchJson(`${apiBaseUrl}/projects/${selectedProject.id}/generation-tasks/${task.id}/submit`, {
                method: "POST",
                body: JSON.stringify({})
              })
            )
        );
        setNotice("已手动提交 Seedance 任务到 worker。");
      }

      if (step === "timeline") {
        await fetchJson<Timeline>(`${apiBaseUrl}/projects/${selectedProject.id}/timelines`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已生成剪辑时间线。");
      }

      if (step === "render") {
        await fetchJson<RenderJob>(`${apiBaseUrl}/projects/${selectedProject.id}/render-jobs`, {
          method: "POST",
          body: JSON.stringify({ profile: selectedProject.target_ratio === "16:9" ? "landscape_1080p" : "social_1080p" })
        });
        setNotice("已创建 FFmpeg 渲染计划。");
      }

      if (step === "runRender") {
        const latestRenderJob = renderJobs[0];
        if (!latestRenderJob) {
          throw new Error("Render job missing");
        }
        await fetchJson(`${apiBaseUrl}/projects/${selectedProject.id}/render-jobs/${latestRenderJob.id}/run`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已提交 FFmpeg 渲染任务到 worker。");
      }

      await refreshPipeline(selectedProject.id);
      await loadProjects();
    } catch {
      setError("流程执行失败，请先确认上一步已经完成，或打开 API docs 查看具体错误。");
    } finally {
      setIsPipelineBusy(false);
    }
  }

  async function handleSelectProject(projectId: string) {
    setSelectedProjectId(projectId);
    setError(null);
    setNotice(null);
    try {
      await refreshPipeline(projectId);
    } catch {
      setError("项目详情加载失败。");
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="工作台导航">
        <div className="brand">
          <div className="brandMark" aria-hidden="true">
            <Film size={22} />
          </div>
          <div>
            <p className="eyebrow">Seedance 平台</p>
            <h1>视频工作台</h1>
          </div>
        </div>

        <nav className="navList">
          <a className="navItem active" href="#projects">
            <FolderOpen size={18} />
            项目
          </a>
          <a className="navItem" href="#workflow">
            <Activity size={18} />
            工作流
          </a>
          <a className="navItem" href="#assets">
            <ImagePlus size={18} />
            素材
          </a>
          <a className="navItem" href="#settings">
            <Settings2 size={18} />
            设置
          </a>
        </nav>

        <div className="servicePanel">
          <p className="panelTitle">本地服务</p>
          <div className="serviceList">
            {services.map((service) => (
              <div className="serviceRow" key={service.label}>
                <span className="statusDot" aria-label={`${service.label} 在线`} />
                <div>
                  <strong>{service.label}</strong>
                  <span>{service.value}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">国内 Seedance + FFmpeg</p>
            <h2>创建、编排并渲染生成视频</h2>
          </div>
          <button className="iconButton" type="button" aria-label="上传参考素材">
            <Upload size={20} />
          </button>
        </header>

        <div className="workspaceGrid">
          <section className="createPanel" aria-labelledby="create-title">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">新建项目</p>
                <h3 id="create-title">视频需求</h3>
              </div>
              <button className="primaryButton" type="submit" form="project-brief" disabled={isSubmitting}>
                <Plus size={18} />
                {isSubmitting ? "创建中" : "创建"}
              </button>
            </div>

            {notice ? <p className="notice success">{notice}</p> : null}
            {error ? <p className="notice error">{error}</p> : null}

            <form className="briefForm" id="project-brief" onSubmit={handleCreateProject}>
              <label>
                标题
                <input name="title" type="text" defaultValue="咖啡店开业短视频" required />
              </label>

              <label>
                主题
                <input name="topic" type="text" defaultValue="为一家现代咖啡店制作开业宣传视频" required />
              </label>

              <div className="formRow">
                <label>
                  时长
                  <select name="target_duration" defaultValue="45">
                    <option value="30">30 秒</option>
                    <option value="45">45 秒</option>
                    <option value="60">60 秒</option>
                    <option value="90">90 秒</option>
                  </select>
                </label>
                <label>
                  画幅
                  <select name="target_ratio" defaultValue="9:16">
                    <option>9:16</option>
                    <option>16:9</option>
                    <option>1:1</option>
                  </select>
                </label>
              </div>

              <div className="formRow">
                <label>
                  风格
                  <select name="style" defaultValue="commercial">
                    <option value="documentary">纪实感</option>
                    <option value="cinematic">电影感</option>
                    <option value="commercial">商业广告</option>
                    <option value="editorial">杂志编辑</option>
                  </select>
                </label>
                <label>
                  语言
                  <select name="language" defaultValue="zh">
                    <option value="zh">中文</option>
                    <option value="en">英文</option>
                    <option value="ja">日文</option>
                  </select>
                </label>
              </div>

              <label>
                平台
                <select name="platform" defaultValue="douyin">
                  <option value="douyin">抖音 / 小红书</option>
                  <option value="bilibili">B站</option>
                  <option value="wechat_channels">视频号</option>
                  <option value="internal">内部预览</option>
                </select>
              </label>

              <label>
                脚本
                <textarea
                  name="script_text"
                  rows={7}
                  defaultValue="清晨开店的温暖氛围，咖啡萃取特写，顾客取餐和交谈，结尾用轻柔的 CTA 邀请观众周末到店。"
                />
              </label>
            </form>
          </section>

          <section className="queuePanel" id="workflow" aria-labelledby="workflow-title">
            <div className="sectionHeader compact">
              <div>
                <p className="eyebrow">流程</p>
                <h3 id="workflow-title">内部接口</h3>
              </div>
              <Clock3 size={20} aria-hidden="true" />
            </div>

            <div className="actionGrid">
              <button type="button" onClick={() => runPipelineStep("optimize")} disabled={isPipelineBusy || !selectedProject}>
                <Sparkles size={17} />
                优化提示词
              </button>
              <button type="button" onClick={() => runPipelineStep("plan")} disabled={isPipelineBusy || !selectedProject}>
                <Layers3 size={17} />
                生成分镜
              </button>
              <button type="button" onClick={() => runPipelineStep("tasks")} disabled={isPipelineBusy || shots.length === 0}>
                <Sparkles size={17} />
                创建任务
              </button>
              <button type="button" onClick={() => runPipelineStep("submitTasks")} disabled={isPipelineBusy || tasks.length === 0}>
                <Upload size={17} />
                提交生成
              </button>
              <button type="button" onClick={() => runPipelineStep("timeline")} disabled={isPipelineBusy || shots.length === 0}>
                <Film size={17} />
                生成时间线
              </button>
              <button type="button" onClick={() => runPipelineStep("render")} disabled={isPipelineBusy || timelines.length === 0}>
                <Play size={17} />
                渲染计划
              </button>
              <button type="button" onClick={() => runPipelineStep("runRender")} disabled={isPipelineBusy || renderJobs.length === 0}>
                <Play size={17} />
                执行渲染
              </button>
            </div>

            <div className="workflowList">
              {workflow.map((item) => {
                const Icon = item.icon;

                return (
                  <article className="workflowItem" key={item.label}>
                    <div className="workflowIcon">
                      <Icon size={18} />
                    </div>
                    <div>
                      <strong>{item.label}</strong>
                      <span>{item.detail}</span>
                    </div>
                    <span className={`statePill ${item.done ? "ready" : "queued"}`}>{item.done ? "已完成" : "等待"}</span>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="projectsPanel" id="projects" aria-labelledby="projects-title">
            <div className="sectionHeader compact">
              <div>
                <p className="eyebrow">最近</p>
                <h3 id="projects-title">项目</h3>
              </div>
              <button className="ghostButton" type="button">
                查看全部
                <ChevronRight size={16} />
              </button>
            </div>

            <div className="projectList">
              {isLoadingProjects ? <p className="emptyState">正在加载项目...</p> : null}
              {!isLoadingProjects && projects.length === 0 ? (
                <p className="emptyState">创建第一个项目，开始视频生成流程。</p>
              ) : null}
              {projects.map((project) => (
                <button
                  className={`projectItem projectButton ${project.id === selectedProject?.id ? "selected" : ""}`}
                  key={project.id}
                  type="button"
                  onClick={() => handleSelectProject(project.id)}
                >
                  <div className="thumbnail">
                    <Captions size={20} />
                  </div>
                  <div>
                    <strong>{project.title}</strong>
                    <span>
                      {project.target_duration}s · {project.target_ratio}
                    </span>
                  </div>
                  <span className="projectStatus">{statusLabels[project.status] ?? project.status}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="audioPanel" id="assets" aria-labelledby="assets-title">
            <div className="sectionHeader compact">
              <div>
                <p className="eyebrow">媒体</p>
                <h3 id="assets-title">素材与时间线</h3>
              </div>
              <Music2 size={20} aria-hidden="true" />
            </div>
            <div className="laneList">
              <div>
                <CheckCircle2 size={18} />
                优化提示词
                <span>{selectedProject?.optimized_prompt ? "已生成" : "未生成"}</span>
              </div>
              <div>
                <CheckCircle2 size={18} />
                Seedance 镜头
                <span>{shots.length} 个</span>
              </div>
              <div>
                <CheckCircle2 size={18} />
                生成任务
                <span>{tasks.filter((task) => task.status === "succeeded").length}/{tasks.length} 成功</span>
              </div>
              <div>
                <CheckCircle2 size={18} />
                剪辑时间线
                <span>{timelines.length} 版</span>
              </div>
            </div>
          </section>

          <section className="timelinePanel" aria-labelledby="detail-title">
            <div className="sectionHeader compact">
              <div>
                <p className="eyebrow">详情</p>
                <h3 id="detail-title">{selectedProject?.title ?? "未选择项目"}</h3>
              </div>
            </div>

            <div className="detailGrid">
              <div>
                <strong>优化提示词</strong>
                {selectedProject?.optimized_prompt ? (
                  <article className="detailItem">
                    <b>Seedance 主提示词</b>
                    <p>{selectedProject.optimized_prompt}</p>
                    {selectedProject.prompt_optimization_notes.map((note) => (
                      <span key={note}>{note}</span>
                    ))}
                  </article>
                ) : (
                  <span>暂无优化提示词</span>
                )}
              </div>

              <div>
                <strong>分镜</strong>
                {shots.length === 0 ? <span>暂无分镜</span> : null}
                {shots.map((shot) => (
                  <article className="detailItem" key={shot.id}>
                    <b>
                      {shot.order_index + 1}. {shot.title}
                    </b>
                    <span>{shot.duration_seconds}s · {statusLabels[shot.status] ?? shot.status}</span>
                    <p>{shot.prompt}</p>
                  </article>
                ))}
              </div>
              <div>
                <strong>渲染</strong>
                {renderJobs.length === 0 ? <span>暂无渲染计划</span> : null}
                {renderJobs.map((job) => (
                  <article className="detailItem" key={job.id}>
                    <b>{job.profile}</b>
                    <span>{statusLabels[job.status] ?? job.status}</span>
                    <p>{job.ffmpeg_plan.commands?.map((command) => command.name).join(" / ")}</p>
                    {job.output_uri ? <span>{job.output_uri}</span> : null}
                    {job.error_message ? <span>{job.error_message}</span> : null}
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
