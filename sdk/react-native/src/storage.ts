/**
 * AsyncStorage wrapper for offline persistence of flag evaluations.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

const FLAG_PREFIX = 'ep_sdk_flag:';
const ASSIGNMENT_PREFIX = 'ep_sdk_asgn:';

/**
 * Persists and retrieves flag/assignment values using AsyncStorage.
 *
 * Keys are namespaced with `ep_sdk_flag:` or `ep_sdk_asgn:` to avoid
 * collisions with other AsyncStorage users in the host app.
 */
export class OfflineStorage {
  /** Persists a flag enabled/disabled state. */
  async setFlag(cacheKey: string, value: boolean): Promise<void> {
    try {
      await AsyncStorage.setItem(FLAG_PREFIX + cacheKey, JSON.stringify(value));
    } catch {
      // Best-effort — never throw
    }
  }

  /** Retrieves a persisted flag state, or `null` if not stored. */
  async getFlag(cacheKey: string): Promise<boolean | null> {
    try {
      const raw = await AsyncStorage.getItem(FLAG_PREFIX + cacheKey);
      if (raw === null) return null;
      return JSON.parse(raw) as boolean;
    } catch {
      return null;
    }
  }

  /** Persists an experiment variant key (or `null` for "not assigned"). */
  async setAssignment(cacheKey: string, variantKey: string | null): Promise<void> {
    try {
      const value = variantKey === null ? 'null' : variantKey;
      await AsyncStorage.setItem(ASSIGNMENT_PREFIX + cacheKey, value);
    } catch {
      // Best-effort — never throw
    }
  }

  /** Retrieves a persisted assignment variant key, or `null` if not stored. */
  async getAssignment(cacheKey: string): Promise<string | null | undefined> {
    try {
      const raw = await AsyncStorage.getItem(ASSIGNMENT_PREFIX + cacheKey);
      if (raw === null) return undefined; // undefined = "never stored"
      if (raw === 'null') return null;    // null = "stored as not-assigned"
      return raw;
    } catch {
      return undefined;
    }
  }

  /** Removes all SDK-namespaced entries from AsyncStorage. */
  async clear(): Promise<void> {
    try {
      const allKeys = await AsyncStorage.getAllKeys();
      const sdkKeys = allKeys.filter(
        (k) => k.startsWith(FLAG_PREFIX) || k.startsWith(ASSIGNMENT_PREFIX)
      );
      if (sdkKeys.length > 0) {
        await AsyncStorage.multiRemove(sdkKeys);
      }
    } catch {
      // Best-effort
    }
  }
}
