export type MetricTrendPoint = {
  date: string;
  value: number;
  secondaryValue?: number;
  signalCoverage?: number;
};

export type GeoTrendSeriesPoint = {
  date: string;
  score: number;
  citations: number;
};

export type GeoTrendApiPoint = {
  date: string;
  score: number;
  citations: number;
  intent: "informational" | "transactional" | "navigational" | null;
};

export type ScoreDistributionPoint = {
  bucket: string;
  index: number;
  count: number;
};
