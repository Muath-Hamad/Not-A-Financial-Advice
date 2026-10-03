import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

/** Match an element whose own full text is `t`, even when glossary terms split it into spans. */
const fullText = (t: string | RegExp) => (_: string, el: Element | null) => {
  if (!el) return false;
  const txt = el.textContent ?? '';
  const ok = typeof t === 'string' ? txt === t : t.test(txt);
  return ok && Array.from(el.children).every((ch) => !(typeof t === 'string' ? ch.textContent === t : t.test(ch.textContent ?? '')));
};

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
    expect(await screen.findByText(fullText(/^ORKA 0.4 ATR above its initial stop/))).toBeInTheDocument();
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
    expect(await screen.findByText(fullText(/^Cycle A has failed 4 sessions in a row/))).toBeInTheDocument();
    expect(await screen.findByText('Stalled — 4 failed sessions')).toBeInTheDocument();
    expect(screen.getByText('GHOST')).toBeInTheDocument();
  });

  it('renders compliance cards with grades', async () => {
    mount('/compliance');
    expect(await screen.findByText('Under review')).toBeInTheDocument();
    expect(screen.getAllByTitle('Sharia grade A').length).toBeGreaterThan(0);
  });

  it('explains a term on hover', async () => {
    mount('/');
    const term = (await screen.findAllByText('Drawdown from peak'))[0];
    term.focus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('How far the portfolio has fallen from its highest value');
  });

  it('lists every term on the glossary page', async () => {
    mount('/glossary');
    expect(await screen.findByRole('heading', { name: 'Glossary' })).toBeInTheDocument();
    expect(screen.getByText('ATR — Average True Range')).toBeInTheDocument();
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

describe('console M1–M3 screens', () => {
  it('runs STOP through impact → reason → verify → result and reaches the audit log', async () => {
    const user = userEvent.setup();
    mount('/controls');
    await user.click(await screen.findByRole('button', { name: 'STOP TRADING' }));
    const dlg = await screen.findByRole('dialog', { name: 'STOP TRADING' });
    expect(await within(dlg).findByText('Orders canceled · 3')).toBeInTheDocument();
    await user.click(within(dlg).getByRole('button', { name: 'Continue' }));
    await user.type(within(dlg).getByLabelText(/Reason/), 'Broker anomaly: unexpected open orders');
    await user.click(within(dlg).getByRole('button', { name: 'Continue' }));
    const go = within(dlg).getByRole('button', { name: 'STOP TRADING' });
    expect(go).toBeDisabled();
    await user.type(within(dlg).getByLabelText(/Authenticator code/), '123456');
    await user.type(within(dlg).getByLabelText(/Type/), 'STOP');
    await user.click(go);
    expect(await within(dlg).findByText('Applied', {}, { timeout: 3000 })).toBeInTheDocument();
    await user.click(within(dlg).getByRole('button', { name: 'Done' }));
    expect(await screen.findByText('STOPPED')).toBeInTheDocument();
  });

  it('says "Not applied" when a step fails', async () => {
    const user = userEvent.setup();
    mount('/controls', { failApply: true });
    await user.click(await screen.findByRole('button', { name: 'Pause entries' }));
    const dlg = await screen.findByRole('dialog', { name: 'Pause entries' });
    await user.click(await within(dlg).findByRole('button', { name: 'Continue' }));
    await user.type(within(dlg).getByLabelText(/Reason/), 'FOMC tomorrow; no new risk');
    await user.click(within(dlg).getByRole('button', { name: 'Continue' }));
    await user.type(within(dlg).getByLabelText(/Authenticator code/), '123456');
    await user.click(within(dlg).getByRole('button', { name: 'Pause entries' }));
    expect(await within(dlg).findByText('Not applied', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('gates resume on the preflight checklist', async () => {
    const user = userEvent.setup();
    mount('/controls', { trading: 'stopped' });
    await user.click(await screen.findByRole('button', { name: 'Resume trading…' }));
    const dlg = await screen.findByRole('dialog', { name: 'Resume preflight checklist' });
    const next = await within(dlg).findByRole('button', { name: 'Continue to confirm' });
    expect(next).toBeDisabled();
    await user.click(await within(dlg).findByRole('button', { name: /^Tick: Acknowledge/ }));
    await waitFor(() => expect(next).toBeEnabled());
  });

  it('asks for a sign-in when the session is missing', async () => {
    mount('/', { signedOut: true });
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeDisabled();
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
  });

  it('renders Performance metrics against the OOS reference and the execution tab', async () => {
    mount('/performance');
    expect(await screen.findByText(fullText('Sharpe'))).toBeInTheDocument();
    expect(screen.getByText('1.22')).toBeInTheDocument();
    mount('/performance/execution');
    expect(await screen.findByText('3.1 bps')).toBeInTheDocument();
  });

  it('shows Agent calibration from the OOS record', async () => {
    mount('/agent');
    expect(await screen.findByText('68%')).toBeInTheDocument();
    expect(screen.getByText('EXP_MAX')).toBeInTheDocument();
  });

  it('resolves an alert with a note', async () => {
    const user = userEvent.setup();
    mount('/alerts');
    const first = (await screen.findAllByRole('button', { name: 'Resolve…' }))[0];
    await user.click(first);
    await user.type(screen.getByLabelText('Resolution note'), 'Known and fixed');
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(await screen.findByText(/resolved$/)).toBeInTheDocument();
  });

  it('lists control changes in the audit log', async () => {
    mount('/audit');
    expect(await screen.findByText('Universe correction')).toBeInTheDocument();
    expect(screen.getByText('Sign-ins')).toBeInTheDocument();
  });
});
