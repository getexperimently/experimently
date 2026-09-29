/**
 * Core-profile stand-in for
 * `@modules/components/warehouse/runs/WarehouseAnalysisSection`: a core build
 * has no warehouse analysis, so the experiment page shows no warehouse
 * section and calls no warehouse route.
 */
export interface WarehouseExperiment {
  id: string;
  key: string | null;
  start_date?: string | null;
}

export interface WarehouseAnalysisSectionProps {
  experiment: WarehouseExperiment;
}

export default function WarehouseAnalysisSection(_props: WarehouseAnalysisSectionProps): null {
  return null;
}
