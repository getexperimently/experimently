import React from 'react';
import type { Product } from '@/data/products';

interface Props {
  product: Product;
  className?: string;
}

/** CSS-only placeholder artwork: a gradient tile with the product's initials. No image assets. */
export default function ProductArt({ product, className = '' }: Props) {
  const initials = product.name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
  return (
    <div
      role="img"
      aria-label={`${product.name} artwork`}
      className={`flex items-center justify-center rounded-md text-white/90 ${className}`}
      style={{ background: `linear-gradient(135deg, ${product.color[0]}, ${product.color[1]})` }}
    >
      <span className="select-none text-3xl font-bold tracking-wider drop-shadow-sm">{initials}</span>
    </div>
  );
}
