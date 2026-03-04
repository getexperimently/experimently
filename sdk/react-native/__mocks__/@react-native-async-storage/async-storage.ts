/**
 * Jest mock for @react-native-async-storage/async-storage.
 * Provides an in-memory implementation suitable for unit tests.
 */
const store: Record<string, string> = {};

const AsyncStorage = {
  getItem: jest.fn(async (key: string) => store[key] ?? null),
  setItem: jest.fn(async (key: string, value: string) => {
    store[key] = value;
  }),
  removeItem: jest.fn(async (key: string) => {
    delete store[key];
  }),
  multiRemove: jest.fn(async (keys: string[]) => {
    keys.forEach((k) => delete store[k]);
  }),
  getAllKeys: jest.fn(async () => Object.keys(store)),
  clear: jest.fn(async () => {
    Object.keys(store).forEach((k) => delete store[k]);
  }),
};

export default AsyncStorage;
