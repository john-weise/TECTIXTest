// src/types/admin.ts

/** Basic user record returned by /api/admin/users */
export type User = {
  username: string;
  is_admin: boolean;
  twofa_enabled?: boolean;
};

/** Log file info returned by /api/admin/logs/info */
export type LogInfo = {
  path: string;
  exists: boolean;
  size_bytes: number;
  mtime: number | null; // POSIX timestamp (seconds)
};

/** Tail API response for /api/admin/logs/tail */
export type TailResponse = {
  path: string;
  exists: boolean;
  size_bytes: number;
  slice_start_byte: number;
  returned_bytes: number;
  line_count: number;
  lines: string[];
  truncated: boolean;
};

/** Single search hit returned by /api/admin/logs/search */
export type LogHit = {
  line_no: number;
  line: string;
  match: [number, number];
  before?: string[];
  after?: string[];
};

/** Search response payload */
export type SearchResponse = {
  pattern: string;
  case_sensitive: boolean;
  hits: LogHit[];
  hit_count: number;
  truncated: boolean;
};

/** Row returned by /api/admin/systems (pydantic SystemSummary) */
export interface SystemSummary {
  system_id: number;
  time_added: string;
  last_scanned: string | null;
  has_csv: boolean;
  scan_policy: string | null;  // <-- add this
}

/** Payload for single-system add/upsert (AddSystemInput) */
export type AddSystemInput = {
  system_id: number;
  csv_path: string | null;
};

/** Payload for batch add/upsert (AddSystemBatchInput) */
export type AddSystemBatchInput = {
  items: AddSystemInput[];
};

/**
 * Response from POST /api/admin/systems
 * - Single mode: SystemSummary
 * - Batch mode: SystemSummary[]
 */
export type AddSystemResponse = SystemSummary | SystemSummary[];

/** Row returned by /api/autodiscovery */
export type AutodiscoveryItem = {
  system_id: number;
  has_policy: boolean;
  policies: string[];
};
