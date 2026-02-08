{{/*
Expand the name of the chart.
*/}}
{{- define "asi-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "asi-platform.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asi-platform.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asi-platform.labels" -}}
helm.sh/chart: {{ include "asi-platform.chart" . }}
{{ include "asi-platform.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asi-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asi-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the controller service account
*/}}
{{- define "asi-platform.controller.serviceAccountName" -}}
{{- if .Values.controller.serviceAccount.create }}
{{- default "asi-controller" .Values.controller.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.controller.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the wizard service account
*/}}
{{- define "asi-platform.wizard.serviceAccountName" -}}
{{- if .Values.wizard.serviceAccount.create }}
{{- default "asi-wizard" .Values.wizard.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.wizard.serviceAccount.name }}
{{- end }}
{{- end }}
