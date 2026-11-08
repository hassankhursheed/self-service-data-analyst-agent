// Types mirroring the FastAPI models (app/api/schemas.py, app/agent/response.py).

export type RoleName = "sales_manager" | "finance_analyst" | "operations_manager" | "admin";
export type RegionCode = "EUROPE" | "AMERICAS" | "ROW";
export type QuestionStatus =
  | "RECEIVED"
  | "GUARDRAIL_CHECKED"
  | "UNDERSTOOD"
  | "CLARIFICATION_NEEDED"
  | "SQL_GENERATED"
  | "VALIDATED"
  | "EXECUTED"
  | "EXECUTION_FAILED"
  | "REPAIRING"
  | "ANSWERED"
  | "BLOCKED"
  | "REJECTED"
  | "FAILED";

export interface User {
  user_id: string;
  username: string;
  display_name: string;
  role: RoleName | null;
  region: RegionCode | null;
  is_active: boolean;
}

export interface ChartSpec {
  type: "line" | "bar" | "metric_card" | "none";
  x: string | null;
  y: string[];
  data: Record<string, unknown>[];
  title: string | null;
  reason: string;
}

export interface TablePage {
  columns: string[];
  rows: unknown[][];
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
  truncated: boolean;
}

export interface AnswerItem {
  label: string;
  value: number | null;
  detail: string | null;
}

export interface AgentResponse {
  correlation_id: string | null;
  thread_id: string | null;
  status: QuestionStatus | null;
  message: string | null;
  answer: string | null;
  low_confidence: boolean;
  low_confidence_label: string | null;
  verified?: boolean;
  items?: AnswerItem[];
  chart: ChartSpec | null;
  table: TablePage | null;
  row_count: number;
  sql: { text: string | null; description: string | null };
  assumptions: string[];
  date_range: { from_date: string; to_date: string; label: string } | null;
  notices: string[];
  interpreted_as: string | null;
  clarification: { question: string; options: string[] } | null;
  block: { reason_code: string; message: string } | null;
}

export interface AskResponse extends AgentResponse {
  conversation_id: string;
  question_id: string | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  question_count: number;
}

export interface QuestionSummary {
  id: string;
  correlation_id: string;
  question: string;
  status: string;
  created_at: string;
}

export interface Paged<T> {
  correlation_id: string;
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ConversationDetail {
  correlation_id: string;
  id: string;
  title: string;
  questions: QuestionSummary[];
  latest: AgentResponse | null;
}

export interface UserView {
  id: string;
  username: string;
  display_name: string;
  role: RoleName | null;
  region: RegionCode | null;
  is_active: boolean;
  last_login_at: string | null;
}

export interface BlockedItem {
  id: number;
  correlation_id: string;
  username: string | null;
  role: string | null;
  question: string | null;
  stage: string;
  reason_code: string;
  reason_text: string;
  sql_text: string | null;
  created_at: string;
}

export interface ErrorItem {
  id: number;
  correlation_id: string;
  question_id: string | null;
  username: string | null;
  node_name: string | null;
  error_type: string;
  retryable: boolean;
  error_message: string;
  status: "open" | "rerun" | "resolved";
  created_at: string;
}

export type ReviewKind = "not_helpful" | "blocked" | "failure";

export interface ReviewItem {
  kind: ReviewKind;
  id: string;
  question_id: string | null;
  correlation_id: string | null;
  question: string | null;
  username: string | null;
  role: string | null;
  sql_text: string | null;
  detail: string;
  status: string;
  created_at: string;
}

export interface VerifiedQuery {
  id: string;
  lineage_id: string;
  version: number;
  question_text: string;
  sql_text: string;
  description: string;
  tables_used: string[];
  metrics_used: string[];
  allowed_roles: RoleName[];
  is_active: boolean;
  verified_by: string | null;
  verified_at: string | null;
  source_question_id: string | null;
}

export const BUSINESS_ROLES: RoleName[] = ["sales_manager", "finance_analyst", "operations_manager"];

export interface ApiErrorBody {
  correlation_id: string;
  error: { code: string; message: string };
}

export const ROLE_LABELS: Record<RoleName, string> = {
  sales_manager: "Sales manager",
  finance_analyst: "Finance analyst",
  operations_manager: "Operations manager",
  admin: "Administrator",
};

export const REGION_LABELS: Record<RegionCode, string> = {
  EUROPE: "Europe",
  AMERICAS: "Americas",
  ROW: "Rest of world",
};
