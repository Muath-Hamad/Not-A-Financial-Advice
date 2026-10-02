import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { handlers, resetMockState, type MockState } from '@/mocks/handlers';
import { ConsoleApp, newQueryClient } from './App';

// jsdom has no canvas: stub the ECharts host.
vi.mock('@/components/charts/Chart', () => ({
  Chart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
  useChartTokens: () => [{ current: null }, null],
}));

const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(path: string, scenario: Partial<MockState> = {}) {
  resetMockState(scenario);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ConsoleApp client={newQueryClient()} height="960px" theme="dark" />
    </MemoryRouter>,
  );
}

describe('console M0 screens', () => {
  it('renders the Overview KPIs and attention list', async () => {
    mount('/');
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument();
    expect(await screen.findAllByText('$90,407.14')).not.toHaveLength(0);
    expect(await screen.findByText('ORKA 0.4 ATR above its initial stop')).toBeInTheDocument();
    expect(screen.getByText('PAPER')).toBeInTheDocument();
  });

  it('opens the holding drawer from the route', async () => {
    mount('/holdings/TXG');
    const drawer = await screen.findByRole('complementary', { name: 'Holding detail · TXG' });
    expect(within(drawer).getAllByText('+$2,925.45').length).toBeGreaterThanOrEqual(2);
    expect(within(drawer).getByText('Model conviction, not a forecast.')).toBeInTheDocument();
    expect(within(drawer).getAllByText('Not available – licensed data pending')).not.toHaveLength(0);
  });

  it('shows the blocked CELC order on Pending', async () => {
    mount('/orders/pending');
    expect(await screen.findAllByText('CELC')).not.toHaveLength(0);
    expect(screen.getAllByText('adv_cap').length).toBeGreaterThan(0);
    expect(screen.getByText('4 intents · 3 to send · 1 blocked or canceled')).toBeInTheDocument();
  });

  it('raises the stale banner and the tripped data gate in Ghost', async () => {
    mount('/health', { env: 'ghost', health: 'stale' });
    expect(await screen.findByText(/Cycle A has failed 4 sessions in a row/)).toBeInTheDocument();
    expect(await screen.findByText('Stalled — 4 failed sessions')).toBeInTheDocument();
    expect(screen.getByText('GHOST')).toBeInTheDocument();
  });

  it('renders compliance cards with grades', async () => {
    mount('/compliance');
    expect(await screen.findByText('Under review')).toBeInTheDocument();
    expect(screen.getAllByTitle('Sharia grade A').length).toBeGreaterThan(0);
  });

  it('renders the roadmap decisions', async () => {
    mount('/roadmap');
    expect(await screen.findByText('Sharia policy in writing')).toBeInTheDocument();
  });

  it('hides Controls and row overrides from a viewer', async () => {
    mount('/holdings', { role: 'viewer' });
    await screen.findByRole('heading', { name: 'Holdings' });
    const nav = screen.getAllByRole('navigation', { name: 'Primary' })[0];
    expect(within(nav).queryByTitle('Controls')).toBeNull();
    expect(screen.queryByLabelText(/Overrides for/)).toBeNull();
  });

  it('shows the cold-start empty state', async () => {
    mount('/', { health: 'empty' });
    expect(await screen.findByText('Nothing to show yet')).toBeInTheDocument();
  });

  it('says so when the console API is down', async () => {
    mount('/', { apiDown: true });
    expect(await screen.findByText('Console API unreachable.', {}, { timeout: 4000 })).toBeInTheDocument();
  });
});
