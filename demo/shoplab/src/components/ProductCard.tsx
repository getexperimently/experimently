import React from 'react';
import Link from 'next/link';
import { formatPrice, type Product } from '@/data/products';
import ProductArt from '@/components/ProductArt';

interface Props {
  product: Product;
  position: number;
  onClick?: (product: Product, position: number) => void;
  /** Optional custom title node (e.g. highlighted search terms). */
  title?: React.ReactNode;
  children?: React.ReactNode;
}

export default function ProductCard({ product, position, onClick, title, children }: Props) {
  return (
    <li className="card flex flex-col overflow-hidden" data-testid="product-card" data-product-id={product.id}>
      <Link
        href={`/products/${product.id}`}
        onClick={() => onClick?.(product, position)}
        className="group flex h-full flex-col p-4 hover:bg-neutral-50"
        aria-label={`${product.name}, ${formatPrice(product.price)}`}
      >
        <ProductArt product={product} className="mb-3 aspect-[4/3] w-full" />
        <span className="text-xs uppercase tracking-wide text-neutral-500">{product.category}</span>
        <span className="mt-1 font-semibold text-neutral-900 group-hover:text-accent-700">{title ?? product.name}</span>
        <span className="mt-1 text-sm text-neutral-600" aria-label={`Rated ${product.rating} out of 5`}>
          ★ {product.rating.toFixed(1)}
        </span>
        <span className="mt-auto pt-3 text-lg font-bold">{formatPrice(product.price)}</span>
        {children}
      </Link>
    </li>
  );
}
