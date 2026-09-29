export type ChangeStatus =
  | "baseline"
  | "unchanged"
  | "changed"
  | "blocked"
  | "error";

export type AlertStatus = "pending" | "acknowledged" | "dismissed";

export type HumanLoopState =
  | "no_action"
  | "notification"
  | "approval_required"
  | "blocked_requires_user";

export type AgentTraceEntry = {
  agent: "supervisor" | "monitoring" | "analysis" | "action";
  role: string;
  summary: string;
};

export type Monitor = {
  id: string;
  task_id: string;
  goal: string;
  url: string;
  kind?: "website" | "gmail";
  name?: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string | null;
  last_checked_at: string | null;
  last_changed_at?: string | null;
  previous_content_hash: string | null;
  last_change: string | null;
  initialized?: boolean;
  status: string;
};

export type ObservedFact = {
  field?: string | null;
  value: string;
  evidence?: string | null;
  source_excerpt?: string | null;
  heading?: string | null;
};

export type Observation = {
  id: string;
  monitor_id: string;
  content_hash: string;
  summary: string;
  checked_at: string;
  meaningful_change: boolean | null;
  reason: string | null;
  action_required: boolean | null;
  change_status: ChangeStatus | null;
  agents: string[];
  agent_trace: AgentTraceEntry[];
  observed_facts?: string[];
  observed_fact_records?: ObservedFact[];
  relevant_excerpt?: string | null;
  title?: string | null;
  fetch_method?: "http" | "browser" | null;
  source_url?: string | null;
};

export type GmailMatchedEmail = {
  id: string;
  monitor_id: string;
  message_id: string;
  alert_id: string | null;
  subject: string;
  sender: string;
  received_at: string | null;
  preview: string;
  relevant: boolean;
  reason: string;
  summary: string;
  action: string;
  created_at: string;
};

export type MonitorDetail = Monitor & {
  latest_observation: Observation | null;
  observations: Observation[];
  matched_emails?: GmailMatchedEmail[];
  last_email_received_at?: string | null;
};

export type MonitorCheckResult = {
  monitor_id: string;
  goal: string;
  url: string;
  status?: "initialized" | "unchanged" | "changed" | "blocked" | "error";
  changed: boolean;
  change_status: ChangeStatus;
  summary: string;
  old_content?: string | null;
  new_content?: string | null;
  previous_checked_at: string | null;
  checked_at: string;
  tool_used: boolean;
  content_hash?: string;
  meaningful_change?: boolean | null;
  action_required?: boolean | null;
  alert_id?: string | null;
  action_type?: string | null;
  human_loop_state?: HumanLoopState | null;
  agents?: string[];
  agent_trace?: AgentTraceEntry[];
  observed_facts?: string[];
  observed_fact_records?: ObservedFact[];
  relevant_excerpt?: string | null;
  fetch_method?: "http" | "browser" | null;
  title?: string | null;
  hash_changed?: boolean;
  message?: string | null;
  result_status?: string | null;
  previous_observation?: string | null;
  current_observation?: string | null;
};

export type SystemStatus = {
  backend: "ok";
  enabled_monitors: number;
  total_monitors: number;
  last_checked_at: string | null;
  scheduler_interval_seconds?: number;
  scheduler_interval_minutes: number;
  scheduler: "ok" | "stale" | "never" | "idle";
  message: string;
};

export type MonitorCreateInput = {
  goal: string;
  url?: string;
  kind?: "website" | "gmail";
};

export type Alert = {
  id: string;
  alert_id: string;
  monitor_id: string;
  content_hash: string;
  summary: string;
  reason: string;
  action_required: boolean;
  status: AlertStatus;
  created_at: string;
  updated_at: string | null;
  action_type: string | null;
  human_loop_state: string | null;
  user_notification: string | null;
  notification_status: string | null;
  source?: string;
};
