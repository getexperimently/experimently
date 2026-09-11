export type Category = 'Outdoor' | 'Footwear' | 'Apparel' | 'Accessories';

export const CATEGORIES: Category[] = ['Outdoor', 'Footwear', 'Apparel', 'Accessories'];

export interface Product {
  id: string;
  slug: string;
  name: string;
  category: Category;
  /** Unit price in USD. */
  price: number;
  /** Average rating, 1–5. */
  rating: number;
  description: string;
  /** Gradient pair (from, to) for the CSS-only placeholder artwork. */
  color: [string, string];
}

export const PRODUCTS: Product[] = [
  {
    id: 'p001',
    slug: 'trailhead-backpack-45l',
    name: 'Trailhead Backpack 45L',
    category: 'Outdoor',
    price: 129,
    rating: 4.7,
    description:
      'A weekend-ready pack with a ventilated back panel, rain cover and enough pockets for every snack.',
    color: ['#0f766e', '#99f6e4'],
  },
  {
    id: 'p002',
    slug: 'summit-tent-2p',
    name: 'Summit Tent 2P',
    category: 'Outdoor',
    price: 249,
    rating: 4.6,
    description: 'Two-person, three-season tent that pitches in four minutes and packs down to a loaf of bread.',
    color: ['#065f46', '#a7f3d0'],
  },
  {
    id: 'p003',
    slug: 'ember-camp-stove',
    name: 'Ember Camp Stove',
    category: 'Outdoor',
    price: 59,
    rating: 4.3,
    description: 'Compact canister stove with a piezo igniter. Boils a litre of water in under three minutes.',
    color: ['#b45309', '#fde68a'],
  },
  {
    id: 'p004',
    slug: 'ridge-runner-trail-shoes',
    name: 'Ridge Runner Trail Shoes',
    category: 'Footwear',
    price: 139,
    rating: 4.8,
    description: 'Grippy, cushioned trail runners with a rock plate for technical descents.',
    color: ['#1d4ed8', '#bfdbfe'],
  },
  {
    id: 'p005',
    slug: 'harbor-canvas-sneakers',
    name: 'Harbor Canvas Sneakers',
    category: 'Footwear',
    price: 69,
    rating: 4.2,
    description: 'Everyday canvas sneakers with a recycled rubber sole. Goes with everything.',
    color: ['#334155', '#cbd5e1'],
  },
  {
    id: 'p006',
    slug: 'alpine-insulated-boots',
    name: 'Alpine Insulated Boots',
    category: 'Footwear',
    price: 189,
    rating: 4.5,
    description: 'Waterproof winter boots rated to -25°C with a Vibram outsole for icy pavements.',
    color: ['#1e3a8a', '#93c5fd'],
  },
  {
    id: 'p007',
    slug: 'merino-base-layer',
    name: 'Merino Base Layer',
    category: 'Apparel',
    price: 79,
    rating: 4.6,
    description: 'Lightweight merino crew that regulates temperature and stays fresh for days on the trail.',
    color: ['#7c2d12', '#fdba74'],
  },
  {
    id: 'p008',
    slug: 'stormshell-rain-jacket',
    name: 'Stormshell Rain Jacket',
    category: 'Apparel',
    price: 159,
    rating: 4.7,
    description: 'Fully seam-sealed 2.5-layer shell with pit zips and a helmet-compatible hood.',
    color: ['#4c1d95', '#c4b5fd'],
  },
  {
    id: 'p009',
    slug: 'everyday-chino-pants',
    name: 'Everyday Chino Pants',
    category: 'Apparel',
    price: 64,
    rating: 4.1,
    description: 'Stretch chinos cut for the office and the bike lane alike. Four colours, one fit.',
    color: ['#78350f', '#fcd34d'],
  },
  {
    id: 'p010',
    slug: 'solstice-sunglasses',
    name: 'Solstice Sunglasses',
    category: 'Accessories',
    price: 89,
    rating: 4.4,
    description: 'Polarised lenses in a bio-based frame. Includes a hard case and a microfibre cloth.',
    color: ['#be123c', '#fecdd3'],
  },
  {
    id: 'p011',
    slug: 'field-watch',
    name: 'Field Watch',
    category: 'Accessories',
    price: 199,
    rating: 4.9,
    description: 'Automatic field watch with a sapphire crystal, 100 m water resistance and a nylon strap.',
    color: ['#111827', '#9ca3af'],
  },
  {
    id: 'p012',
    slug: 'wool-beanie',
    name: 'Wool Beanie',
    category: 'Accessories',
    price: 29,
    rating: 4.3,
    description: 'Chunky ribbed beanie knitted from responsibly sourced wool. Warm, not itchy.',
    color: ['#9f1239', '#fda4af'],
  },
];

export function findProduct(idOrSlug: string | undefined): Product | undefined {
  if (!idOrSlug) return undefined;
  return PRODUCTS.find((p) => p.id === idOrSlug || p.slug === idOrSlug);
}

export function formatPrice(amount: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}
