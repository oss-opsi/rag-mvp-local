import type {
  AdminUser,
  AnalysisJob,
  AppNotification,
  ApiKeyInfo,
  Client,
  ClientCdcsResponse,
  CdcDetail,
  CollectionInfo,
  Conversation,
  ConversationDetail,
  IngestionJob,
  QdrantCollectionStat,
  QualityDashboard,
  QueryResponse,
  RefreshJob,
  RequirementFeedback,
  Schedule,
  UploadResponse,
  User,
} from "./types";

export type RagasMetrics = {
  faithfulness: number;
  answer_relevancy: number;
  context_precision: number;
  context_recall: number;
};

export type RagasPerQuestion = {
  question: string;
  ground_truth: string;
  answer: string;
  faithfulness: number;
  answer_relevancy: number;
  context_precision: number;
  context_recall: number;
};

export type LlmSettings = {
  llm_chat: string;
  llm_analysis: string;
  llm_repass: string;
};

export type LlmSettingsResponse = {
  settings: LlmSettings;
  allowed: string[];
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "Erreur inconnue";
    try {
      const j = await res.json();
      detail = (j && (j.detail || j.message)) || detail;
    } catch {
      try {
        detail = await res.text();
      } catch {
        // ignore
      }
    }
    throw new Error(detail);
  }
  const text = await res.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

export const api = {
  async login(username: string, password: string): Promise<User> {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    return handle<User>(res);
  },

  async logout(): Promise<void> {
    await fetch("/api/auth/logout", { method: "POST" });
  },

  async me(): Promise<User> {
    const res = await fetch("/api/auth/me");
    return handle<User>(res);
  },

  async getApiKey(): Promise<ApiKeyInfo> {
    const res = await fetch("/api/auth/api-key");
    return handle<ApiKeyInfo>(res);
  },

  async setApiKey(api_key: string): Promise<ApiKeyInfo> {
    const res = await fetch("/api/auth/api-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key }),
    });
    return handle<ApiKeyInfo>(res);
  },

  async deleteApiKey(): Promise<ApiKeyInfo> {
    const res = await fetch("/api/auth/api-key", { method: "DELETE" });
    return handle<ApiKeyInfo>(res);
  },

  async uploadDocument(file: File): Promise<UploadResponse> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    return handle<UploadResponse>(res);
  },

  async ingestionJobs(statusFilter?: string): Promise<IngestionJob[]> {
    const qs = statusFilter
      ? `?status=${encodeURIComponent(statusFilter)}`
      : "";
    const res = await fetch(`/api/ingestion-jobs${qs}`);
    const data = await handle<{ jobs: IngestionJob[] }>(res);
    return data.jobs || [];
  },

  async ingestionJob(id: number): Promise<IngestionJob> {
    const res = await fetch(`/api/ingestion-jobs/${id}`);
    return handle<IngestionJob>(res);
  },

  async collectionInfo(): Promise<CollectionInfo> {
    const res = await fetch("/api/collection/info");
    return handle<CollectionInfo>(res);
  },

  async deleteDocument(source: string): Promise<unknown> {
    const res = await fetch(
      `/api/collection/document?source=${encodeURIComponent(source)}`,
      { method: "DELETE" }
    );
    return handle(res);
  },

  async resetCollection(): Promise<unknown> {
    const res = await fetch("/api/collection", { method: "DELETE" });
    return handle(res);
  },

  async query(
    question: string,
    k = 10,
    rerank = false,
    conversationId?: string | number | null
  ): Promise<QueryResponse> {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        openai_api_key: "",
        k,
        rerank,
        conversation_id: conversationId != null ? String(conversationId) : null,
      }),
    });
    return handle<QueryResponse>(res);
  },

  /**
   * Open the SSE stream endpoint. Caller is responsible for reading the body.
   */
  async queryStream(
    question: string,
    k = 6,
    rerank = false,
    signal?: AbortSignal,
    conversationId?: string | number | null
  ): Promise<Response> {
    const res = await fetch("/api/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        openai_api_key: "",
        k,
        rerank,
        conversation_id: conversationId != null ? String(conversationId) : null,
      }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || "Erreur streaming");
    }
    return res;
  },

  async conversations(): Promise<Conversation[]> {
    const res = await fetch("/api/conversations");
    return handle<Conversation[]>(res);
  },

  async createConversation(title?: string): Promise<Conversation> {
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    return handle<Conversation>(res);
  },

  async conversation(id: number): Promise<ConversationDetail> {
    const res = await fetch(`/api/conversations/${id}`);
    return handle<ConversationDetail>(res);
  },

  async postMessage(
    id: number,
    role: "user" | "assistant",
    content: string,
    sources?: unknown
  ): Promise<{ status: string; message_id?: number }> {
    const res = await fetch(`/api/conversations/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, content, sources }),
    });
    return handle<{ status: string; message_id?: number }>(res);
  },

  async setMessageFeedback(
    messageId: number,
    rating: 1 | -1,
    comment?: string | null,
  ): Promise<unknown> {
    const res = await fetch(`/api/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment ?? null }),
    });
    return handle(res);
  },

  async clearMessageFeedback(messageId: number): Promise<unknown> {
    const res = await fetch(`/api/messages/${messageId}/feedback`, {
      method: "DELETE",
    });
    return handle(res);
  },

  async deleteConversation(id: number): Promise<unknown> {
    const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    return handle(res);
  },

  async renameConversation(id: number, title: string): Promise<unknown> {
    const res = await fetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    return handle(res);
  },

  async clients(): Promise<Client[]> {
    const res = await fetch("/api/workspace/clients");
    const data = await handle<{ clients: Client[] }>(res);
    return data.clients || [];
  },

  async createClient(name: string): Promise<Client> {
    const res = await fetch("/api/workspace/clients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    return handle<Client>(res);
  },

  async deleteClient(id: number): Promise<unknown> {
    const res = await fetch(`/api/workspace/clients/${id}`, {
      method: "DELETE",
    });
    return handle(res);
  },

  async clientCdcs(clientId: number): Promise<ClientCdcsResponse> {
    const res = await fetch(`/api/workspace/clients/${clientId}/cdcs`);
    return handle<ClientCdcsResponse>(res);
  },

  async uploadCdc(clientId: number, file: File): Promise<{ id: number; filename: string }> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/workspace/clients/${clientId}/cdcs`, {
      method: "POST",
      body: fd,
    });
    return handle(res);
  },

  async cdc(id: number): Promise<CdcDetail> {
    const res = await fetch(`/api/workspace/cdcs/${id}`);
    return handle<CdcDetail>(res);
  },

  async deleteCdc(id: number): Promise<unknown> {
    const res = await fetch(`/api/workspace/cdcs/${id}`, { method: "DELETE" });
    return handle(res);
  },

  async analyseCdc(id: number, forceRefresh = false): Promise<AnalysisJob> {
    const fd = new FormData();
    fd.append("openai_api_key", "");
    fd.append("force_refresh", forceRefresh ? "true" : "false");
    const res = await fetch(`/api/workspace/cdcs/${id}/analyse`, {
      method: "POST",
      body: fd,
    });
    return handle<AnalysisJob>(res);
  },

  /**
   * Download an analysis export (xlsx or md) by triggering a save dialog.
   * Throws on backend error so the caller can show a toast.
   */
  async downloadCdcExport(id: number, fmt: "xlsx" | "md"): Promise<void> {
    const res = await fetch(`/api/workspace/cdcs/${id}/export/${fmt}`);
    if (!res.ok) {
      let detail = `Erreur ${res.status}`;
      try {
        const j = (await res.json()) as { detail?: string };
        if (j.detail) detail = j.detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : `analyse.${fmt}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  async getAnalysisFeedback(
    analysisId: number | string,
  ): Promise<RequirementFeedback[]> {
    const res = await fetch(
      `/api/workspace/analyses/${encodeURIComponent(String(analysisId))}/feedback`,
    );
    const data = await handle<{ analysis_id: string; feedback: RequirementFeedback[] }>(
      res,
    );
    return data.feedback || [];
  },

  async submitFeedback(
    analysisId: number | string,
    requirementId: string,
    vote: "up" | "down",
    comment?: string | null,
  ): Promise<RequirementFeedback> {
    const res = await fetch(
      `/api/workspace/analyses/${encodeURIComponent(
        String(analysisId),
      )}/requirements/${encodeURIComponent(requirementId)}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vote, comment: comment ?? null }),
      },
    );
    return handle<RequirementFeedback>(res);
  },

  async deleteFeedback(
    analysisId: number | string,
    requirementId: string,
  ): Promise<void> {
    const res = await fetch(
      `/api/workspace/analyses/${encodeURIComponent(
        String(analysisId),
      )}/requirements/${encodeURIComponent(requirementId)}/feedback`,
      { method: "DELETE" },
    );
    await handle(res);
  },

  async getQualityDashboard(
    analysisId: number | string,
  ): Promise<QualityDashboard> {
    const res = await fetch(
      `/api/workspace/analyses/${encodeURIComponent(
        String(analysisId),
      )}/quality-dashboard`,
    );
    return handle<QualityDashboard>(res);
  },

  async repassAnalysis(
    analysisId: number | string,
    options?: { requirementIds?: string[]; force?: boolean },
  ): Promise<AnalysisJob> {
    const body: Record<string, unknown> = {};
    if (options?.requirementIds && options.requirementIds.length > 0) {
      body.requirement_ids = options.requirementIds;
    }
    if (options?.force) body.force = true;
    const res = await fetch(
      `/api/workspace/analyses/${encodeURIComponent(
        String(analysisId),
      )}/repass`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    return handle<AnalysisJob>(res);
  },

  /**
   * Déclenche le téléchargement du CSV feedback (UTF-8 BOM, séparateur ';').
   */
  async exportFeedbackCsv(analysisId: number | string): Promise<void> {
    const url = `/api/workspace/analyses/${encodeURIComponent(
      String(analysisId),
    )}/feedback/export`;
    const res = await fetch(url);
    if (!res.ok) {
      let detail = `Erreur ${res.status}`;
      try {
        const j = (await res.json()) as { detail?: string };
        if (j.detail) detail = j.detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : `feedback_${analysisId}.csv`;
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objUrl), 1000);
  },

  async analysisJob(id: number): Promise<AnalysisJob> {
    const res = await fetch(`/api/analysis-jobs/${id}`);
    return handle<AnalysisJob>(res);
  },

  async analysisJobs(opts?: {
    statusFilter?: string;
    cdcId?: number;
  }): Promise<AnalysisJob[]> {
    const params = new URLSearchParams();
    if (opts?.statusFilter) params.set("status", opts.statusFilter);
    if (opts?.cdcId !== undefined) params.set("cdc_id", String(opts.cdcId));
    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await fetch(`/api/analysis-jobs${qs}`);
    const data = await handle<{ jobs: AnalysisJob[] }>(res);
    return data.jobs || [];
  },

  // Self-service password change
  async changePassword(
    current_password: string,
    new_password: string,
  ): Promise<{ ok: boolean }> {
    const res = await fetch("/api/auth/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password, new_password }),
    });
    return handle<{ ok: boolean }>(res);
  },

  // Admin: list users
  async adminListUsers(): Promise<AdminUser[]> {
    const res = await fetch("/api/admin/users");
    const data = await handle<{ users: AdminUser[] }>(res);
    return data.users || [];
  },

  // Admin: create user
  async adminCreateUser(input: {
    username: string;
    name?: string;
    email?: string;
    password: string;
    role?: "admin" | "user";
  }): Promise<{ user: AdminUser }> {
    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return handle<{ user: AdminUser }>(res);
  },

  // Admin: reset password
  async adminResetPassword(
    username: string,
    new_password: string,
  ): Promise<{ ok: boolean }> {
    const res = await fetch(
      `/api/admin/users/${encodeURIComponent(username)}/password`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password }),
      },
    );
    return handle<{ ok: boolean }>(res);
  },

  // Admin: change role
  async adminSetRole(
    username: string,
    role: "admin" | "user",
  ): Promise<{ ok: boolean }> {
    const res = await fetch(
      `/api/admin/users/${encodeURIComponent(username)}/role`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      },
    );
    return handle<{ ok: boolean }>(res);
  },

  // Admin: delete user
  async adminDeleteUser(username: string): Promise<{ ok: boolean }> {
    const res = await fetch(
      `/api/admin/users/${encodeURIComponent(username)}`,
      { method: "DELETE" },
    );
    return handle<{ ok: boolean }>(res);
  },

  // Admin LLM settings
  async adminGetLlmSettings(): Promise<LlmSettingsResponse> {
    const res = await fetch("/api/admin/settings/llm");
    return handle<LlmSettingsResponse>(res);
  },

  async adminSetLlmSettings(
    values: Partial<LlmSettings>,
  ): Promise<LlmSettingsResponse> {
    const res = await fetch("/api/admin/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    return handle<LlmSettingsResponse>(res);
  },

  // RAGAS evaluation (multipart CSV upload)
  async evaluateRagas(
    file: File,
    openai_api_key: string,
  ): Promise<{ per_question: RagasPerQuestion[]; aggregate: RagasMetrics }> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("openai_api_key", openai_api_key);
    const res = await fetch("/api/evaluate", { method: "POST", body: fd });
    return handle<{ per_question: RagasPerQuestion[]; aggregate: RagasMetrics }>(
      res,
    );
  },

  // -------------------------------------------------------------------
  // Page Admin Planificateur
  // -------------------------------------------------------------------

  async listSchedules(): Promise<Schedule[]> {
    const res = await fetch("/api/admin/schedules");
    const data = await handle<{ schedules: Schedule[] }>(res);
    return data.schedules || [];
  },

  async createSchedule(input: {
    source: string;
    cron_expression: string;
    label?: string | null;
    pause_chat_during_refresh?: boolean;
    enabled?: boolean;
  }): Promise<Schedule> {
    const res = await fetch("/api/admin/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: input.source,
        cron_expression: input.cron_expression,
        label: input.label ?? null,
        pause_chat_during_refresh: !!input.pause_chat_during_refresh,
        enabled: input.enabled !== false,
      }),
    });
    return handle<Schedule>(res);
  },

  async updateSchedule(
    id: number,
    input: {
      cron_expression?: string;
      label?: string | null;
      pause_chat_during_refresh?: boolean;
      enabled?: boolean;
    },
  ): Promise<Schedule> {
    const res = await fetch(`/api/admin/schedules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return handle<Schedule>(res);
  },

  async deleteSchedule(id: number): Promise<unknown> {
    const res = await fetch(`/api/admin/schedules/${id}`, { method: "DELETE" });
    return handle(res);
  },

  async runScheduleNow(id: number): Promise<RefreshJob> {
    const res = await fetch(`/api/admin/schedules/${id}/run-now`, {
      method: "POST",
    });
    return handle<RefreshJob>(res);
  },

  async runSourceNow(source: string): Promise<RefreshJob> {
    const res = await fetch(
      `/api/admin/sources/${encodeURIComponent(source)}/run-now`,
      { method: "POST" },
    );
    return handle<RefreshJob>(res);
  },

  async listJobs(opts?: {
    source?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<RefreshJob[]> {
    const params = new URLSearchParams();
    if (opts?.source) params.set("source", opts.source);
    if (opts?.status) params.set("status", opts.status);
    if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
    const qs = params.toString();
    const res = await fetch(`/api/admin/jobs${qs ? `?${qs}` : ""}`);
    const data = await handle<{ jobs: RefreshJob[] }>(res);
    return data.jobs || [];
  },

  async getCurrentJob(): Promise<RefreshJob | null> {
    const res = await fetch("/api/admin/jobs/current");
    const data = await handle<{ job: RefreshJob | null }>(res);
    return data.job ?? null;
  },

  async getJob(id: number): Promise<RefreshJob> {
    const res = await fetch(`/api/admin/jobs/${id}`);
    return handle<RefreshJob>(res);
  },

  async cancelJob(id: number): Promise<unknown> {
    const res = await fetch(`/api/admin/jobs/${id}/cancel`, { method: "POST" });
    return handle(res);
  },

  // -------------------------------------------------------------------
  // Maintenance avancée
  // -------------------------------------------------------------------

  async maintenanceReembedSource(source: string): Promise<RefreshJob> {
    const res = await fetch(
      `/api/admin/maintenance/reembed/${encodeURIComponent(source)}`,
      { method: "POST" },
    );
    return handle<RefreshJob>(res);
  },

  async maintenanceReembedAll(): Promise<RefreshJob> {
    const res = await fetch("/api/admin/maintenance/reembed-all", {
      method: "POST",
    });
    return handle<RefreshJob>(res);
  },

  async maintenanceOptimize(collection: string): Promise<RefreshJob> {
    const res = await fetch(
      `/api/admin/maintenance/optimize/${encodeURIComponent(collection)}`,
      { method: "POST" },
    );
    return handle<RefreshJob>(res);
  },

  async maintenanceIntegrityCheck(): Promise<RefreshJob> {
    const res = await fetch("/api/admin/maintenance/integrity-check", {
      method: "POST",
    });
    return handle<RefreshJob>(res);
  },

  async maintenanceQdrantStats(): Promise<{
    collections: QdrantCollectionStat[];
    error?: string;
  }> {
    const res = await fetch("/api/admin/maintenance/qdrant-stats");
    return handle<{ collections: QdrantCollectionStat[]; error?: string }>(res);
  },

  // -------------------------------------------------------------------
  // Notifications
  // -------------------------------------------------------------------

  async listUnreadNotifications(): Promise<{
    unread_count: number;
    items: AppNotification[];
  }> {
    const res = await fetch("/api/notifications/unread");
    return handle<{ unread_count: number; items: AppNotification[] }>(res);
  },

  async listNotifications(limit = 20): Promise<AppNotification[]> {
    const res = await fetch(`/api/notifications?limit=${limit}`);
    const data = await handle<{ items: AppNotification[] }>(res);
    return data.items || [];
  },

  async markNotificationRead(id: number): Promise<unknown> {
    const res = await fetch(`/api/notifications/${id}/read`, { method: "POST" });
    return handle(res);
  },

  async markAllNotificationsRead(): Promise<unknown> {
    const res = await fetch("/api/notifications/read-all", { method: "POST" });
    return handle(res);
  },
};
