/**
 * Simulated devices. A device's attributes are sent verbatim as the SDK user's
 * `attributes`, which the platform receives as targeting `context` on flag
 * evaluation and experiment assignment. The attribute names below are the ones
 * the seeded targeting rules reference (`os`, `os_version`, `region`, `tier`,
 * `employee`, `app_version`).
 */

export type Os = 'iOS' | 'Android';
export type Region = 'US' | 'GB' | 'DE' | 'IN' | 'BR';
export type Tier = 'free' | 'premium';

export interface Device {
  /** Stable id; doubles as the SDK user id so assignments stay sticky per device. */
  device_id: string;
  os: Os;
  /** Semver string, e.g. "17.4.0". */
  os_version: string;
  /** Semver string, e.g. "3.2.1". */
  app_version: string;
  region: Region;
  tier: Tier;
  employee: boolean;
  device_model: string;
}

export interface DevicePreset {
  id: string;
  label: string;
  device: Device;
}

export const OS_OPTIONS: Os[] = ['iOS', 'Android'];
export const REGION_OPTIONS: Region[] = ['US', 'GB', 'DE', 'IN', 'BR'];
export const TIER_OPTIONS: Tier[] = ['free', 'premium'];

/*
 * Preset ids are deliberately outside the 2 % global holdout (the holdout bucket
 * is a fixed-salt hash of the user id, so this is stable across re-seeds). To
 * show the holdout, type a custom id such as `sp-holdout-15` in the Device panel.
 */
export const DEVICE_PRESETS: DevicePreset[] = [
  {
    id: 'iphone15-us-premium',
    label: 'iPhone 15 · iOS 17.4 · US · premium',
    device: {
      device_id: 'sp-iphone-15-us-premium',
      os: 'iOS',
      os_version: '17.4.0',
      app_version: '3.2.1',
      region: 'US',
      tier: 'premium',
      employee: false,
      device_model: 'iPhone 15',
    },
  },
  {
    id: 'pixel7-de-free',
    label: 'Pixel 7 · Android 14 · DE · free',
    device: {
      device_id: 'sp-pixel-7-de-free',
      os: 'Android',
      os_version: '14.0.0',
      app_version: '3.2.0',
      region: 'DE',
      tier: 'free',
      employee: false,
      device_model: 'Pixel 7',
    },
  },
  {
    id: 'galaxys10-us-premium',
    label: 'Galaxy S10 · Android 12 · US · premium · app 3.1.0',
    device: {
      device_id: 'sp-galaxy-s10-us-premium',
      os: 'Android',
      os_version: '12.0.0',
      app_version: '3.1.0',
      region: 'US',
      tier: 'premium',
      employee: false,
      device_model: 'Galaxy S10',
    },
  },
  {
    id: 'iphone14-gb-free',
    label: 'iPhone 14 · iOS 16.7 · GB · free',
    device: {
      device_id: 'sp-iphone-14-gb-free',
      os: 'iOS',
      os_version: '16.7.0',
      app_version: '3.2.0',
      region: 'GB',
      tier: 'free',
      employee: false,
      device_model: 'iPhone 14',
    },
  },
  {
    id: 'internal-tester',
    label: 'Internal tester · iPhone 15 · employee',
    device: {
      device_id: 'sp-internal-tester',
      os: 'iOS',
      os_version: '17.4.0',
      app_version: '3.2.1',
      region: 'US',
      tier: 'premium',
      employee: true,
      device_model: 'iPhone 15',
    },
  },
];

export const DEFAULT_PRESET = DEVICE_PRESETS[0];

/**
 * Identity of a device configuration. Used as the React `key` of the SDK
 * provider: any change (id or attribute) re-mounts the provider, which drops
 * the SDK caches and re-evaluates every flag and experiment.
 */
export function deviceKey(device: Device): string {
  return JSON.stringify([
    device.device_id,
    device.os,
    device.os_version,
    device.app_version,
    device.region,
    device.tier,
    device.employee,
    device.device_model,
  ]);
}

/** The preset whose device is exactly `device`, if any (custom edits give `undefined`). */
export function findPreset(device: Device): DevicePreset | undefined {
  const key = deviceKey(device);
  return DEVICE_PRESETS.find((p) => deviceKey(p.device) === key);
}

/** SDK user context for a device: the id is the user id, every attribute is targeting context. */
export function toUserContext(device: Device): { userId: string; attributes: Record<string, unknown> } {
  return {
    userId: device.device_id,
    attributes: {
      os: device.os,
      os_version: device.os_version,
      app_version: device.app_version,
      region: device.region,
      tier: device.tier,
      employee: device.employee,
      device_model: device.device_model,
      device_id: device.device_id,
    },
  };
}

const SEMVER = /^\d+\.\d+\.\d+$/;

/** Validate the free-text fields of a custom device. Returns field → message. */
export function validateDevice(device: Device): Partial<Record<keyof Device, string>> {
  const errors: Partial<Record<keyof Device, string>> = {};
  if (!device.device_id.trim()) errors.device_id = 'Device id is required.';
  if (!SEMVER.test(device.os_version)) errors.os_version = 'Use a semver like 17.4.0.';
  if (!SEMVER.test(device.app_version)) errors.app_version = 'Use a semver like 3.2.1.';
  if (!device.device_model.trim()) errors.device_model = 'Device model is required.';
  return errors;
}

/** A fresh random device id (`sp-custom-xxxxxxxx`). */
export function randomDeviceId(random: () => number = Math.random): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let suffix = '';
  for (let i = 0; i < 8; i += 1) suffix += alphabet[Math.floor(random() * alphabet.length)];
  return `sp-custom-${suffix}`;
}
