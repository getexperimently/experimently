from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class MonitoringStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an SNS topic for alerts
        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            display_name="Experimentation Platform Alerts",
            topic_name="experimentation-alerts",
        )

        # Add an email subscription (replace with actual email)
        self.alerts_topic.add_subscription(
            sns_subscriptions.EmailSubscription("alerts@example.com")
        )

        # Create a CloudWatch Dashboard
        dashboard = cloudwatch.Dashboard(
            self, "ExperimentationDashboard", dashboard_name="experimentation-platform"
        )

        # Add API Gateway metrics
        api_widget = cloudwatch.GraphWidget(
            title="API Gateway",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Count",
                    dimensions_map={"ApiName": "ExperimentationApi"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Latency",
                    dimensions_map={"ApiName": "ExperimentationApi"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Add Lambda metrics
        lambda_widget = cloudwatch.GraphWidget(
            title="Lambda Functions",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": "AssignmentLambda"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": "EventProcessorLambda"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": "FeatureFlagLambda"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": "AssignmentLambda"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": "EventProcessorLambda"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": "FeatureFlagLambda"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Add DynamoDB metrics
        dynamodb_widget = cloudwatch.GraphWidget(
            title="DynamoDB",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedReadCapacityUnits",
                    dimensions_map={"TableName": "AssignmentsTable"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedWriteCapacityUnits",
                    dimensions_map={"TableName": "AssignmentsTable"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedReadCapacityUnits",
                    dimensions_map={"TableName": "EventsTable"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedWriteCapacityUnits",
                    dimensions_map={"TableName": "EventsTable"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Add Kinesis metrics
        kinesis_widget = cloudwatch.GraphWidget(
            title="Kinesis",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/Kinesis",
                    metric_name="IncomingRecords",
                    dimensions_map={"StreamName": "experimentation-events"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/Kinesis",
                    metric_name="IncomingBytes",
                    dimensions_map={"StreamName": "experimentation-events"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/Kinesis",
                    metric_name="GetRecords.IteratorAgeMilliseconds",
                    dimensions_map={"StreamName": "experimentation-events"},
                    statistic="Maximum",
                    period=Duration.minutes(1),
                )
            ],
        )

        # Add RDS metrics
        rds_widget = cloudwatch.GraphWidget(
            title="RDS Aurora",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="CPUUtilization",
                    dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="DatabaseConnections",
                    dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="FreeableMemory",
                    dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="ReadLatency",
                    dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="WriteLatency",
                    dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Add Redis metrics
        redis_widget = cloudwatch.GraphWidget(
            title="ElastiCache Redis",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/ElastiCache",
                    metric_name="CPUUtilization",
                    dimensions_map={"CacheClusterId": "Redis"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/ElastiCache",
                    metric_name="CurrConnections",
                    dimensions_map={"CacheClusterId": "Redis"},
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/ElastiCache",
                    metric_name="CacheHits",
                    dimensions_map={"CacheClusterId": "Redis"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="AWS/ElastiCache",
                    metric_name="CacheMisses",
                    dimensions_map={"CacheClusterId": "Redis"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Add all widgets to the dashboard
        dashboard.add_widgets(
            api_widget,
            lambda_widget,
            dynamodb_widget,
            kinesis_widget,
            rds_widget,
            redis_widget,
        )

        # Create CloudWatch Alarms

        # API Gateway 5XX errors alarm
        api_5xx_alarm = cloudwatch.Alarm(
            self,
            "Api5xxAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ApiGateway",
                metric_name="5XXError",
                dimensions_map={"ApiName": "ExperimentationApi"},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            evaluation_periods=1,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="API Gateway is returning 5XX errors",
            alarm_name="ExperimentationApi5xxErrors",
        )

        api_5xx_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))

        # Lambda error alarm
        lambda_error_alarm = cloudwatch.Alarm(
            self,
            "LambdaErrorAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": "AssignmentLambda"},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            evaluation_periods=1,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="Lambda function is experiencing errors",
            alarm_name="AssignmentLambdaErrors",
        )

        lambda_error_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # DynamoDB throttling alarm
        dynamodb_throttling_alarm = cloudwatch.Alarm(
            self,
            "DynamoDBThrottlingAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/DynamoDB",
                metric_name="ThrottledRequests",
                dimensions_map={"TableName": "AssignmentsTable"},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            evaluation_periods=1,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="DynamoDB table is experiencing throttling",
            alarm_name="AssignmentsTableThrottling",
        )

        dynamodb_throttling_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Aurora high CPU alarm
        aurora_cpu_alarm = cloudwatch.Alarm(
            self,
            "AuroraCpuAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions_map={"DBClusterIdentifier": "AuroraCluster"},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            evaluation_periods=3,
            threshold=80,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="Aurora cluster CPU is high",
            alarm_name="AuroraHighCPU",
        )

        aurora_cpu_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Kinesis iterator age alarm (potential processing backlog)
        iterator_age_alarm = cloudwatch.Alarm(
            self,
            "KinesisIteratorAgeAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/Kinesis",
                metric_name="GetRecords.IteratorAgeMilliseconds",
                dimensions_map={"StreamName": "experimentation-events"},
                statistic="Maximum",
                period=Duration.minutes(5),
            ),
            evaluation_periods=3,
            threshold=300000,  # 5 minutes
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="Kinesis stream processing is falling behind",
            alarm_name="KinesisProcessingDelay",
        )

        iterator_age_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Lambda duration alarm
        lambda_duration_alarm = cloudwatch.Alarm(
            self,
            "LambdaDurationAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Duration",
                dimensions_map={"FunctionName": "AssignmentLambda"},
                statistic="p95",
                period=Duration.minutes(5),
            ),
            evaluation_periods=3,
            threshold=5000,  # 5 seconds
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="Lambda function execution time is high",
            alarm_name="AssignmentLambdaDuration",
        )

        lambda_duration_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Redis CPU alarm
        redis_cpu_alarm = cloudwatch.Alarm(
            self,
            "RedisCpuAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ElastiCache",
                metric_name="CPUUtilization",
                dimensions_map={"CacheClusterId": "Redis"},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            evaluation_periods=3,
            threshold=80,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="Redis CPU utilization is high",
            alarm_name="RedisHighCPU",
        )

        redis_cpu_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Create a Log Group for application logs
        application_logs = logs.LogGroup(
            self,
            "ApplicationLogs",
            log_group_name="/experimentation/application",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Create a metric filter for error logs
        error_metric = application_logs.add_metric_filter(
            "ErrorMetric",
            filter_pattern=logs.FilterPattern.all_terms("ERROR"),
            metric_name="ErrorCount",
            metric_namespace="ExperimentationPlatform",
            default_value=0,
        )

        # Create an alarm for error logs
        error_logs_alarm = cloudwatch.Alarm(
            self,
            "ErrorLogsAlarm",
            metric=error_metric.metric(statistic="Sum", period=Duration.minutes(5)),
            evaluation_periods=1,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="High number of error logs detected",
            alarm_name="ApplicationErrorLogs",
        )

        error_logs_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # Create a dashboard for application-specific metrics
        app_dashboard = cloudwatch.Dashboard(
            self,
            "ApplicationDashboard",
            dashboard_name="experimentation-application-metrics",
        )

        # Add application-specific widgets (these would be custom metrics published by your application)
        app_widget = cloudwatch.GraphWidget(
            title="Experiment Metrics",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="ActiveExperiments",
                    statistic="Maximum",
                    period=Duration.minutes(5),
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="ExperimentCreationRate",
                    statistic="Sum",
                    period=Duration.hours(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="FeatureFlagEvaluations",
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="ExperimentAssignments",
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
            ],
        )

        event_widget = cloudwatch.GraphWidget(
            title="Event Processing",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="EventsProcessed",
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="EventProcessingLatency",
                    statistic="Average",
                    period=Duration.minutes(1),
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform",
                    metric_name="EventProcessingErrors",
                    statistic="Sum",
                    period=Duration.minutes(5),
                )
            ],
        )

        # Add widgets to application dashboard
        app_dashboard.add_widgets(app_widget, event_widget)

        # ---------------------------------------------------------------
        # EP-013: Prometheus / application-level metrics section
        # These widgets surface metrics emitted by the FastAPI app via
        # backend/app/core/metrics.py and scraped into CloudWatch via the
        # CloudWatch agent or a Prometheus remote-write adapter.
        # ---------------------------------------------------------------

        # Request rate and error rate (HTTP metrics from the FastAPI app)
        prometheus_http_widget = cloudwatch.GraphWidget(
            title="HTTP Request Rate & Error Rate (app)",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_requests_total",
                    dimensions_map={"method": "GET"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                    label="GET requests/min",
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_requests_total",
                    dimensions_map={"method": "POST"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                    label="POST requests/min",
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_requests_total",
                    dimensions_map={"status_code": "500"},
                    statistic="Sum",
                    period=Duration.minutes(1),
                    label="5xx errors/min",
                ),
            ],
        )

        # Latency widget (p50 / p95 / p99)
        prometheus_latency_widget = cloudwatch.GraphWidget(
            title="Request Latency (app p50/p95/p99)",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_request_duration_seconds",
                    statistic="p50",
                    period=Duration.minutes(1),
                    label="p50 latency (s)",
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_request_duration_seconds",
                    statistic="p95",
                    period=Duration.minutes(1),
                    label="p95 latency (s)",
                ),
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="http_request_duration_seconds",
                    statistic="p99",
                    period=Duration.minutes(1),
                    label="p99 latency (s)",
                ),
            ],
        )

        # Active experiments gauge
        active_experiments_widget = cloudwatch.GraphWidget(
            title="Active Experiments",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="active_experiments_gauge",
                    statistic="Maximum",
                    period=Duration.minutes(5),
                    label="Active experiments",
                ),
            ],
        )

        # Cache hit ratio (cache hits / (hits + misses))
        cache_hit_rate_widget = cloudwatch.GraphWidget(
            title="Cache Hit Ratio",
            left=[
                cloudwatch.MathExpression(
                    expression="hits / (hits + misses) * 100",
                    using_metrics={
                        "hits": cloudwatch.Metric(
                            namespace="ExperimentationPlatform/Prometheus",
                            metric_name="cache_hits_total",
                            statistic="Sum",
                            period=Duration.minutes(1),
                        ),
                        "misses": cloudwatch.Metric(
                            namespace="ExperimentationPlatform/Prometheus",
                            metric_name="cache_misses_total",
                            statistic="Sum",
                            period=Duration.minutes(1),
                        ),
                    },
                    label="Cache hit ratio (%)",
                    period=Duration.minutes(1),
                ),
            ],
        )

        # Feature flag evaluations
        flag_eval_widget = cloudwatch.GraphWidget(
            title="Feature Flag Evaluations",
            left=[
                cloudwatch.Metric(
                    namespace="ExperimentationPlatform/Prometheus",
                    metric_name="feature_flag_evaluations_total",
                    statistic="Sum",
                    period=Duration.minutes(1),
                    label="Flag evaluations/min",
                ),
            ],
        )

        # Add EP-013 widgets to the application dashboard
        app_dashboard.add_widgets(
            prometheus_http_widget,
            prometheus_latency_widget,
            active_experiments_widget,
            cache_hit_rate_widget,
            flag_eval_widget,
        )

        # ---------------------------------------------------------------
        # EP-013: Application-level alarms (from CLOUDWATCH_ALARMS spec)
        # ---------------------------------------------------------------

        # High error rate alarm (>1% 5xx)
        high_error_rate_alarm = cloudwatch.Alarm(
            self,
            "HighErrorRateAlarm",
            metric=cloudwatch.Metric(
                namespace="ExperimentationPlatform/Prometheus",
                metric_name="http_requests_total",
                dimensions_map={"status_code": "500"},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            evaluation_periods=2,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="High 5xx error rate detected in the FastAPI application",
            alarm_name="AppHighErrorRate",
        )
        high_error_rate_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # High p99 latency alarm (>2 s)
        high_latency_alarm = cloudwatch.Alarm(
            self,
            "HighLatencyP99Alarm",
            metric=cloudwatch.Metric(
                namespace="ExperimentationPlatform/Prometheus",
                metric_name="http_request_duration_seconds",
                statistic="p99",
                period=Duration.minutes(1),
            ),
            evaluation_periods=3,
            threshold=2.0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="p99 request latency exceeded 2 seconds",
            alarm_name="AppHighLatencyP99",
        )
        high_latency_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )

        # High active experiments alarm (>100)
        high_active_experiments_alarm = cloudwatch.Alarm(
            self,
            "HighActiveExperimentsAlarm",
            metric=cloudwatch.Metric(
                namespace="ExperimentationPlatform/Prometheus",
                metric_name="active_experiments_gauge",
                statistic="Maximum",
                period=Duration.minutes(5),
            ),
            evaluation_periods=1,
            threshold=100,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="More than 100 concurrent active experiments",
            alarm_name="AppHighActiveExperiments",
        )
        high_active_experiments_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.alerts_topic)
        )
