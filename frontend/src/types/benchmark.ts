export type BenchmarkPercentileStatus = "ok" | "insufficient_data";

export type BenchmarkPercentileResponse = {
  project_id: number;
  metric: string;
  status: BenchmarkPercentileStatus;
  percentile: number | null;
  top_percent: number | null;
  cohort_key: string | null;
  cohort_label: string | null;
  cohort_size: number;
  project_value: number | null;
  period_date: string | null;
};

export type ProprietaryScoreStatus = "ok" | "insufficient_data";

export type ProprietaryScoreResponse = {
  project_id: number;
  score_type: string;
  score_version: string;
  status: ProprietaryScoreStatus;
  value: number | null;
  confidence: "high" | "medium" | "low" | "insufficient";
  data_points_used: number;
  components: Record<string, unknown>;
  weights: Record<string, unknown>;
  computed_at: string;
};
