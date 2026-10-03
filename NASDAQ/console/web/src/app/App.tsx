import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Navigate, Route, Routes } from 'react-router-dom';
import { ConsoleProvider, type Theme } from './console';
import { Shell } from './Shell';
import { Overview } from '@/screens/Overview';
import { Holdings } from '@/screens/Holdings';
import { Orders } from '@/screens/Orders';
import { Compliance } from '@/screens/Compliance';
import { Health } from '@/screens/Health';
import { Roadmap } from '@/screens/Roadmap';
import { More, Settings } from '@/screens/Misc';
import { Performance } from '@/screens/Performance';
import { Controls } from '@/screens/Controls';
import { Agent } from '@/screens/Agent';
import { Alerts } from '@/screens/Alerts';
import { Audit } from '@/screens/Audit';
import { Glossary } from '@/screens/Glossary';

// Mock-mode only, so MSW never ships in the production bundle's main chunk.
const ProtoPanel = lazy(() => import('./ProtoPanel').then((m) => ({ default: m.ProtoPanel })));

export function newQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: true },
    },
  });
}

/** The console inside a router (BrowserRouter in the app, MemoryRouter in stories). */
export function ConsoleApp({ client, height, theme, mock = false }: { client: QueryClient; height?: string; theme?: Theme; mock?: boolean }) {
  const overlay = mock ? <Suspense fallback={null}><ProtoPanel /></Suspense> : null;
  return (
    <QueryClientProvider client={client}>
      <ConsoleProvider initialTheme={theme}>
        <Routes>
          <Route element={<Shell height={height} overlay={overlay} />}>
            <Route index element={<Overview />} />
            <Route path="holdings" element={<Holdings />} />
            <Route path="holdings/:sym" element={<Holdings />} />
            <Route path="orders" element={<Orders />} />
            <Route path="orders/:tab" element={<Orders />} />
            <Route path="compliance" element={<Compliance />} />
            <Route path="compliance/:tab" element={<Compliance />} />
            <Route path="health" element={<Health />} />
            <Route path="roadmap" element={<Roadmap />} />
            <Route path="glossary" element={<Glossary />} />
            <Route path="settings" element={<Settings />} />
            <Route path="more" element={<More />} />
            <Route path="performance/*" element={<Performance />} />
            <Route path="controls" element={<Controls />} />
            <Route path="agent" element={<Agent />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="audit" element={<Audit />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </ConsoleProvider>
    </QueryClientProvider>
  );
}
