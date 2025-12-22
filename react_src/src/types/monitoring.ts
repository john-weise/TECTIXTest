// src/types/monitoring.ts
export type ContinuousMonitoringItem = {
  system_id: number;
  score: number;                // 0..100
  last_scanned: string | null;  // ISO or null
  monitored: boolean;           // green/red light
};

export interface CompliancePoint {
  run_id: string;
  ts_epoch: number;
  ts_iso: string;
  score: number | null;
}

export interface ComplianceOverTimeResponse {
  system_id: number;
  has_data: boolean;
  first_ts_iso: string | null;
  last_ts_iso: string | null;
  points: CompliancePoint[];
}
