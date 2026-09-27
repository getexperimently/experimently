{{/*
Names, labels, image references, and the refusals the schema cannot express.
*/}}

{{- define "experimently.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "experimently.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "experimently.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "experimently.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Selector labels for one component: pass (dict "ctx" $ "component" "api"). */}}
{{- define "experimently.selectorLabels" -}}
app.kubernetes.io/name: {{ include "experimently.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "experimently.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "experimently.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "experimently.secretName" -}}
{{- default (printf "%s-secrets" (include "experimently.fullname" .)) .Values.existingSecret }}
{{- end }}

{{/* The image tag: `<profile>-<appVersion>` unless a versioned tag is given. */}}
{{- define "experimently.imageTag" -}}
{{- $tag := default (printf "%s-%s" .Values.profile .Chart.AppVersion) .Values.image.tag }}
{{- if not (hasPrefix (printf "%s-" .Values.profile) $tag) }}
{{- fail (printf "image.tag %q does not match profile %q: a mismatched image serves the wrong profile without an error" $tag .Values.profile) }}
{{- end }}
{{- $tag }}
{{- end }}

{{/* pass (dict "ctx" $ "image" .Values.image.api) */}}
{{- define "experimently.image" -}}
{{- if .image.digest }}
{{- printf "%s@%s" .image.repository .image.digest }}
{{- else }}
{{- printf "%s:%s" .image.repository (include "experimently.imageTag" .ctx) }}
{{- end }}
{{- end }}

{{/* The host people reach: publicBaseUrl without scheme (and without port). */}}
{{- define "experimently.publicHost" -}}
{{- $u := urlParse (required "publicBaseUrl is required, e.g. https://experimently.example.com" .Values.publicBaseUrl) }}
{{- (split ":" $u.host)._0 }}
{{- end }}

{{- define "experimently.postgresHost" -}}
{{- if .Values.postgresql.bundled }}
{{- printf "%s-postgres" (include "experimently.fullname" .) }}
{{- else }}
{{- required "postgresql.host is required when postgresql.bundled=false" .Values.postgresql.host }}
{{- end }}
{{- end }}

{{- define "experimently.redisHost" -}}
{{- if .Values.redis.bundled }}
{{- printf "%s-redis" (include "experimently.fullname" .) }}
{{- else }}
{{- required "redis.host is required when redis.enabled=true and redis.bundled=false" .Values.redis.host }}
{{- end }}
{{- end }}

{{/*
The env entries every API process gets beyond the ConfigMap: secrets, only
ever by reference. Required keys are not `optional`, so a missing key in an
existingSecret stops the pod with CreateContainerConfigError naming it.
*/}}
{{- define "experimently.secretEnv" -}}
{{- $secret := include "experimently.secretName" . }}
{{- $keys := list "SECRET_KEY" "FIRST_SUPERUSER_PASSWORD" "POSTGRES_USER" "POSTGRES_PASSWORD" }}
{{- if eq .Values.profile "full" }}
{{- $keys = append $keys "AUDIT_HMAC_KEY" }}
{{- end }}
{{- range $keys }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ . }}
{{- end }}
{{- $optional := list "METRICS_TOKEN" }}
{{- if .Values.redis.enabled }}
{{- $optional = append $optional "REDIS_PASSWORD" }}
{{- end }}
{{- range $optional }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ . }}
      optional: true
{{- end }}
{{- end }}

{{/* extraEnv may not reintroduce what the chart pins. */}}
{{- define "experimently.extraEnv" -}}
{{- range .Values.api.extraEnv }}
{{- if has .name (list "RUN_MIGRATIONS" "SEED" "SEED_FORCE") }}
{{- fail (printf "api.extraEnv may not set %s: migrations run once in the migrate init container, and demo seeds are not available through this chart" .name) }}
{{- end }}
{{- end }}
{{- with .Values.api.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "experimently.podSecurity" -}}
runAsNonRoot: true
runAsUser: {{ .uid }}
runAsGroup: {{ .gid }}
fsGroup: {{ .gid }}
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "experimently.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}
