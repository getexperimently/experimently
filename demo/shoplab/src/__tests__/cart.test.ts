import {
  addItem,
  cartCount,
  cartTotal,
  CART_KEY,
  clearCart,
  readCart,
  removeItem,
  subscribeCart,
  writeCart,
  type CartItem,
} from '@/lib/cart';

describe('cart helpers (pure)', () => {
  const items: CartItem[] = [
    { productId: 'p001', price: 129, quantity: 1 },
    { productId: 'p012', price: 29, quantity: 3 },
  ];

  it('addItem appends a new line or increments an existing one without mutating input', () => {
    const withNew = addItem(items, 'p004', 139, 2);
    expect(withNew).toHaveLength(3);
    expect(withNew[2]).toEqual({ productId: 'p004', price: 139, quantity: 2 });

    const incremented = addItem(items, 'p012', 29);
    expect(incremented).toHaveLength(2);
    expect(incremented.find((i) => i.productId === 'p012')?.quantity).toBe(4);
    expect(items[1].quantity).toBe(3); // untouched
  });

  it('removeItem drops the line', () => {
    expect(removeItem(items, 'p001').map((i) => i.productId)).toEqual(['p012']);
  });

  it('cartTotal and cartCount sum price × quantity and units, rounding to cents', () => {
    expect(cartTotal(items)).toBe(129 + 29 * 3);
    expect(cartCount(items)).toBe(4);
    expect(cartTotal([{ productId: 'x', price: 0.1, quantity: 3 }])).toBe(0.3);
    expect(cartTotal([])).toBe(0);
    expect(cartCount([])).toBe(0);
  });
});

describe('cart storage', () => {
  beforeEach(() => window.localStorage.clear());

  it('round-trips through localStorage and ignores malformed entries', () => {
    writeCart([{ productId: 'p001', price: 129, quantity: 2 }]);
    expect(readCart()).toEqual([{ productId: 'p001', price: 129, quantity: 2 }]);

    window.localStorage.setItem(CART_KEY, JSON.stringify([{ productId: 'ok', price: 1, quantity: 1 }, { bogus: true }, 42]));
    expect(readCart()).toEqual([{ productId: 'ok', price: 1, quantity: 1 }]);

    window.localStorage.setItem(CART_KEY, '{not json');
    expect(readCart()).toEqual([]);
  });

  it('notifies subscribers when the cart changes and clears cleanly', () => {
    const listener = jest.fn();
    const unsubscribe = subscribeCart(listener);
    writeCart([{ productId: 'p001', price: 129, quantity: 1 }]);
    expect(listener).toHaveBeenCalledTimes(1);
    clearCart();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(readCart()).toEqual([]);
    unsubscribe();
    writeCart([{ productId: 'p002', price: 249, quantity: 1 }]);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
