export type User = { user_id: string; name: string };

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

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: QuerySource[];
  created_at?: string;
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
