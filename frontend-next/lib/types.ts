export type UserRole = "admin" | "user" | "guest";

export type User = {
  user_id: string;
  name: string;
  role?: UserRole;
};

export type AdminUser = {
  username: string;
  name: string;
  email: string;
  role: "admin" | "user";
  created_at: string;
};

export type ApiKeyInfo = { has_key: boolean; masked?: string; reason?: string };

export type Health = {
  status: string;
  qdrant_url: string;
  indexed_vectors: Record<string, number>;
};

export type DocumentInfo = {
  source: string;
  chunks: number;
  [key: string]: unknown;
};

export type CollectionInfo = {
  user_id: string;
  documents: DocumentInfo[];
  total_documents: number;
  total_chunks: number;
};

export type IngestionJobStatus = "queued" | "running" | "done" | "error";

export type IngestionJob = {
  id: number;
  user_id: string;
  filename: string;
  status: IngestionJobStatus;
  chunk_count: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type UploadResponse = {
  job_id: number;
  filename: string;
  status: IngestionJobStatus;
  message: string;
};

export type AnalysisJobStatus = "queued" | "running" | "done" | "error";

export type AnalysisJob = {
  id: number;
  user_id: string;
  cdc_id: number;
  status: AnalysisJobStatus;
  force_refresh: boolean;
  analysis_id: number | null;
  report: Report | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  reused?: boolean;
};

export type QuerySource = {
  text: string;
  source: string;
  page?: number | string;
  score?: number;
  rerank_score?: number;
};

export type QueryResponse = {
  answer: string;
  sources: QuerySource[];
};

export type Conversation = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type MessageFeedback = {
  rating: 1 | -1;
  comment?: string | null;
};

export type ChatMessage = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  sources?: QuerySource[];
  created_at?: string;
  feedback?: MessageFeedback | null;
};

export type ConversationDetail = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
};

export type Client = {
  id: number;
  name: string;
  [key: string]: unknown;
};

export type CdcStatus =
  | "pending"
  | "uploaded"
  | "parsing"
  | "analysing"
  | "analyzed"
  | "error"
  | string;

export type Cdc = {
  id: number;
  filename: string;
  status: CdcStatus;
  uploaded_at?: string;
  analysis_id?: number | null;
  coverage_percent?: number | null;
  ext?: string;
  [key: string]: unknown;
};

export type ClientCdcsResponse = {
  client_id: number;
  pipeline_version: string;
  corpus_fingerprint?: string;
  cdcs: Cdc[];
};

export type RequirementStatus =
  | "covered"
  | "partial"
  | "missing"
  | "ambiguous";

export type RequirementSource = {
  source: string;
  page?: number | string;
  text: string;
  score?: number;
};

export type Requirement = {
  id: string;
  title: string;
  category: string;
  description: string;
  criteria?: string[];
  status: RequirementStatus;
  verdict: string;
  evidence: string[];
  sources: RequirementSource[];
  hyde_used?: boolean;
  repass_used?: boolean;
};

export type AnalysisSummary = {
  total: number;
  covered: number;
  partial: number;
  missing: number;
  ambiguous: number;
  coverage_percent: number;
};

export type Report = {
  filename: string;
  summary: AnalysisSummary;
  requirements: Requirement[];
  pipeline_version?: string;
  from_cache?: boolean;
  analysis_id?: number;
  cdc_id?: number;
};

// Analysis row as returned by backend get_latest_analysis:
// flat columns + an embedded `report` that contains summary + requirements.
export type AnalysisRow = {
  id: number;
  cdc_id?: number;
  created_at?: string;
  total?: number;
  covered?: number;
  partial?: number;
  missing?: number;
  ambiguous?: number;
  coverage_percent?: number;
  chunks_processed?: number;
  pipeline_version?: string;
  corpus_fingerprint?: string;
  report?: {
    filename?: string;
    summary?: Partial<AnalysisSummary>;
    requirements?: Requirement[];
    pipeline_version?: string;
    [key: string]: unknown;
  } | null;
};

export type CdcDetail = {
  cdc: Cdc;
  status: CdcStatus;
  pipeline_version: string;
  corpus_fingerprint?: string;
  analysis: AnalysisRow | null;
};

// ---------------------------------------------------------------------------
// Admin — Sources publiques (KB partagée knowledge_base)
// ---------------------------------------------------------------------------

export type SourceLastRun = {
  status: "running" | "done" | "done_with_errors" | "failed";
  started_at: number;
  finished_at: number | null;
  fetched: number;
  chunks: number;
  upserted: number;
  errors: string[];
};

export type SourceState = {
  id: string;
  label: string;
  status:
    | "available"
    | "planned"
    | "needs_credentials";
  domaine: string[];
  requires_credentials?: boolean;
  credentials_configured?: boolean;
  last_run?: SourceLastRun;
};

export type SourcesStatus = {
  kb_collection: string;
  kb_exists: boolean;
  vectors_count: number;
  sources: SourceState[];
};

export type SourceRefreshResponse = {
  source: string;
  status: "accepted" | "already_running" | string;
  message?: string;
};

export type LegifranceCredsState = {
  client_id_configured: boolean;
  client_secret_configured: boolean;
  client_id_masked: string;
};
