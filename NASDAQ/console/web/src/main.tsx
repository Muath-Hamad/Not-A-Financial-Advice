import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConsoleApp, newQueryClient } from '@/app/App';
import '@/styles/nafa.css';
import '@/styles/index.css';

const MOCK = import.meta.env.VITE_API_MOCK === '1';

async function boot() {
  if (MOCK) {
    const [{ worker }, { setMockState }] = await Promise.all([import('./mocks/browser'), import('./mocks/handlers')]);
    // Deep-link a scenario: ?mock.env=ghost&mock.data=stale&mock.trading=held&mock.role=viewer
    const q = new URLSearchParams(location.search);
    const data = q.get('mock.data');
    setMockState({
      ...(q.get('mock.env') ? { env: q.get('mock.env') as 'ghost' | 'paper' | 'live' } : {}),
      ...(data === 'loading' ? { loading: true } : data ? { health: data as 'loaded' | 'empty' | 'stale' | 'error' } : {}),
      ...(q.get('mock.trading') ? { trading: q.get('mock.trading') as 'running' } : {}),
      ...(q.get('mock.role') ? { role: q.get('mock.role') as 'owner' | 'viewer' } : {}),
    });
    await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <ConsoleApp client={newQueryClient()} mock={MOCK} />
      </BrowserRouter>
    </StrictMode>,
  );
}

void boot();
