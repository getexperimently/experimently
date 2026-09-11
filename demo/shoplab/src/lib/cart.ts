/**
 * localStorage-backed shopping cart. The total/count helpers and the add/remove
 * operations are pure so they can be unit-tested without a DOM.
 */

export const CART_KEY = 'shoplab.cart';
export const CART_CHANGED_EVENT = 'shoplab:cart-changed';

export interface CartItem {
  productId: string;
  /** Unit price captured at add time. */
  price: number;
  quantity: number;
}

function hasStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function isCartItem(value: unknown): value is CartItem {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return typeof v.productId === 'string' && typeof v.price === 'number' && typeof v.quantity === 'number';
}

export function readCart(): CartItem[] {
  if (!hasStorage()) return [];
  try {
    const raw = window.localStorage.getItem(CART_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isCartItem) : [];
  } catch {
    return [];
  }
}

export function writeCart(items: CartItem[]): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.setItem(CART_KEY, JSON.stringify(items));
    window.dispatchEvent(new CustomEvent(CART_CHANGED_EVENT));
  } catch {
    // ignore quota / private-mode errors
  }
}

export function clearCart(): void {
  writeCart([]);
}

/** Pure: returns a new list with `quantity` more of `productId`. */
export function addItem(items: CartItem[], productId: string, price: number, quantity = 1): CartItem[] {
  const qty = Math.max(1, Math.floor(quantity));
  const existing = items.find((i) => i.productId === productId);
  if (existing) {
    return items.map((i) => (i.productId === productId ? { ...i, price, quantity: i.quantity + qty } : i));
  }
  return [...items, { productId, price, quantity: qty }];
}

/** Pure: returns a new list without `productId`. */
export function removeItem(items: CartItem[], productId: string): CartItem[] {
  return items.filter((i) => i.productId !== productId);
}

/** Pure: sum of price × quantity, rounded to cents. */
export function cartTotal(items: CartItem[]): number {
  const cents = items.reduce((sum, i) => sum + Math.round(i.price * 100) * i.quantity, 0);
  return cents / 100;
}

/** Pure: total number of units in the cart. */
export function cartCount(items: CartItem[]): number {
  return items.reduce((sum, i) => sum + i.quantity, 0);
}

/** Convenience: read, add, write. Returns the new cart. */
export function addToCart(productId: string, price: number, quantity = 1): CartItem[] {
  const next = addItem(readCart(), productId, price, quantity);
  writeCart(next);
  return next;
}

/** Subscribe to cart changes (same tab via custom event, other tabs via `storage`). */
export function subscribeCart(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === CART_KEY) listener();
  };
  window.addEventListener(CART_CHANGED_EVENT, listener);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(CART_CHANGED_EVENT, listener);
    window.removeEventListener('storage', onStorage);
  };
}
