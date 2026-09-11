import React, { useEffect, useState } from 'react';
import {
  DEVICE_PRESETS,
  OS_OPTIONS,
  REGION_OPTIONS,
  TIER_OPTIONS,
  deviceKey,
  findPreset,
  randomDeviceId,
  validateDevice,
  type Device,
  type Os,
  type Region,
  type Tier,
} from '@/lib/devices';

interface Props {
  device: Device;
  onChange: (device: Device) => void;
}

/**
 * Device picker. Presets apply immediately; the custom fields edit a draft that is
 * applied with the form's submit button (so typing does not re-evaluate on every
 * keystroke). Any applied change re-keys the SDK provider — see pages/index.tsx.
 */
export default function DevicePanel({ device, onChange }: Props) {
  const [draft, setDraft] = useState<Device>(device);
  const [errors, setErrors] = useState<Partial<Record<keyof Device, string>>>({});
  const activePreset = findPreset(device);
  const currentKey = deviceKey(device);

  // Follow the applied device (e.g. after a preset click) so the form always shows what is live.
  useEffect(() => {
    setDraft(device);
    setErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKey]);

  const update = <K extends keyof Device>(field: K, value: Device[K]) => setDraft((d) => ({ ...d, [field]: value }));

  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    const next: Device = { ...draft, device_id: draft.device_id.trim(), device_model: draft.device_model.trim() };
    const problems = validateDevice(next);
    setErrors(problems);
    if (Object.keys(problems).length > 0) return;
    onChange(next);
  };

  const dirty = deviceKey(draft) !== currentKey;

  return (
    <section className="card p-4" aria-labelledby="device-panel-title">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id="device-panel-title" className="text-sm font-bold uppercase tracking-wide text-neutral-700">
          Device
        </h2>
        <span className="truncate font-mono text-xs text-neutral-500" data-testid="active-device-id">
          {device.device_id}
        </span>
      </div>

      <fieldset className="mb-4">
        <legend className="label">Presets</legend>
        <div className="grid gap-1">
          {DEVICE_PRESETS.map((p) => {
            const checked = activePreset?.id === p.id;
            return (
              <label
                key={p.id}
                className={`flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-sm ${
                  checked ? 'border-pulse-500 bg-pulse-50' : 'border-neutral-200 hover:bg-neutral-50'
                }`}
              >
                <input
                  type="radio"
                  name="device-preset"
                  value={p.id}
                  checked={checked}
                  onChange={() => onChange(p.device)}
                  className="accent-pulse-600"
                />
                <span>{p.label}</span>
              </label>
            );
          })}
        </div>
        {!activePreset && (
          <p className="mt-1 text-xs text-neutral-500" data-testid="custom-device-note">
            Custom device (no preset matches).
          </p>
        )}
      </fieldset>

      <form onSubmit={apply} noValidate aria-label="Custom device">
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          <div className="col-span-2">
            <label htmlFor="dev-id" className="label">
              Device id (SDK user id)
            </label>
            <div className="flex gap-1">
              <input
                id="dev-id"
                className="input font-mono"
                value={draft.device_id}
                onChange={(e) => update('device_id', e.target.value)}
                aria-invalid={Boolean(errors.device_id)}
                aria-describedby={errors.device_id ? 'dev-id-error' : undefined}
              />
              <button type="button" className="btn-secondary flex-none" onClick={() => update('device_id', randomDeviceId())}>
                Random id
              </button>
            </div>
            {errors.device_id && (
              <p id="dev-id-error" className="mt-1 text-xs text-red-700">
                {errors.device_id}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="dev-os" className="label">
              OS
            </label>
            <select id="dev-os" className="input" value={draft.os} onChange={(e) => update('os', e.target.value as Os)}>
              {OS_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="dev-os-version" className="label">
              OS version
            </label>
            <input
              id="dev-os-version"
              className="input font-mono"
              value={draft.os_version}
              onChange={(e) => update('os_version', e.target.value)}
              aria-invalid={Boolean(errors.os_version)}
              aria-describedby={errors.os_version ? 'dev-os-version-error' : undefined}
            />
            {errors.os_version && (
              <p id="dev-os-version-error" className="mt-1 text-xs text-red-700">
                {errors.os_version}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="dev-app-version" className="label">
              App version
            </label>
            <input
              id="dev-app-version"
              className="input font-mono"
              value={draft.app_version}
              onChange={(e) => update('app_version', e.target.value)}
              aria-invalid={Boolean(errors.app_version)}
              aria-describedby={errors.app_version ? 'dev-app-version-error' : undefined}
            />
            {errors.app_version && (
              <p id="dev-app-version-error" className="mt-1 text-xs text-red-700">
                {errors.app_version}
              </p>
            )}
          </div>
          <div>
            <label htmlFor="dev-model" className="label">
              Device model
            </label>
            <input
              id="dev-model"
              className="input"
              value={draft.device_model}
              onChange={(e) => update('device_model', e.target.value)}
              aria-invalid={Boolean(errors.device_model)}
              aria-describedby={errors.device_model ? 'dev-model-error' : undefined}
            />
            {errors.device_model && (
              <p id="dev-model-error" className="mt-1 text-xs text-red-700">
                {errors.device_model}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="dev-region" className="label">
              Region
            </label>
            <select id="dev-region" className="input" value={draft.region} onChange={(e) => update('region', e.target.value as Region)}>
              {REGION_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="dev-tier" className="label">
              Tier
            </label>
            <select id="dev-tier" className="input" value={draft.tier} onChange={(e) => update('tier', e.target.value as Tier)}>
              {TIER_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <label className="col-span-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft.employee} onChange={(e) => update('employee', e.target.checked)} className="accent-pulse-600" />
            Employee (internal tester)
          </label>
        </div>

        <div className="mt-3 flex items-center justify-between gap-2">
          <p className="text-xs text-neutral-500">
            {dirty ? 'Unapplied changes.' : 'Attributes are sent as targeting context.'}
          </p>
          <button type="submit" className="btn-primary" disabled={!dirty}>
            Apply device
          </button>
        </div>
      </form>
    </section>
  );
}
