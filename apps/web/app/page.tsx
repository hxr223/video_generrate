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
  MonitorPlay,
  Music2,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  Sparkles,
  Upload,
  WandSparkles,
  X
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
  result_asset_id: string | null;
};

type GenerationTask = {
  id: string;
  shot_id: string | null;
  provider: string;
  model: string;
  status: string;
  provider_task_id: string | null;
  result_asset_id: string | null;
  error_message: string | null;
  request_payload: Record<string, unknown>;
};

type Asset = {
  id: string;
  kind: string;
  label: string;
  uri: string;
  duration_seconds: number | null;
  width?: number | null;
  height?: number | null;
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

type PublicSettings = {
  app_name: string;
  app_env: string;
  allowed_project_durations: number[];
  render_profiles: string[];
  providers: {
    seedance_configured: boolean;
    seedream_configured: boolean;
  };
  models: {
    seedance: string;
    seedream: string;
    seedream_size: string;
  };
  services: {
    api_base_url: string;
    ark_base_url: string;
    seedance_base_url: string;
    seedream_base_url: string;
    minio_endpoint: string;
    object_storage_public_base_url: string | null;
    minio_bucket: string;
  };
  capabilities: {
    upload_asset_kinds: string[];
    shot_bindable_asset_kinds: string[];
  };
};

type WorkflowState = "queued" | "running" | "ready" | "failed";
type PipelineStep =
  | "pipelineRun"
  | "optimize"
  | "plan"
  | "imageTasks"
  | "tasks"
  | "submitTasks"
  | "timeline"
  | "render"
  | "runRender";
type DetailTab = "overview" | "shots" | "tasks" | "assets" | "render";

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
  succeeded: "成功",
  ready: "就绪"
};

const workflowLabels: Record<WorkflowState, string> = {
  queued: "待开始",
  running: "推进中",
  ready: "已就绪",
  failed: "有异常"
};

const actionLabels: Record<string, string> = {
  pipelineRun: "一键编排",
  optimize: "优化提示词",
  plan: "生成分镜",
  tasks: "创建视频任务",
  imageTasks: "创建图片素材任务",
  submitTasks: "提交排队任务",
  timeline: "生成时间线",
  render: "创建渲染计划",
  runRender: "提交渲染任务",
  uploadAsset: "上传素材",
  generateScript: "自动生成脚本"
};

type PipelineRunResult = {
  triggered_steps: string[];
  waiting_on: string[];
  latest_timeline_id: string | null;
  latest_render_job_id: string | null;
};

type ScriptDraftResult = {
  script_text: string;
  beats: string[];
};

function isFormDataBody(body: BodyInit | null | undefined): body is FormData {
  return typeof FormData !== "undefined" && body instanceof FormData;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (!isFormDataBody(init?.body) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return (await response.json()) as T;
}

function summarizeAsyncState(items: Array<{ status: string }>): WorkflowState {
  if (items.some((item) => item.status === "failed")) {
    return "failed";
  }
  if (items.some((item) => item.status === "queued" || item.status === "running")) {
    return "running";
  }
  if (items.some((item) => item.status === "succeeded" || item.status === "ready")) {
    return "ready";
  }
  return "queued";
}

function getDefaultRenderProfile(project: Project | null): string {
  return project?.target_ratio === "16:9" ? "landscape_1080p" : "social_1080p";
}

function truncateText(value: string | null | undefined, maxLength: number): string {
  if (!value) {
    return "暂无内容";
  }
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength).trim()}...`;
}

function formatAssetKind(kind: string): string {
  const labels: Record<string, string> = {
    generated_image: "生成图片",
    seedance_video: "生成视频",
    reference_image: "参考图片",
    reference_video: "参考视频",
    audio: "音频",
    subtitle: "字幕",
    export: "导出文件"
  };
  return labels[kind] ?? kind;
}

function formatProvider(provider: string): string {
  return provider === "volcengine_seedream" ? "Seedream" : "Seedance";
}

function getProviderHealth(publicSettings: PublicSettings | null): Array<{
  label: string;
  value: string;
  tone: "online" | "warning";
}> {
  if (!publicSettings) {
    return [
      { label: "API", value: "等待连接", tone: "warning" },
      { label: "Seedance", value: "待配置", tone: "warning" },
      { label: "Seedream", value: "待配置", tone: "warning" }
    ];
  }

  return [
    { label: "API", value: publicSettings.app_env, tone: "online" },
    {
      label: "Seedance",
      value: publicSettings.providers.seedance_configured ? "已配置" : "未配置"
        ,
      tone: publicSettings.providers.seedance_configured ? "online" : "warning"
    },
    {
      label: "Seedream",
      value: publicSettings.providers.seedream_configured ? "已配置" : "未配置",
      tone: publicSettings.providers.seedream_configured ? "online" : "warning"
    }
  ];
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tasks, setTasks] = useState<GenerationTask[]>([]);
  const [timelines, setTimelines] = useState<Timeline[]>([]);
  const [renderJobs, setRenderJobs] = useState<RenderJob[]>([]);
  const [publicSettings, setPublicSettings] = useState<PublicSettings | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shotCount, setShotCount] = useState("4");
  const [attachGeneratedImages, setAttachGeneratedImages] = useState(true);
  const [renderProfile, setRenderProfile] = useState("social_1080p");
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [uploadKind, setUploadKind] = useState("reference_image");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploadShotId, setUploadShotId] = useState("");
  const [attachUploadedAsset, setAttachUploadedAsset] = useState(true);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [isClearingProjects, setIsClearingProjects] = useState(false);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [projectTitle, setProjectTitle] = useState("");
  const [projectTopic, setProjectTopic] = useState("");
  const [projectTargetDuration, setProjectTargetDuration] = useState("9");
  const [projectTargetRatio, setProjectTargetRatio] = useState("9:16");
  const [projectLanguage, setProjectLanguage] = useState("zh");
  const [projectStyle, setProjectStyle] = useState("commercial");
  const [projectPlatform, setProjectPlatform] = useState("douyin");
  const [projectScriptText, setProjectScriptText] = useState("");

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? projects[0] ?? null,
    [projects, selectedProjectId]
  );

  const allowedDurations = publicSettings?.allowed_project_durations ?? [3, 5, 9, 15];
  const renderProfiles = publicSettings?.render_profiles ?? ["social_1080p", "landscape_1080p", "master_prores"];
  const canAttachUploadedAsset = uploadKind === "reference_image" || uploadKind === "reference_video";
  const readyShotCount = shots.filter((shot) => shot.status === "ready" || Boolean(shot.result_asset_id)).length;
  const renderableShotsReady = shots.length > 0 && readyShotCount === shots.length;
  const runningTasks = tasks.some((task) => task.status === "queued" || task.status === "running");
  const runningRenderJobs = renderJobs.some((job) => job.status === "queued" || job.status === "running");
  const latestTimeline = timelines[0] ?? null;
  const latestRenderJob = renderJobs[0] ?? null;
  const successfulTasks = tasks.filter((task) => task.status === "succeeded").length;
  const uploadableKinds = publicSettings?.capabilities.upload_asset_kinds ?? [
    "reference_image",
    "reference_video",
    "audio",
    "subtitle"
  ];

  const workflow = [
    {
      label: "Brief",
      detail: "项目标题、画幅、平台和脚本设定",
      icon: Clapperboard,
      state: selectedProject ? ("ready" as WorkflowState) : ("queued" as WorkflowState)
    },
    {
      label: "主提示词",
      detail: "把创意要求压成可复用的模型主提示词",
      icon: WandSparkles,
      state: selectedProject?.optimized_prompt
        ? ("ready" as WorkflowState)
        : selectedProject?.status === "planning"
          ? ("running" as WorkflowState)
          : ("queued" as WorkflowState)
    },
    {
      label: "Storyboard",
      detail: "根据时长拆镜头并分配节奏",
      icon: Layers3,
      state: shots.length > 0 ? ("ready" as WorkflowState) : selectedProject ? ("running" as WorkflowState) : ("queued" as WorkflowState)
    },
    {
      label: "生成任务",
      detail: "图片/视频任务进入队列并等待素材回流",
      icon: Sparkles,
      state: summarizeAsyncState(tasks)
    },
    {
      label: "Timeline",
      detail: "镜头、音频、字幕与转场进入时间线",
      icon: Film,
      state: latestTimeline ? ("ready" as WorkflowState) : selectedProject?.status === "assembling" ? ("running" as WorkflowState) : ("queued" as WorkflowState)
    },
    {
      label: "Export",
      detail: "渲染计划与最终导出",
      icon: MonitorPlay,
      state: renderJobs.some((job) => job.status === "failed")
        ? ("failed" as WorkflowState)
        : runningRenderJobs
          ? ("running" as WorkflowState)
          : renderJobs.some((job) => job.status === "succeeded")
            ? ("ready" as WorkflowState)
            : ("queued" as WorkflowState)
    }
  ];

  const stageActions: Array<{
    step: PipelineStep;
    label: string;
    caption: string;
    icon: typeof Sparkles;
    tone: "accent" | "neutral";
    disabled: boolean;
    hintTitle?: string;
    hintLines?: string[];
  }> = [
    {
      step: "pipelineRun",
      label: "一键继续创作",
      caption: "自动推进到当前能继续的下一阶段",
      icon: Play,
      tone: "accent",
      disabled: !selectedProject || Boolean(activeAction),
      hintTitle: "适合什么时候点",
      hintLines: [
        "当你不想手动判断当前该跑哪一步时，用它自动推进到还能继续的阶段。",
        "如果 provider 未配置或素材还没 ready，它会停在等待点，而不是强行往下跑。",
        "最适合做日常主入口，先点它，再看系统还差哪一步。"
      ]
    },
    {
      step: "optimize",
      label: "优化主提示词",
      caption: selectedProject?.optimized_prompt ? "已有主提示词，可再次重生成" : "先把 brief 压成更稳定的模型提示词",
      icon: WandSparkles,
      tone: "neutral",
      disabled: !selectedProject || Boolean(activeAction),
      hintTitle: "它会生成什么",
      hintLines: [
        "把项目主题、脚本和风格信息整理成更适合模型使用的主提示词。",
        "适合在 brief 刚写完，或你调整了风格、平台、叙事方向之后使用。"
      ]
    },
    {
      step: "plan",
      label: "生成分镜",
      caption: shots.length > 0 ? `当前已有 ${shots.length} 个镜头` : `按 ${shotCount} 个镜头自动拆分`,
      icon: Layers3,
      tone: "neutral",
      disabled: !selectedProject || Boolean(activeAction),
      hintTitle: "点击后会做什么",
      hintLines: [
        "根据项目主题、脚本、时长、画幅和风格，自动拆出一组分镜镜头。",
        "适合在刚创建项目，或你修改了 brief 之后重新规划镜头时使用。",
        "当前前端入口会重新生成分镜，用新的规划结果覆盖旧的镜头列表。"
      ]
    },
    {
      step: "tasks",
      label: "创建视频任务",
      caption: tasks.length > 0 ? `${tasks.length} 个任务在管线中` : "将分镜转成 Seedance 视频任务",
      icon: Sparkles,
      tone: "neutral",
      disabled: !selectedProject || shots.length === 0 || Boolean(activeAction),
      hintTitle: "会发生什么",
      hintLines: [
        "把每个分镜转换成 Seedance 视频生成任务，进入任务队列。",
        "有了分镜但还没真正生成素材时，就该点这一步。",
        "如果 worker 和 provider 已配置，任务会继续提交；否则会先留在本地队列里。"
      ]
    },
    {
      step: "timeline",
      label: "生成时间线",
      caption: renderableShotsReady ? "镜头已就绪，可进入编排" : "需要先让镜头素材回到 ready",
      icon: Film,
      tone: "neutral",
      disabled: !selectedProject || !renderableShotsReady || Boolean(activeAction),
      hintTitle: "前提条件",
      hintLines: [
        "只有镜头素材都 ready 之后，系统才能把它们编进时间线。",
        "这一步会整理镜头顺序、片段时长，并为后续渲染准备可执行的 timeline。",
        "如果还有镜头没生成好，先不要点这一步。"
      ]
    },
    {
      step: latestRenderJob ? "runRender" : "render",
      label: latestRenderJob ? "执行渲染" : "创建渲染计划",
      caption: latestRenderJob
        ? latestRenderJob.output_uri
          ? "当前已有导出结果，可再次触发"
          : "把时间线送进 FFmpeg 导出"
        : "先为当前时间线生成导出计划",
      icon: MonitorPlay,
      tone: "neutral",
      disabled: !selectedProject || Boolean(activeAction) || (!latestRenderJob && timelines.length === 0),
      hintTitle: latestRenderJob ? "执行后会做什么" : "创建后会得到什么",
      hintLines: latestRenderJob
        ? [
            "把已经生成好的渲染计划送进 FFmpeg 执行，开始导出最终视频。",
            "适合在时间线确认没问题、并且你准备正式出片时点击。"
          ]
        : [
            "先根据当前时间线生成一份渲染计划，确认 profile 和输出命令。",
            "如果你想先看导出方案，再决定是否真正执行渲染，这一步最合适。"
          ]
    }
  ];

  const detailTabs: Array<{ id: DetailTab; label: string }> = [
    { id: "overview", label: "概览" },
    { id: "shots", label: "分镜" },
    { id: "tasks", label: "任务" },
    { id: "assets", label: "素材" },
    { id: "render", label: "渲染" }
  ];

  useEffect(() => {
    if (!canAttachUploadedAsset && attachUploadedAsset) {
      setAttachUploadedAsset(false);
    }
  }, [attachUploadedAsset, canAttachUploadedAsset]);

  useEffect(() => {
    if (!selectedProject) {
      return;
    }
    const nextDefaultProfile = getDefaultRenderProfile(selectedProject);
    if (!renderProfiles.includes(renderProfile)) {
      setRenderProfile(nextDefaultProfile);
    }
  }, [renderProfile, renderProfiles, selectedProject]);

  async function loadProjects(preferredSelectedId?: string): Promise<Project | null> {
    const data = await fetchJson<Project[]>(`${apiBaseUrl}/projects`);
    setProjects(data);
    const nextSelectedId = preferredSelectedId ?? selectedProjectId ?? data[0]?.id ?? null;
    setSelectedProjectId(nextSelectedId);
    return data.find((project) => project.id === nextSelectedId) ?? null;
  }

  async function loadSettings() {
    const settingsPayload = await fetchJson<PublicSettings>(`${apiBaseUrl}/settings/public`);
    setPublicSettings(settingsPayload);
  }

  async function refreshPipeline(projectId: string) {
    const [nextShots, nextAssets, nextTasks, nextTimelines, nextRenderJobs] = await Promise.all([
      fetchJson<Shot[]>(`${apiBaseUrl}/projects/${projectId}/shots`),
      fetchJson<Asset[]>(`${apiBaseUrl}/projects/${projectId}/assets`),
      fetchJson<GenerationTask[]>(`${apiBaseUrl}/projects/${projectId}/generation-tasks`),
      fetchJson<Timeline[]>(`${apiBaseUrl}/projects/${projectId}/timelines`),
      fetchJson<RenderJob[]>(`${apiBaseUrl}/projects/${projectId}/render-jobs`)
    ]);
    setShots(nextShots);
    setAssets(nextAssets);
    setTasks(nextTasks);
    setTimelines(nextTimelines);
    setRenderJobs(nextRenderJobs);
  }

  async function refreshWorkspace(projectId?: string) {
    const preferredProjectId = projectId ?? selectedProject?.id ?? undefined;
    const [_, nextSelectedProject] = await Promise.all([loadSettings(), loadProjects(preferredProjectId)]);

    if (nextSelectedProject) {
      await refreshPipeline(nextSelectedProject.id);
      return;
    }

    setShots([]);
    setAssets([]);
    setTasks([]);
    setTimelines([]);
    setRenderJobs([]);
  }

  async function handleRefreshWorkspace(projectId?: string) {
    setError(null);

    try {
      await refreshWorkspace(projectId);
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        setError(caughtError.message || "工作台刷新失败。");
      } else {
        setError("工作台刷新失败。");
      }
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        await loadSettings();
        const nextSelectedProject = await loadProjects();
        if (nextSelectedProject) {
          await refreshPipeline(nextSelectedProject.id);
          setRenderProfile(getDefaultRenderProfile(nextSelectedProject));
        }
      } catch {
        if (!cancelled) {
          setError("无法连接后端 API，请确认 FastAPI 已在 8000 端口启动。");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingProjects(false);
        }
      }
    }

    void bootstrap();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!autoRefreshEnabled || !selectedProjectId) {
      return;
    }
    if (!runningTasks && !runningRenderJobs) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void handleRefreshWorkspace(selectedProjectId);
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [autoRefreshEnabled, runningRenderJobs, runningTasks, selectedProjectId]);

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setNotice(null);

    const payload = {
      title: projectTitle.trim(),
      topic: projectTopic.trim(),
      target_duration: Number(projectTargetDuration),
      target_ratio: projectTargetRatio,
      language: projectLanguage,
      style: projectStyle,
      platform: projectPlatform,
      script_text: projectScriptText.trim()
    };

    try {
      const project = await fetchJson<Project>(`${apiBaseUrl}/projects`, {
        method: "POST",
        body: JSON.stringify(payload)
      });

      setProjects((current) => [project, ...current]);
      setSelectedProjectId(project.id);
      setShots([]);
      setAssets([]);
      setTasks([]);
      setTimelines([]);
      setRenderJobs([]);
      setRenderProfile(getDefaultRenderProfile(project));
      setDetailTab("overview");
      setNotice(`已创建：${project.title}`);
    } catch {
      setError("项目创建失败，请检查后端服务和数据库。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleGenerateScriptDraft() {
    if (!projectTitle.trim() || !projectTopic.trim()) {
      setError("请先填写标题和主题，再使用自动生成。");
      return;
    }

    if (projectScriptText.trim()) {
      const shouldReplace = window.confirm("当前脚本框已有内容，是否用新生成的脚本覆盖？");
      if (!shouldReplace) {
        return;
      }
    }

    setActiveAction("generateScript");
    setError(null);
    setNotice(null);

    try {
      const result = await fetchJson<ScriptDraftResult>(`${apiBaseUrl}/projects/script-draft`, {
        method: "POST",
        body: JSON.stringify({
          title: projectTitle.trim(),
          topic: projectTopic.trim(),
          target_duration: Number(projectTargetDuration),
          target_ratio: projectTargetRatio,
          language: projectLanguage,
          style: projectStyle,
          platform: projectPlatform,
        })
      });

      setProjectScriptText(result.script_text);
      setNotice("脚本已生成，可直接编辑后创建项目。");
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        setError(caughtError.message || "脚本生成失败。");
      } else {
        setError("脚本生成失败。");
      }
    } finally {
      setActiveAction(null);
    }
  }

  async function handleSelectProject(projectId: string) {
    setSelectedProjectId(projectId);
    setRenderProfile(getDefaultRenderProfile(projects.find((project) => project.id === projectId) ?? null));
    setError(null);
    setNotice(null);
    try {
      await refreshPipeline(projectId);
    } catch {
      setError("项目详情加载失败。");
    }
  }

  async function handleClearProjects() {
    if (projects.length === 0 || isClearingProjects) {
      return;
    }

    const shouldClear = window.confirm(`将删除最近创作中的 ${projects.length} 个项目，此操作不可撤销。是否继续？`);
    if (!shouldClear) {
      return;
    }

    setIsClearingProjects(true);
    setError(null);
    setNotice(null);

    try {
      await Promise.all(
        projects.map((project) =>
          fetch(`${apiBaseUrl}/projects/${project.id}`, {
            method: "DELETE"
          }).then((response) => {
            if (!response.ok) {
              throw new Error(`删除项目失败: ${project.title}`);
            }
          })
        )
      );

      setProjects([]);
      setSelectedProjectId(null);
      setShots([]);
      setAssets([]);
      setTasks([]);
      setTimelines([]);
      setRenderJobs([]);
      setNotice("最近创作已清空。");
      setDetailTab("overview");
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        setError(caughtError.message || "清空项目失败。");
      } else {
        setError("清空项目失败。");
      }
    } finally {
      setIsClearingProjects(false);
    }
  }

  async function runPipelineStep(step: PipelineStep) {
    if (!selectedProject) {
      setError("请先创建或选择一个项目。");
      return;
    }

    setActiveAction(step);
    setError(null);
    setNotice(null);

    try {
      if (step === "pipelineRun") {
        const result = await fetchJson<PipelineRunResult>(`${apiBaseUrl}/projects/${selectedProject.id}/pipeline/run`, {
          method: "POST",
          body: JSON.stringify({
            shot_count: Number(shotCount),
            replace_existing_shots: false,
            optimize_prompt: true,
            create_image_tasks: false,
            create_video_tasks: true,
            attach_generated_images_to_shots: attachGeneratedImages,
            build_timeline_when_ready: true,
            create_render_job_when_ready: true,
            run_render_when_ready: true,
            profile: renderProfile
          })
        });
        setNotice(
          result.waiting_on.length > 0
            ? `已推进编排，当前等待：${result.waiting_on.join(" / ")}`
            : "已完成一键编排并继续推进到下一阶段。"
        );
      }

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
          body: JSON.stringify({ shot_count: Number(shotCount), replace_existing: true })
        });
        setNotice(`已按 ${shotCount} 个镜头生成分镜。`);
      }

      if (step === "tasks") {
        await fetchJson<GenerationTask[]>(`${apiBaseUrl}/projects/${selectedProject.id}/generation-tasks`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已创建 Seedance 视频任务；如果 worker 正在运行，会自动提交。");
      }

      if (step === "imageTasks") {
        await fetchJson<GenerationTask[]>(`${apiBaseUrl}/projects/${selectedProject.id}/image-generation-tasks`, {
          method: "POST",
          body: JSON.stringify({ attach_to_shots: attachGeneratedImages })
        });
        setNotice(
          attachGeneratedImages
            ? "已创建 Seedream 图片任务；成功后会自动绑定回分镜。"
            : "已创建 Seedream 图片任务；生成后只进入素材库，不自动绑定分镜。"
        );
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
        setNotice("已手动提交当前排队任务到 worker。");
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
          body: JSON.stringify({ profile: renderProfile })
        });
        setNotice(`已创建 ${renderProfile} 渲染计划。`);
      }

      if (step === "runRender") {
        if (!latestRenderJob) {
          throw new Error("Render job missing");
        }
        await fetchJson(`${apiBaseUrl}/projects/${selectedProject.id}/render-jobs/${latestRenderJob.id}/run`, {
          method: "POST",
          body: JSON.stringify({})
        });
        setNotice("已提交 FFmpeg 渲染任务到 worker。");
      }

      await refreshWorkspace(selectedProject.id);
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        setError(caughtError.message || "流程执行失败，请查看后端返回详情。");
      } else {
        setError("流程执行失败，请先确认上一步已经完成，或打开 API docs 查看具体错误。");
      }
    } finally {
      setActiveAction(null);
    }
  }

  async function handleUploadAsset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      setError("请先创建或选择一个项目。");
      return;
    }

    const formData = new FormData(event.currentTarget);
    const file = formData.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("请选择要上传的素材文件。");
      return;
    }

    setActiveAction("uploadAsset");
    setError(null);
    setNotice(null);

    const payload = new FormData();
    payload.append("file", file);
    payload.append("kind", uploadKind);
    payload.append("label", uploadLabel || file.name.replace(/\.[^.]+$/, ""));
    if (uploadShotId) {
      payload.append("shot_id", uploadShotId);
    }
    payload.append("attach_to_shot", String(canAttachUploadedAsset && attachUploadedAsset && Boolean(uploadShotId)));

    try {
      await fetchJson<Asset>(`${apiBaseUrl}/projects/${selectedProject.id}/assets/upload`, {
        method: "POST",
        body: payload
      });
      setUploadLabel("");
      setNotice("素材上传成功，已写入素材库。");
      event.currentTarget.reset();
      await refreshWorkspace(selectedProject.id);
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        setError(caughtError.message || "素材上传失败。");
      } else {
        setError("素材上传失败。");
      }
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <main className="studioShell">
      <div className="ambientGlow ambientGlowOne" aria-hidden="true" />
      <div className="ambientGlow ambientGlowTwo" aria-hidden="true" />

      <header className="heroHeader">
        <div className="heroCopy">
          <p className="heroEyebrow">Seedance Studio</p>
          <h1>把创意 brief、生成管线和导出结果收进一个创作舞台</h1>
          <p className="heroLead">
            参考集梦这类创作工作台的体验，把首页从“接口面板”改成“项目主场”。你可以从这里一键继续创作，也可以随时回到分镜、素材和渲染阶段做人工接管。
          </p>

          <div className="heroActions">
            <button
              className="heroPrimaryButton"
              type="button"
              onClick={() => void runPipelineStep("pipelineRun")}
              disabled={!selectedProject || Boolean(activeAction)}
            >
              <Play size={18} />
              {activeAction === "pipelineRun" ? "正在推进" : selectedProject ? "一键继续创作" : "先创建项目"}
            </button>
            <button className="heroSecondaryButton" type="button" onClick={() => void handleRefreshWorkspace()}>
              <RefreshCw size={17} />
              刷新工作台
            </button>
          </div>

          <div className="heroMetaRow">
            {getProviderHealth(publicSettings).map((item) => (
              <span className={`heroBadge ${item.tone}`} key={item.label}>
                {item.label}
                <b>{item.value}</b>
              </span>
            ))}
          </div>
        </div>

        <div className="heroStageCard">
          <div className="heroStageTop">
            <div>
              <p className="sectionEyebrow">当前项目</p>
              <h2>{selectedProject?.title ?? "还没有选中的项目"}</h2>
            </div>
            <span className={`statusBadge tone-${selectedProject?.status ?? "draft"}`}>
              {selectedProject ? statusLabels[selectedProject.status] ?? selectedProject.status : "待开始"}
            </span>
          </div>

          <p className="heroStageText">
            {selectedProject
              ? truncateText(selectedProject.topic, 120)
              : "先在左侧创建一个项目，这里会成为当前创作的主舞台。"}
          </p>

          <div className="snapshotGrid">
            <article>
              <strong>{selectedProject ? `${selectedProject.target_duration}s` : "--"}</strong>
              <span>目标时长</span>
            </article>
            <article>
              <strong>{shots.length}</strong>
              <span>分镜镜头</span>
            </article>
            <article>
              <strong>{tasks.length}</strong>
              <span>生成任务</span>
            </article>
            <article>
              <strong>{renderJobs.length}</strong>
              <span>渲染计划</span>
            </article>
          </div>
        </div>
      </header>

      <div className="studioLayout">
        <aside className="projectRail">
          <section className="panel projectRailPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">项目库</p>
                <h3>最近创作</h3>
              </div>
              <div className="headerActions">
                <button className="inlineAction" type="button" onClick={() => void handleRefreshWorkspace()}>
                  刷新
                  <ChevronRight size={16} />
                </button>
                <button
                  className="inlineAction danger"
                  type="button"
                  onClick={() => void handleClearProjects()}
                  disabled={projects.length === 0 || isClearingProjects}
                >
                  {isClearingProjects ? "清空中" : "清空"}
                </button>
              </div>
            </div>

            <div className="projectList">
              {isLoadingProjects ? <p className="emptyState">正在加载项目...</p> : null}
              {!isLoadingProjects && projects.length === 0 ? <p className="emptyState">创建第一个项目，开始视频生成流程。</p> : null}
              {projects.map((project) => (
                <button
                  className={`projectCard ${project.id === selectedProject?.id ? "selected" : ""}`}
                  key={project.id}
                  type="button"
                  onClick={() => void handleSelectProject(project.id)}
                >
                  <div className="projectCardIcon">
                    <FolderOpen size={18} />
                  </div>
                  <div className="projectCardBody">
                    <strong>{project.title}</strong>
                    <span>
                      {project.target_duration}s · {project.target_ratio} · {project.platform}
                    </span>
                  </div>
                  <span className={`statusBadge tone-${project.status}`}>{statusLabels[project.status] ?? project.status}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel createPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">新建项目</p>
                <h3>创作 Brief</h3>
              </div>
              <div className="headerActions">
                <button className="heroSmallButton" type="submit" form="project-brief" disabled={isSubmitting}>
                  <Plus size={16} />
                  {isSubmitting ? "创建中" : "创建"}
                </button>
                <button className="inlineAction" type="button" onClick={() => setIsDetailOpen(true)}>
                  查看详情
                </button>
              </div>
            </div>

            <form className="briefForm" id="project-brief" onSubmit={handleCreateProject}>
              <label>
                标题
                <input
                  name="title"
                  type="text"
                  placeholder="例：咖啡店开业短视频"
                  required
                  value={projectTitle}
                  onChange={(event) => setProjectTitle(event.target.value)}
                />
              </label>

              <label>
                主题
                <input
                  name="topic"
                  type="text"
                  placeholder="例：为一家现代咖啡店制作开业宣传视频"
                  required
                  value={projectTopic}
                  onChange={(event) => setProjectTopic(event.target.value)}
                />
              </label>

              <div className="formRow">
                <label>
                  时长
                  <select name="target_duration" value={projectTargetDuration} onChange={(event) => setProjectTargetDuration(event.target.value)}>
                    {allowedDurations.map((duration) => (
                      <option key={duration} value={duration}>
                        {duration} 秒
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  画幅
                  <select name="target_ratio" value={projectTargetRatio} onChange={(event) => setProjectTargetRatio(event.target.value)}>
                    <option>9:16</option>
                    <option>16:9</option>
                    <option>1:1</option>
                  </select>
                </label>
              </div>

              <div className="formRow">
                <label>
                  风格
                  <select name="style" value={projectStyle} onChange={(event) => setProjectStyle(event.target.value)}>
                    <option value="documentary">纪实感</option>
                    <option value="cinematic">电影感</option>
                    <option value="commercial">商业广告</option>
                    <option value="editorial">杂志编辑</option>
                  </select>
                </label>
                <label>
                  语言
                  <select name="language" value={projectLanguage} onChange={(event) => setProjectLanguage(event.target.value)}>
                    <option value="zh">中文</option>
                    <option value="en">英文</option>
                    <option value="ja">日文</option>
                  </select>
                </label>
              </div>

              <label>
                平台
                <select name="platform" value={projectPlatform} onChange={(event) => setProjectPlatform(event.target.value)}>
                  <option value="douyin">抖音 / 小红书</option>
                  <option value="bilibili">B站</option>
                  <option value="wechat_channels">视频号</option>
                  <option value="internal">内部预览</option>
                </select>
              </label>

              <label>
                <span className="fieldHeader">
                  <span>脚本</span>
                  <button
                    className="fieldHintButton"
                    type="button"
                    onClick={() => void handleGenerateScriptDraft()}
                    disabled={Boolean(activeAction) || isSubmitting}
                  >
                    <WandSparkles size={15} />
                    {activeAction === "generateScript" ? "生成中..." : "自动生成"}
                  </button>
                </span>
                <textarea
                  name="script_text"
                  rows={7}
                  placeholder="例：清晨开店的温暖氛围，咖啡萃取特写，顾客取餐和交谈，结尾用轻柔的 CTA 邀请观众周末到店。"
                  value={projectScriptText}
                  onChange={(event) => setProjectScriptText(event.target.value)}
                />
              </label>
            </form>
          </section>
        </aside>

        <section className="studioMain">
          <section className="panel stagePanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">主舞台</p>
                <h3>当前项目推进</h3>
              </div>
              {activeAction ? <span className="inlineMeta">当前操作：{actionLabels[activeAction] ?? activeAction}</span> : null}
            </div>

            <div className="summaryRail">
              <article className="summaryCard warm">
                <Sparkles size={18} />
                <div>
                  <strong>{selectedProject?.optimized_prompt ? "主提示词已生成" : "主提示词待优化"}</strong>
                  <span>{selectedProject?.optimized_prompt ? "可以直接复用到分镜和视频任务" : "先让系统把 brief 压成更稳定的主提示词"}</span>
                </div>
              </article>
              <article className="summaryCard cool">
                <Layers3 size={18} />
                <div>
                  <strong>{shots.length > 0 ? `已拆分 ${shots.length} 个镜头` : "还没有分镜"}</strong>
                  <span>{shots.length > 0 ? `${readyShotCount} 个镜头已经 ready，可继续进时间线` : "按当前时长和平台自动规划节奏"}</span>
                </div>
              </article>
              <article className="summaryCard dark">
                <MonitorPlay size={18} />
                <div>
                  <strong>{latestRenderJob ? latestRenderJob.profile : "等待渲染计划"}</strong>
                  <span>{latestRenderJob ? statusLabels[latestRenderJob.status] ?? latestRenderJob.status : "在素材就绪后进入 FFmpeg 导出"}</span>
                </div>
              </article>
            </div>

            <div className="workflowRail">
              {workflow.map((item) => {
                const Icon = item.icon;

                return (
                  <article className={`workflowCard tone-${item.state}`} key={item.label}>
                    <div className="workflowCardIcon">
                      <Icon size={18} />
                    </div>
                    <div>
                      <strong>{item.label}</strong>
                      <span>{item.detail}</span>
                    </div>
                    <em>{workflowLabels[item.state]}</em>
                  </article>
                );
              })}
            </div>

            <div className="phaseActionGrid">
              {stageActions.map((item) => {
                const Icon = item.icon;

                return (
                  <button
                    className={`phaseActionCard ${item.tone}`}
                    key={item.step}
                    type="button"
                    onClick={() => void runPipelineStep(item.step)}
                    disabled={item.disabled}
                  >
                    <span className="phaseActionIcon">
                      <Icon size={18} />
                    </span>
                    <strong>{item.label}</strong>
                    <span>{item.caption}</span>
                    {item.hintLines?.length ? (
                      <div className="actionHint">
                        <b>{item.hintTitle}</b>
                        {item.hintLines.map((line) => (
                          <p key={line}>{line}</p>
                        ))}
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </section>

          <section className="panel storyboardPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">Storyboard</p>
                <h3>分镜与素材带</h3>
              </div>
              <div className="miniStats">
                <span>{readyShotCount}/{shots.length || 0} 镜头就绪</span>
                <span>{assets.length} 个素材</span>
              </div>
            </div>

            {shots.length === 0 ? (
              <p className="emptyState">还没有分镜。先用“一键继续创作”或“生成分镜”把项目推进到 storyboard 阶段。</p>
            ) : (
              <div className="storyboardGrid">
                {shots.map((shot) => (
                  <article className="storyCard" key={shot.id}>
                    <div className="storyVisual">
                      <span>Shot {shot.order_index + 1}</span>
                      <b>{shot.duration_seconds}s</b>
                    </div>
                    <div className="storyBody">
                      <div className="storyMeta">
                        <strong>{shot.title}</strong>
                        <span className={`statusBadge tone-${shot.status}`}>{statusLabels[shot.status] ?? shot.status}</span>
                      </div>
                      <p>{truncateText(shot.prompt, 110)}</p>
                    </div>
                  </article>
                ))}
              </div>
            )}

            <div className="assetRibbon">
              {assets.length === 0 ? (
                <p className="emptyState compact">素材库还是空的，生成图片/视频任务成功后会在这里回流。</p>
              ) : (
                assets.slice(0, 8).map((asset) => (
                  <article className="assetTile" key={asset.id}>
                    <div className="assetTileVisual">
                      {asset.kind.includes("video") ? <Film size={18} /> : asset.kind.includes("audio") ? <Music2 size={18} /> : <ImagePlus size={18} />}
                    </div>
                    <strong>{asset.label}</strong>
                    <span>{formatAssetKind(asset.kind)}</span>
                    <span>
                      {asset.duration_seconds ? `${asset.duration_seconds}s` : asset.width && asset.height ? `${asset.width}×${asset.height}` : "已入库"}
                    </span>
                  </article>
                ))
              )}
            </div>
          </section>

        </section>

        <aside className="inspector">
          <section className="panel runtimePanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">运行状态</p>
                <h3>系统脉搏</h3>
              </div>
              <Activity size={18} />
            </div>

            {notice ? <p className="notice success">{notice}</p> : null}
            {error ? <p className="notice error">{error}</p> : null}

            <div className="healthList">
              {(publicSettings
                ? [
                    {
                      label: "后端 API",
                      value: publicSettings.services.api_base_url,
                      detail: `${publicSettings.app_env} 环境`,
                      tone: "online"
                    },
                    {
                      label: "Seedance",
                      value: publicSettings.models.seedance,
                      detail: publicSettings.providers.seedance_configured ? publicSettings.services.seedance_base_url : "未配置 ARK_API_KEY",
                      tone: publicSettings.providers.seedance_configured ? "online" : "warning"
                    },
                    {
                      label: "Seedream",
                      value: `${publicSettings.models.seedream} · ${publicSettings.models.seedream_size}`,
                      detail: publicSettings.providers.seedream_configured ? publicSettings.services.seedream_base_url : "未配置 ARK_API_KEY",
                      tone: publicSettings.providers.seedream_configured ? "online" : "warning"
                    },
                    {
                      label: "对象存储",
                      value: publicSettings.services.minio_endpoint,
                      detail: `Bucket: ${publicSettings.services.minio_bucket}`,
                      tone: "online"
                    }
                  ]
                : [
                    { label: "后端 API", value: apiBaseUrl, detail: "等待连接", tone: "warning" },
                    { label: "Seedance", value: "-", detail: "等待配置", tone: "warning" },
                    { label: "Seedream", value: "-", detail: "等待配置", tone: "warning" },
                    { label: "对象存储", value: "-", detail: "等待配置", tone: "warning" }
                  ]
              ).map((service) => (
                <article className="healthCard" key={service.label}>
                  <span className={`healthDot ${service.tone}`} aria-hidden="true" />
                  <div>
                    <strong>{service.label}</strong>
                    <span>{service.value}</span>
                    <p>{service.detail}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="panel settingsPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">工作流设置</p>
                <h3>参数与自动化</h3>
              </div>
              <Settings2 size={18} />
            </div>

            <div className="settingsFields">
              <label>
                分镜数量
                <select value={shotCount} onChange={(event) => setShotCount(event.target.value)}>
                  {[2, 3, 4, 5, 6].map((count) => (
                    <option key={count} value={count}>
                      {count} 个镜头
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Seedream 绑定策略
                <select
                  value={attachGeneratedImages ? "true" : "false"}
                  onChange={(event) => setAttachGeneratedImages(event.target.value === "true")}
                >
                  <option value="true">自动绑定回分镜</option>
                  <option value="false">仅写入素材库</option>
                </select>
              </label>
              <label>
                渲染 Profile
                <select value={renderProfile} onChange={(event) => setRenderProfile(event.target.value)}>
                  {renderProfiles.map((profile) => (
                    <option key={profile} value={profile}>
                      {profile}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                状态自动刷新
                <select
                  value={autoRefreshEnabled ? "true" : "false"}
                  onChange={(event) => setAutoRefreshEnabled(event.target.value === "true")}
                >
                  <option value="true">开启，每 5 秒刷新</option>
                  <option value="false">关闭，手动刷新</option>
                </select>
              </label>
            </div>

            <div className="smallActionRow">
              <button
                className="subtleButton"
                type="button"
                onClick={() => void runPipelineStep("imageTasks")}
                disabled={!selectedProject || shots.length === 0 || Boolean(activeAction)}
              >
                <ImagePlus size={16} />
                创建图片任务
              </button>
              <button
                className="subtleButton"
                type="button"
                onClick={() => void runPipelineStep("submitTasks")}
                disabled={!selectedProject || tasks.length === 0 || Boolean(activeAction)}
              >
                <Upload size={16} />
                手动提交任务
              </button>
            </div>
          </section>

          <section className="panel uploadPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">资产输入</p>
                <h3>上传参考素材</h3>
              </div>
              <Upload size={18} />
            </div>

            <form className="settingsFields" onSubmit={handleUploadAsset}>
              <label>
                素材类型
                <select value={uploadKind} onChange={(event) => setUploadKind(event.target.value)}>
                  {uploadableKinds.map((kind) => (
                    <option key={kind} value={kind}>
                      {formatAssetKind(kind)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                素材标签
                <input
                  type="text"
                  value={uploadLabel}
                  placeholder="留空则使用文件名"
                  onChange={(event) => setUploadLabel(event.target.value)}
                />
              </label>
              <label>
                绑定镜头
                <select value={uploadShotId} onChange={(event) => setUploadShotId(event.target.value)} disabled={!selectedProject || shots.length === 0}>
                  <option value="">仅上传到素材库</option>
                  {shots.map((shot) => (
                    <option key={shot.id} value={shot.id}>
                      {shot.order_index + 1}. {shot.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                上传后处理
                <select
                  value={attachUploadedAsset ? "true" : "false"}
                  onChange={(event) => setAttachUploadedAsset(event.target.value === "true")}
                  disabled={!canAttachUploadedAsset || !uploadShotId}
                >
                  <option value="true">写入素材库并绑定镜头</option>
                  <option value="false">仅写入素材库</option>
                </select>
              </label>
              <label>
                文件
                <input name="file" type="file" accept="image/*,video/*,audio/*,.srt,.ass,.vtt" disabled={!selectedProject || Boolean(activeAction)} />
              </label>
              <button className="heroSmallButton wide" type="submit" disabled={!selectedProject || Boolean(activeAction)}>
                <Upload size={17} />
                {activeAction === "uploadAsset" ? "上传中" : "上传素材"}
              </button>
            </form>
          </section>

          <section className="panel analyticsPanel">
            <div className="panelHeader">
              <div>
                <p className="sectionEyebrow">项目快照</p>
                <h3>结果概览</h3>
              </div>
              <Clock3 size={18} />
            </div>

            <div className="stackedMetrics">
              <article>
                <strong>{successfulTasks}/{tasks.length || 0}</strong>
                <span>成功生成任务</span>
              </article>
              <article>
                <strong>{latestTimeline ? latestTimeline.segments.length : 0}</strong>
                <span>时间线片段</span>
              </article>
              <article>
                <strong>{latestRenderJob?.output_uri ? "已导出" : "待导出"}</strong>
                <span>最终成片</span>
              </article>
            </div>
          </section>
        </aside>
      </div>

      {isDetailOpen ? (
        <div className="detailModalOverlay" role="presentation" onClick={() => setIsDetailOpen(false)}>
          <section className="panel detailModal" aria-labelledby="detail-modal-title" onClick={(event) => event.stopPropagation()}>
            <div className="panelHeader detailModalHeader">
              <div>
                <p className="sectionEyebrow">详情区</p>
                <h3 id="detail-modal-title">{selectedProject?.title ?? "未选择项目"}</h3>
              </div>
              <div className="headerActions">
                <button className="inlineAction" type="button" onClick={() => void handleRefreshWorkspace()}>
                  刷新
                </button>
                <button className="detailModalClose" type="button" aria-label="关闭详情" onClick={() => setIsDetailOpen(false)}>
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="tabRail">
              {detailTabs.map((tab) => (
                <button
                  className={`tabButton ${detailTab === tab.id ? "active" : ""}`}
                  key={tab.id}
                  type="button"
                  onClick={() => setDetailTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="detailModalBody">
              {detailTab === "overview" ? (
                <div className="detailGrid">
                  <article className="detailCard featured">
                    <div className="detailCardHeader">
                      <strong>项目主题</strong>
                      <span>{selectedProject ? `${selectedProject.target_duration}s · ${selectedProject.target_ratio}` : "等待项目"}</span>
                    </div>
                    <p>{selectedProject ? truncateText(selectedProject.topic, 240) : "创建项目后，这里会展示项目主旨和脚本。"} </p>
                    <div className="chipRow">
                      <span>{selectedProject?.style ?? "风格待定"}</span>
                      <span>{selectedProject?.platform ?? "平台待定"}</span>
                      <span>{selectedProject?.language ?? "语言待定"}</span>
                    </div>
                  </article>

                  <article className="detailCard">
                    <div className="detailCardHeader">
                      <strong>主提示词</strong>
                      <span>{selectedProject?.optimized_prompt ? "已生成" : "未生成"}</span>
                    </div>
                    <p>{truncateText(selectedProject?.optimized_prompt ?? selectedProject?.script_text, 280)}</p>
                    {selectedProject?.prompt_optimization_notes?.length ? (
                      <div className="tagStack">
                        {selectedProject.prompt_optimization_notes.map((note) => (
                          <span key={note}>{note}</span>
                        ))}
                      </div>
                    ) : null}
                  </article>

                  <article className="detailCard">
                    <div className="detailCardHeader">
                      <strong>时间线状态</strong>
                      <span>{latestTimeline ? `v${latestTimeline.version}` : "未生成"}</span>
                    </div>
                    <p>{latestTimeline ? `当前时间线总长 ${latestTimeline.duration_seconds}s，共 ${latestTimeline.segments.length} 个片段。` : "镜头 ready 后即可生成剪辑时间线。"} </p>
                  </article>
                </div>
              ) : null}

              {detailTab === "shots" ? (
                <div className="detailList">
                  {shots.length === 0 ? <p className="emptyState compact">暂无分镜。</p> : null}
                  {shots.map((shot) => (
                    <article className="detailListCard" key={shot.id}>
                      <div className="detailCardHeader">
                        <strong>
                          {shot.order_index + 1}. {shot.title}
                        </strong>
                        <span>{statusLabels[shot.status] ?? shot.status}</span>
                      </div>
                      <p>{shot.prompt}</p>
                    </article>
                  ))}
                </div>
              ) : null}

              {detailTab === "tasks" ? (
                <div className="detailList">
                  {tasks.length === 0 ? <p className="emptyState compact">暂无任务。</p> : null}
                  {tasks.map((task) => (
                    <article className="detailListCard" key={task.id}>
                      <div className="detailCardHeader">
                        <strong>{formatProvider(task.provider)}</strong>
                        <span>{statusLabels[task.status] ?? task.status}</span>
                      </div>
                      <p>{task.model}</p>
                      {task.error_message ? <p className="dangerText">{task.error_message}</p> : null}
                    </article>
                  ))}
                </div>
              ) : null}

              {detailTab === "assets" ? (
                <div className="assetDetailGrid">
                  {assets.length === 0 ? <p className="emptyState compact">暂无素材。</p> : null}
                  {assets.map((asset) => (
                    <article className="assetDetailCard" key={asset.id}>
                      <div className="assetDetailVisual">
                        {asset.kind.includes("video") ? <Film size={18} /> : asset.kind.includes("audio") ? <Music2 size={18} /> : <ImagePlus size={18} />}
                      </div>
                      <div className="assetDetailBody">
                        <strong>{asset.label}</strong>
                        <span>{formatAssetKind(asset.kind)}</span>
                        <span>{asset.duration_seconds ? `${asset.duration_seconds}s` : asset.width && asset.height ? `${asset.width}×${asset.height}` : "已入库"}</span>
                        <p>{truncateText(asset.uri, 120)}</p>
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}

              {detailTab === "render" ? (
                <div className="detailList">
                  {renderJobs.length === 0 ? <p className="emptyState compact">暂无渲染计划。</p> : null}
                  {renderJobs.map((job) => (
                    <article className="detailListCard" key={job.id}>
                      <div className="detailCardHeader">
                        <strong>{job.profile}</strong>
                        <span>{statusLabels[job.status] ?? job.status}</span>
                      </div>
                      <p>{job.ffmpeg_plan.commands?.map((command) => command.name).join(" / ") || "等待命令生成"}</p>
                      {job.output_uri ? <p>{job.output_uri}</p> : null}
                      {job.error_message ? <p className="dangerText">{job.error_message}</p> : null}
                    </article>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
