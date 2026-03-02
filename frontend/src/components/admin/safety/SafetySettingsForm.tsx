import React, { useEffect, useState } from 'react';
import { AdminService } from '@/services/admin';
import { SafetySettings } from '@/types/admin';

interface SafetySettingsFormProps {
  onSaved?: () => void;
}

export function SafetySettingsForm({ onSaved }: SafetySettingsFormProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [form, setForm] = useState<SafetySettings>({
    error_rate_threshold: 5,
    latency_threshold_ms: 500,
    rollback_policy: 'auto',
    monitoring_window_minutes: 30,
  });

  useEffect(() => {
    setLoading(true);
    AdminService.getSafetySettings()
      .then((data) => {
        setForm(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message || 'Failed to load safety settings');
        setLoading(false);
      });
  }, []);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]:
        name === 'rollback_policy'
          ? value
          : Number(value),
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await AdminService.updateSafetySettings(form);
      setSuccess(true);
      onSaved?.();
    } catch (err) {
      setError((err as Error).message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div data-testid="safety-settings-form-loading" className="flex flex-col gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <form
      data-testid="safety-settings-form"
      onSubmit={handleSubmit}
      className="bg-white border border-slate-200 rounded-lg p-6 flex flex-col gap-5"
    >
      <h2 className="text-base font-semibold text-slate-800">Safety Settings</h2>

      {error && (
        <div
          data-testid="settings-error"
          className="bg-red-50 border border-red-200 rounded p-3 text-red-700 text-sm"
        >
          {error}
        </div>
      )}

      {success && (
        <div
          data-testid="settings-success"
          className="bg-green-50 border border-green-200 rounded p-3 text-green-700 text-sm"
        >
          Settings saved successfully.
        </div>
      )}

      <div className="flex flex-col gap-1">
        <label
          htmlFor="error_rate_threshold"
          className="text-sm font-medium text-slate-700"
        >
          Error Rate Threshold (%)
        </label>
        <input
          id="error_rate_threshold"
          data-testid="error-rate-threshold-input"
          type="number"
          name="error_rate_threshold"
          value={form.error_rate_threshold}
          onChange={handleChange}
          min={0}
          max={100}
          step={0.1}
          className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="latency_threshold_ms"
          className="text-sm font-medium text-slate-700"
        >
          Latency Threshold (ms)
        </label>
        <input
          id="latency_threshold_ms"
          data-testid="latency-threshold-input"
          type="number"
          name="latency_threshold_ms"
          value={form.latency_threshold_ms}
          onChange={handleChange}
          min={0}
          className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="rollback_policy"
          className="text-sm font-medium text-slate-700"
        >
          Rollback Policy
        </label>
        <select
          id="rollback_policy"
          data-testid="rollback-policy-select"
          name="rollback_policy"
          value={form.rollback_policy}
          onChange={handleChange}
          className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        >
          <option value="auto">Auto</option>
          <option value="manual">Manual</option>
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="monitoring_window_minutes"
          className="text-sm font-medium text-slate-700"
        >
          Monitoring Window (minutes)
        </label>
        <input
          id="monitoring_window_minutes"
          data-testid="monitoring-window-input"
          type="number"
          name="monitoring_window_minutes"
          value={form.monitoring_window_minutes}
          onChange={handleChange}
          min={1}
          className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      <div className="flex justify-end">
        <button
          data-testid="save-settings-button"
          type="submit"
          disabled={saving}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>
    </form>
  );
}
