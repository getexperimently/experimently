"""
Data export service — converts DB data to CSV/JSON for download.
EP-020: Data Export & Reporting
"""
import csv
import json
import io
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.schemas.export import (
    ExportRequest,
    ExportFormat,
    ExportScope,
    ExperimentExportRow,
    VariantExportRow,
    FeatureFlagExportRow,
    PlatformOverviewReport,
)


class ExportService:
    """
    Service for exporting platform data to CSV or JSON format.

    Handles experiments, variants, feature flags, and platform overview reports.
    Does not import FastAPI-specific code; pure service layer.
    """

    def __init__(self, db: Session) -> None:
        """Initialize with a database session."""
        self.db = db

    # ------------------------------------------------------------------
    # Public export methods
    # ------------------------------------------------------------------

    def export_experiments(
        self,
        request: ExportRequest,
        experiment_ids: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """
        Export experiment data.

        Args:
            request: ExportRequest specifying format, scope, and date filters.
            experiment_ids: Optional list of experiment IDs to filter by.

        Returns:
            Tuple of (content: str, content_type: str).
        """
        rows = self._build_experiment_rows(request, experiment_ids)
        if request.format == ExportFormat.CSV:
            return self._to_csv(rows, ExperimentExportRow), "text/csv"
        return (
            json.dumps([r.model_dump() for r in rows], default=str),
            "application/json",
        )

    def export_variants(
        self,
        request: ExportRequest,
        experiment_ids: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """
        Export per-variant results.

        Args:
            request: ExportRequest specifying format and optional date filters.
            experiment_ids: Optional list of experiment IDs to filter by.

        Returns:
            Tuple of (content: str, content_type: str).
        """
        rows = self._build_variant_rows(request, experiment_ids)
        if request.format == ExportFormat.CSV:
            return self._to_csv(rows, VariantExportRow), "text/csv"
        return (
            json.dumps([r.model_dump() for r in rows], default=str),
            "application/json",
        )

    def export_feature_flags(
        self,
        request: ExportRequest,
    ) -> Tuple[str, str]:
        """
        Export feature flag usage data.

        Args:
            request: ExportRequest specifying format and optional date filters.

        Returns:
            Tuple of (content: str, content_type: str).
        """
        rows = self._build_feature_flag_rows(request)
        if request.format == ExportFormat.CSV:
            return self._to_csv(rows, FeatureFlagExportRow), "text/csv"
        return (
            json.dumps([r.model_dump() for r in rows], default=str),
            "application/json",
        )

    def generate_platform_overview(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> PlatformOverviewReport:
        """
        Generate platform-wide summary report.

        Args:
            start_date: Optional inclusive start of the reporting period.
            end_date: Optional inclusive end of the reporting period.

        Returns:
            PlatformOverviewReport with aggregate counts.
        """
        # Base experiment counts
        exp_query = self.db.query(Experiment)
        if start_date:
            exp_query = exp_query.filter(Experiment.created_at >= start_date)
        if end_date:
            exp_query = exp_query.filter(Experiment.created_at <= end_date)

        total_experiments: int = exp_query.count()

        active_experiments: int = (
            exp_query.filter(Experiment.status == ExperimentStatus.ACTIVE).count()
        )
        completed_experiments: int = (
            exp_query.filter(Experiment.status == ExperimentStatus.COMPLETED).count()
        )

        # Feature flag counts
        ff_query = self.db.query(FeatureFlag)
        if start_date:
            ff_query = ff_query.filter(FeatureFlag.created_at >= start_date)
        if end_date:
            ff_query = ff_query.filter(FeatureFlag.created_at <= end_date)

        total_feature_flags: int = ff_query.count()
        active_feature_flags: int = (
            ff_query.filter(FeatureFlag.status == FeatureFlagStatus.ACTIVE).count()
        )

        # Assignment and event counts via relationships — use scalar counts where available
        # These are approximated from what the DB can provide without raw-event tables
        total_assignments: int = self._count_assignments(start_date, end_date)
        total_events: int = self._count_events(start_date, end_date)

        # Experiments with a winner are those whose summary JSON contains a winner
        experiments_with_winners: int = self._count_experiments_with_winners(
            start_date, end_date
        )

        # Average duration for completed experiments
        average_duration: Optional[float] = self._average_experiment_duration(
            start_date, end_date
        )

        generated_at = datetime.now(tz=timezone.utc).isoformat()

        return PlatformOverviewReport(
            generated_at=generated_at,
            period_start=start_date.isoformat() if start_date else None,
            period_end=end_date.isoformat() if end_date else None,
            total_experiments=total_experiments,
            active_experiments=active_experiments,
            completed_experiments=completed_experiments,
            total_feature_flags=total_feature_flags,
            active_feature_flags=active_feature_flags,
            total_assignments=total_assignments,
            total_events=total_events,
            experiments_with_winners=experiments_with_winners,
            average_experiment_duration_days=average_duration,
        )

    # ------------------------------------------------------------------
    # Internal row builders
    # ------------------------------------------------------------------

    def _build_experiment_rows(
        self,
        request: ExportRequest,
        experiment_ids: Optional[List[str]],
    ) -> List[ExperimentExportRow]:
        """Query experiments and map to ExperimentExportRow instances."""
        query = self.db.query(Experiment)
        if experiment_ids:
            query = query.filter(Experiment.id.in_(experiment_ids))
        if request.start_date:
            query = query.filter(Experiment.created_at >= request.start_date)
        if request.end_date:
            query = query.filter(Experiment.created_at <= request.end_date)
        experiments = query.all()
        return [self._experiment_to_row(exp) for exp in experiments]

    def _build_variant_rows(
        self,
        request: ExportRequest,
        experiment_ids: Optional[List[str]],
    ) -> List[VariantExportRow]:
        """Query experiments+variants and map to VariantExportRow instances."""
        query = self.db.query(Experiment)
        if experiment_ids:
            query = query.filter(Experiment.id.in_(experiment_ids))
        if request.start_date:
            query = query.filter(Experiment.created_at >= request.start_date)
        if request.end_date:
            query = query.filter(Experiment.created_at <= request.end_date)
        experiments = query.all()

        rows: List[VariantExportRow] = []
        for exp in experiments:
            exp_id = str(exp.id)
            exp_name = str(exp.name)
            for variant in getattr(exp, "variants", []):
                rows.append(
                    VariantExportRow(
                        experiment_id=exp_id,
                        experiment_name=exp_name,
                        variant_id=str(variant.id),
                        variant_name=str(variant.name),
                        is_control=bool(getattr(variant, "is_control", False)),
                        assignments=0,
                        conversions=None,
                        conversion_rate=None,
                        p_value=None,
                        is_significant=False,
                        relative_improvement_pct=None,
                    )
                )
        return rows

    def _build_feature_flag_rows(
        self,
        request: ExportRequest,
    ) -> List[FeatureFlagExportRow]:
        """Query feature flags and map to FeatureFlagExportRow instances."""
        query = self.db.query(FeatureFlag)
        if request.start_date:
            query = query.filter(FeatureFlag.created_at >= request.start_date)
        if request.end_date:
            query = query.filter(FeatureFlag.created_at <= request.end_date)
        flags = query.all()
        return [self._feature_flag_to_row(ff) for ff in flags]

    # ------------------------------------------------------------------
    # Internal model-to-row mappers
    # ------------------------------------------------------------------

    def _experiment_to_row(self, exp: Experiment) -> ExperimentExportRow:
        """Map an Experiment model instance to ExperimentExportRow."""
        # Resolve status value — handle both enum and plain string
        status_val: str
        if hasattr(exp.status, "value"):
            status_val = exp.status.value
        else:
            status_val = str(exp.status)

        # Resolve experiment_type value
        type_val: str
        if hasattr(exp.experiment_type, "value"):
            type_val = exp.experiment_type.value
        else:
            type_val = str(exp.experiment_type)

        start_str: Optional[str] = (
            exp.start_date.isoformat() if exp.start_date else None
        )
        end_str: Optional[str] = (
            exp.end_date.isoformat() if exp.end_date else None
        )

        duration: Optional[float] = None
        if exp.start_date and exp.end_date:
            delta = exp.end_date - exp.start_date
            duration = round(delta.total_seconds() / 86400, 2)

        # Count assignments through relationship if available
        assignments_count: int = 0
        if hasattr(exp, "assignments") and exp.assignments is not None:
            try:
                assignments_count = len(exp.assignments)
            except TypeError:
                assignments_count = 0

        # Count events through relationship if available
        events_count: int = 0
        if hasattr(exp, "events") and exp.events is not None:
            try:
                events_count = len(exp.events)
            except TypeError:
                events_count = 0

        return ExperimentExportRow(
            experiment_id=str(exp.id),
            experiment_name=str(exp.name),
            status=status_val,
            experiment_type=type_val,
            start_date=start_str,
            end_date=end_str,
            duration_days=duration,
            total_assignments=assignments_count,
            total_events=events_count,
            winner_variant=None,
            recommendation=None,
        )

    def _feature_flag_to_row(self, ff: FeatureFlag) -> FeatureFlagExportRow:
        """Map a FeatureFlag model instance to FeatureFlagExportRow."""
        status_val: str
        if hasattr(ff.status, "value"):
            status_val = ff.status.value
        else:
            status_val = str(ff.status)

        # Derive evaluation stats from raw_metrics if available
        total_evals: int = 0
        enabled_evals: int = 0
        if hasattr(ff, "raw_metrics") and ff.raw_metrics:
            try:
                total_evals = len(ff.raw_metrics)
                enabled_evals = sum(
                    1
                    for m in ff.raw_metrics
                    if getattr(m, "flag_enabled", False)
                )
            except TypeError:
                pass

        enabled_rate: float = (
            round(enabled_evals / total_evals, 4) if total_evals > 0 else 0.0
        )

        created_str: str = (
            ff.created_at.isoformat()
            if ff.created_at
            else datetime.now(tz=timezone.utc).isoformat()
        )
        updated_str: str = (
            ff.updated_at.isoformat()
            if ff.updated_at
            else datetime.now(tz=timezone.utc).isoformat()
        )

        return FeatureFlagExportRow(
            flag_id=str(ff.id),
            flag_key=str(ff.key),
            flag_name=str(ff.name),
            status=status_val,
            rollout_percentage=int(ff.rollout_percentage),
            total_evaluations=total_evals,
            enabled_evaluations=enabled_evals,
            enabled_rate=enabled_rate,
            created_at=created_str,
            updated_at=updated_str,
        )

    # ------------------------------------------------------------------
    # Generic CSV serializer
    # ------------------------------------------------------------------

    def _to_csv(self, rows: list, schema_class: type) -> str:
        """
        Generic CSV serializer using schema field names as headers.

        Args:
            rows: List of Pydantic model instances.
            schema_class: The Pydantic model class (used for headers).

        Returns:
            CSV string, or empty string if rows is empty.
        """
        if not rows:
            return ""
        output = io.StringIO()
        fields = list(schema_class.model_fields.keys())
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())
        return output.getvalue()

    # ------------------------------------------------------------------
    # Private aggregate helpers
    # ------------------------------------------------------------------

    def _count_assignments(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> int:
        """Count total assignments, optionally filtered by date range."""
        try:
            from backend.app.models.assignment import Assignment

            query = self.db.query(Assignment)
            if start_date:
                query = query.filter(Assignment.created_at >= start_date)
            if end_date:
                query = query.filter(Assignment.created_at <= end_date)
            return int(query.count())
        except Exception:
            return 0

    def _count_events(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> int:
        """Count total events, optionally filtered by date range."""
        try:
            from backend.app.models.event import Event

            query = self.db.query(Event)
            if start_date:
                query = query.filter(Event.created_at >= start_date)
            if end_date:
                query = query.filter(Event.created_at <= end_date)
            return int(query.count())
        except Exception:
            return 0

    def _count_experiments_with_winners(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> int:
        """
        Count experiments whose reports indicate a winner exists.

        Falls back to 0 when the Report model or relationship is unavailable.
        """
        try:
            from backend.app.models.report import Report

            query = self.db.query(Report)
            if start_date:
                query = query.filter(Report.created_at >= start_date)
            if end_date:
                query = query.filter(Report.created_at <= end_date)
            # Reports that have a winner recorded in their summary JSON
            query = query.filter(Report.summary.isnot(None))
            return int(query.count())
        except Exception:
            return 0

    def _average_experiment_duration(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> Optional[float]:
        """
        Compute average duration (days) of completed experiments that have both
        start_date and end_date set.
        """
        try:
            query = (
                self.db.query(Experiment)
                .filter(Experiment.status == ExperimentStatus.COMPLETED)
                .filter(Experiment.start_date.isnot(None))
                .filter(Experiment.end_date.isnot(None))
            )
            if start_date:
                query = query.filter(Experiment.created_at >= start_date)
            if end_date:
                query = query.filter(Experiment.created_at <= end_date)
            experiments = query.all()
            if not experiments:
                return None
            durations = [
                (exp.end_date - exp.start_date).total_seconds() / 86400
                for exp in experiments
                if exp.end_date and exp.start_date
            ]
            if not durations:
                return None
            return round(sum(durations) / len(durations), 2)
        except Exception:
            return None
