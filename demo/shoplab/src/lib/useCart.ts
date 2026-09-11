import { useCallback, useEffect, useState } from 'react';
import { addToCart, cartCount, cartTotal, clearCart, readCart, subscribeCart, type CartItem } from '@/lib/cart';

export interface CartState {
  items: CartItem[];
  count: number;
  total: number;
  add: (productId: string, price: number, quantity?: number) => CartItem[];
  clear: () => void;
}

/** React view over the localStorage cart; re-renders when any tab changes it. */
export function useCart(): CartState {
  const [items, setItems] = useState<CartItem[]>([]);

  useEffect(() => {
    setItems(readCart());
    return subscribeCart(() => setItems(readCart()));
  }, []);

  const add = useCallback((productId: string, price: number, quantity = 1) => {
    const next = addToCart(productId, price, quantity);
    setItems(next);
    return next;
  }, []);

  const clear = useCallback(() => {
    clearCart();
    setItems([]);
  }, []);

  return { items, count: cartCount(items), total: cartTotal(items), add, clear };
}
