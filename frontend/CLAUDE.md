# Frontend Development Guide

Frontend-specific guidance for the experimentation platform Next.js application.

## Quick Start

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
# Opens at http://localhost:3000

# Run tests
npm test

# Build for production
npm run build

# Run production build locally
npm start
```

## Directory Structure

```
frontend/
├── src/
│   ├── app/              # Next.js App Router
│   │   ├── layout.tsx    # Root layout
│   │   ├── page.tsx      # Home page
│   │   └── [routes]/     # Dynamic routes
│   ├── components/       # React components
│   │   ├── experiments/  # Experiment-related components
│   │   ├── feature-flags/# Feature flag components
│   │   ├── analytics/    # Analytics & metrics components
│   │   ├── ui/           # Shared UI components
│   │   └── common/       # Common components
│   ├── services/         # API service layer
│   │   ├── api.ts        # Base API client
│   │   ├── experiments.ts
│   │   ├── featureFlags.ts
│   │   └── analytics.ts
│   ├── hooks/            # Custom React hooks
│   ├── lib/              # Utilities and helpers
│   ├── types/            # TypeScript type definitions
│   └── styles/           # Global styles
├── public/               # Static assets
└── package.json
```

## TypeScript Patterns

### Type Definitions

```typescript
// Use interfaces for object shapes
interface Experiment {
  id: string;
  name: string;
  status: ExperimentStatus;
  startDate: Date;
  endDate?: Date;
  variants: Variant[];
}

// Use types for unions and primitives
type ExperimentStatus = 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'COMPLETED';
type UserRole = 'ADMIN' | 'DEVELOPER' | 'ANALYST' | 'VIEWER';

// Component props
interface ExperimentCardProps {
  experiment: Experiment;
  onEdit?: (id: string) => void;
  onDelete?: (id: string) => void;
}
```

### Component Patterns

```typescript
// Client components (interactive)
'use client';

import { useState } from 'react';
import { Experiment } from '@/types';

export default function ExperimentCard({
  experiment,
  onEdit,
  onDelete
}: ExperimentCardProps) {
  const [isLoading, setIsLoading] = useState(false);

  const handleEdit = async () => {
    setIsLoading(true);
    try {
      await onEdit?.(experiment.id);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="card">
      <h3>{experiment.name}</h3>
      <button onClick={handleEdit} disabled={isLoading}>
        Edit
      </button>
    </div>
  );
}

// Server components (default in App Router)
import { ExperimentService } from '@/services/experiments';

export default async function ExperimentsPage() {
  const experiments = await ExperimentService.list();

  return (
    <div>
      <h1>Experiments</h1>
      {experiments.map(exp => (
        <ExperimentCard key={exp.id} experiment={exp} />
      ))}
    </div>
  );
}
```

## API Service Layer

### Base API Client

```typescript
// src/services/api.ts — the only place that calls `fetch`
import { apiFetch, ApiError, apiBase } from '@/services/api';

// apiBase(): NEXT_PUBLIC_API_URL without a trailing slash, "" = same origin (nginx proxies /api/)
// apiFetch<T>(path, { method, json, query, auth, redirectOn401 }):
//   - adds `Authorization: Bearer <localStorage["experimently.token"]>`
//   - serialises `json`, appends `query` (undefined/null omitted), parses the JSON body
//   - throws ApiError { status, detail, code?, message } for non-2xx (status 0 = unreachable)
//   - on 401 clears the token and navigates to /login?next=<current path> (skipped on /login
//     and for `auth: false` requests such as the login call itself)
const flags = await apiFetch<FeatureFlagListResponse>('/api/v1/feature-flags', {
  query: { status: 'active', page: 1 },
});
```

Never call `fetch` directly from services, pages, components or hooks; tests mock `global.fetch`
and `apiFetch` calls it at request time.

### Resource-Specific Services

```typescript
// src/services/experiments.ts
import { apiFetch } from '@/services/api';
import { Experiment, CreateExperimentRequest } from '@/types/experiments';

export const ExperimentsService = {
  list: () => apiFetch<ExperimentListResponse>('/api/v1/experiments'),
  get: (id: string) => apiFetch<Experiment>(`/api/v1/experiments/${id}`),
  create: (data: CreateExperimentRequest) =>
    apiFetch<Experiment>('/api/v1/experiments', { method: 'POST', json: data }),
  update: (id: string, data: Partial<Experiment>) =>
    apiFetch<Experiment>(`/api/v1/experiments/${id}`, { method: 'PUT', json: data }),
  delete: (id: string) => apiFetch<void>(`/api/v1/experiments/${id}`, { method: 'DELETE' }),
};
```

## Custom Hooks

### Data Fetching Hook

```typescript
// src/hooks/useExperiments.ts
'use client';

import { useState, useEffect } from 'react';
import { ExperimentService } from '@/services/experiments';
import { Experiment } from '@/types';

export function useExperiments() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const fetchExperiments = async () => {
      try {
        setIsLoading(true);
        const data = await ExperimentService.list();
        setExperiments(data);
      } catch (err) {
        setError(err as Error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchExperiments();
  }, []);

  const refresh = async () => {
    const data = await ExperimentService.list();
    setExperiments(data);
  };

  return { experiments, isLoading, error, refresh };
}
```

### Form Hook

```typescript
// src/hooks/useForm.ts
import { useState, ChangeEvent, FormEvent } from 'react';

export function useForm<T>(initialValues: T, onSubmit: (values: T) => Promise<void>) {
  const [values, setValues] = useState<T>(initialValues);
  const [errors, setErrors] = useState<Partial<Record<keyof T, string>>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setValues(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onSubmit(values);
    } catch (error) {
      console.error('Form submission error:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    values,
    errors,
    isSubmitting,
    handleChange,
    handleSubmit,
    setValues,
    setErrors,
  };
}
```

## State Management

### React Context Pattern

```typescript
// src/contexts/AuthContext.tsx (real implementation — do not re-create it)
import { useAuth } from '@/contexts/AuthContext';

const { user, status, login, logout, hasRole } = useAuth();
// user:   UserMe | null   ({ id, email, username, full_name, role, is_superuser, is_active, auth_provider })
// status: 'loading' | 'authenticated' | 'anonymous'
//   - on mount: if localStorage["experimently.token"] exists → GET /api/v1/auth/me (401 → anonymous)
//   - login(email, password) → POST /api/v1/auth/login, stores ONLY the token
//   - logout() → POST /api/v1/auth/logout (best effort), clears the token
// Never persist the user object (the old `admin_user` localStorage entry is gone).
```

Protect pages with `<RequireAuth roles?>` (already applied by `_app.tsx` to every route except
`/`, `/login`, `/docs/**`, `/power-calculator`) and admin pages with
`withAdminGuard(Page, { requiredRole?: 'ADMIN' })`. The shell (`components/AppShell.tsx`)
provides the top nav and the visible "Log out" button; every page sets its title via
`<PageTitle title="…" />`.

## Styling Guidelines

### Tailwind CSS (Recommended)

```typescript
// Use Tailwind utility classes
export default function Button({ children, variant = 'primary' }) {
  const baseClasses = 'px-4 py-2 rounded font-medium transition-colors';
  const variantClasses = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-gray-200 text-gray-800 hover:bg-gray-300',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  };

  return (
    <button className={`${baseClasses} ${variantClasses[variant]}`}>
      {children}
    </button>
  );
}
```

### CSS Modules (Alternative)

```typescript
// Button.module.css
.button {
  padding: 0.5rem 1rem;
  border-radius: 0.25rem;
  font-weight: 500;
  transition: background-color 0.2s;
}

.primary {
  background-color: #2563eb;
  color: white;
}

.primary:hover {
  background-color: #1d4ed8;
}

// Button.tsx
import styles from './Button.module.css';

export default function Button({ children, variant = 'primary' }) {
  return (
    <button className={`${styles.button} ${styles[variant]}`}>
      {children}
    </button>
  );
}
```

## Testing

### Component Testing

```typescript
// ExperimentCard.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import ExperimentCard from './ExperimentCard';

describe('ExperimentCard', () => {
  const mockExperiment = {
    id: '1',
    name: 'Test Experiment',
    status: 'ACTIVE',
    startDate: new Date('2024-01-01'),
  };

  it('renders experiment name', () => {
    render(<ExperimentCard experiment={mockExperiment} />);
    expect(screen.getByText('Test Experiment')).toBeInTheDocument();
  });

  it('calls onEdit when edit button clicked', () => {
    const onEdit = jest.fn();
    render(<ExperimentCard experiment={mockExperiment} onEdit={onEdit} />);

    fireEvent.click(screen.getByText('Edit'));
    expect(onEdit).toHaveBeenCalledWith('1');
  });
});
```

### Hook Testing

```typescript
// useExperiments.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { useExperiments } from './useExperiments';
import { ExperimentService } from '@/services/experiments';

jest.mock('@/services/experiments');

describe('useExperiments', () => {
  it('fetches experiments on mount', async () => {
    const mockExperiments = [{ id: '1', name: 'Test' }];
    (ExperimentService.list as jest.Mock).mockResolvedValue(mockExperiments);

    const { result } = renderHook(() => useExperiments());

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.experiments).toEqual(mockExperiments);
    });
  });
});
```

## Performance Optimization

### Code Splitting

```typescript
// Use dynamic imports for heavy components
import dynamic from 'next/dynamic';

const AnalyticsDashboard = dynamic(
  () => import('@/components/analytics/Dashboard'),
  { loading: () => <p>Loading...</p> }
);

export default function AnalyticsPage() {
  return <AnalyticsDashboard />;
}
```

### Memoization

```typescript
import { memo, useMemo, useCallback } from 'react';

// Memo for expensive components
const ExperimentCard = memo(({ experiment }: ExperimentCardProps) => {
  return <div>{experiment.name}</div>;
});

// useMemo for expensive calculations
function ExperimentList({ experiments }) {
  const activeExperiments = useMemo(() => {
    return experiments.filter(exp => exp.status === 'ACTIVE');
  }, [experiments]);

  return <div>{activeExperiments.map(...)}</div>;
}

// useCallback for stable function references
function ExperimentManager() {
  const handleEdit = useCallback((id: string) => {
    console.log('Editing', id);
  }, []);

  return <ExperimentCard onEdit={handleEdit} />;
}
```

## Environment Variables

```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_ANALYTICS_ID=UA-XXXXXXXXX-X

# Access in code
const apiUrl = process.env.NEXT_PUBLIC_API_URL;
```

**Important**: Only variables prefixed with `NEXT_PUBLIC_` are exposed to the browser.

## Common Development Tasks

### Adding New Page

1. Create file in `src/app/[route]/page.tsx`
2. Define component and data fetching
3. Add navigation link in layout/header
4. Add types in `src/types/`
5. Create service methods if needed

### Adding New Component

1. Create component file in appropriate `src/components/` subdirectory
2. Define TypeScript interface for props
3. Implement component logic
4. Add unit tests
5. Update Storybook if using

### Integration with Backend

1. Define TypeScript types matching backend schemas
2. Create service method in `src/services/`
3. Create custom hook for data fetching
4. Use hook in component
5. Handle loading and error states

## Debugging Tips

- Use React DevTools browser extension
- Enable verbose Next.js logging: `DEBUG=* npm run dev`
- Check Network tab for API calls
- Use `console.log` strategically (remove before commit)
- Add error boundaries for graceful error handling

## Resources

- Next.js Docs: https://nextjs.org/docs
- React Docs: https://react.dev
- TypeScript Handbook: https://www.typescriptlang.org/docs/
- Tailwind CSS: https://tailwindcss.com/docs
