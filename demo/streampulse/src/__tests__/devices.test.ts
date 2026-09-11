import {
  DEFAULT_PRESET,
  DEVICE_PRESETS,
  deviceKey,
  findPreset,
  randomDeviceId,
  toUserContext,
  validateDevice,
} from '@/lib/devices';

describe('device presets', () => {
  it('ships the five presets from the spec with unique ids', () => {
    expect(DEVICE_PRESETS.map((p) => p.label)).toEqual([
      'iPhone 15 · iOS 17.4 · US · premium',
      'Pixel 7 · Android 14 · DE · free',
      'Galaxy S10 · Android 12 · US · premium · app 3.1.0',
      'iPhone 14 · iOS 16.7 · GB · free',
      'Internal tester · iPhone 15 · employee',
    ]);
    expect(new Set(DEVICE_PRESETS.map((p) => p.device.device_id)).size).toBe(5);
    expect(DEVICE_PRESETS[4].device.employee).toBe(true);
    expect(DEVICE_PRESETS[2].device).toMatchObject({ os: 'Android', os_version: '12.0.0', app_version: '3.1.0' });
  });

  it('maps a device to the SDK user: id = device_id, every attribute as targeting context', () => {
    expect(toUserContext(DEFAULT_PRESET.device)).toEqual({
      userId: 'sp-iphone-15-us-premium',
      attributes: {
        os: 'iOS',
        os_version: '17.4.0',
        app_version: '3.2.1',
        region: 'US',
        tier: 'premium',
        employee: false,
        device_model: 'iPhone 15',
        device_id: 'sp-iphone-15-us-premium',
      },
    });
  });

  it('deviceKey changes whenever any attribute changes, and findPreset only matches exact presets', () => {
    const base = DEFAULT_PRESET.device;
    expect(deviceKey(base)).toBe(deviceKey({ ...base }));
    expect(deviceKey(base)).not.toBe(deviceKey({ ...base, region: 'GB' }));
    expect(deviceKey(base)).not.toBe(deviceKey({ ...base, employee: true }));
    expect(findPreset(base)?.id).toBe(DEFAULT_PRESET.id);
    expect(findPreset({ ...base, os_version: '17.5.0' })).toBeUndefined();
  });

  it('validates semver fields and required text', () => {
    expect(validateDevice(DEFAULT_PRESET.device)).toEqual({});
    const bad = validateDevice({ ...DEFAULT_PRESET.device, device_id: ' ', os_version: '17', app_version: 'latest', device_model: '' });
    expect(Object.keys(bad).sort()).toEqual(['app_version', 'device_id', 'device_model', 'os_version']);
  });

  it('randomDeviceId is deterministic for a given RNG and uses the sp-custom- prefix', () => {
    let i = 0;
    const rng = () => ((i += 7) % 36) / 36;
    const a = randomDeviceId(rng);
    i = 0;
    const b = randomDeviceId(rng);
    expect(a).toBe(b);
    expect(a).toMatch(/^sp-custom-[a-z0-9]{8}$/);
  });
});
