import type { AgentResponse, User } from "@/lib/types";

export const answered: AgentResponse = {
  correlation_id: "6f1c2b9e-1d2a-4a5b-9c1e-3f4d5e6a7b8c",
  thread_id: "t",
  status: "ANSWERED",
  message: null,
  answer: "Revenue in Europe last quarter was 81,234.50.",
  low_confidence: false,
  low_confidence_label: null,
  chart: { type: "metric_card", x: null, y: ["revenue"], data: [{ revenue: 81234.5 }], title: null, reason: "One number." },
  table: { columns: ["revenue"], rows: [[81234.5]], page: 1, page_size: 50, total_rows: 1, total_pages: 1, truncated: false },
  row_count: 1,
  sql: { text: "SELECT SUM(x) AS revenue FROM orders", description: "Sums order revenue for European customers." },
  assumptions: ["Revenue includes discounts."],
  date_range: { from_date: "2025-01-01", to_date: "2025-03-31", label: "Last quarter = 1 Jan to 31 Mar 2025" },
  notices: [],
  interpreted_as: null,
  clarification: null,
  block: null,
};

export const blocked: AgentResponse = {
  ...answered,
  status: "BLOCKED",
  answer: null,
  chart: null,
  table: null,
  row_count: 0,
  sql: { text: null, description: null },
  assumptions: [],
  date_range: null,
  message: "Only read-only questions are allowed.",
  block: { reason_code: "WRITE_REQUEST", message: "Only read-only questions are allowed." },
};

export const salesUser: User = {
  user_id: "11111111-1111-1111-1111-111111111111",
  username: "sales.europe",
  display_name: "Europe Sales",
  role: "sales_manager",
  region: "EUROPE",
  is_active: true,
};

export const adminUser: User = { ...salesUser, username: "admin", display_name: "Admin", role: "admin", region: null };
