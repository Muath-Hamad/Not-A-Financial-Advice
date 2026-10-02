// The prototype's state catalogue (docs/09c HANDOFF §5, canvas.json) for
// the M0 screens. Controls, the confirm modal and the resume preflight
// (M1) and Performance (M2) are added with their milestones.

import type { Meta, StoryObj } from '@storybook/react';
import { resetMockState, type MockState } from '@/mocks/handlers';
import { Frame, type FrameProps } from './Frame';

type Args = FrameProps & { scenario?: Partial<MockState> };

const meta: Meta<Args> = {
  title: 'State catalogue',
  render: ({ scenario: _s, ...frame }) => <Frame {...frame} />,
  loaders: [async ({ args }) => { resetMockState((args as Args).scenario ?? {}); return {}; }],
  args: { path: '/', width: 1440, height: 960 },
};
export default meta;

type Story = StoryObj<Args>;
const desk = (path: string, scenario: Partial<MockState> = {}, extra: Partial<Args> = {}): Story => ({ args: { path, width: 1440, height: 960, scenario, ...extra } });
const phone = (path: string, scenario: Partial<MockState> = {}): Story => ({ args: { path, width: 390, height: 844, scenario } });

export const OverviewDesktop: Story = { ...desk('/'), name: 'Overview · desktop' };
export const HoldingsDrawer: Story = { ...desk('/holdings/TXG'), name: 'Holdings · TXG detail drawer' };
export const OrdersPending: Story = { ...desk('/orders/pending'), name: 'Orders · pending for the next open' };
export const ComplianceCards: Story = { ...desk('/compliance'), name: 'Compliance · holding cards' };
export const Stale: Story = { ...desk('/', { env: 'ghost', health: 'stale' }), name: 'Stale · Cycle A failed 4× (ghost, today)' };
export const StaleHealth: Story = { ...desk('/health', { env: 'ghost', health: 'stale' }), name: 'Stale · Health and data gate' };
export const Loading: Story = { ...desk('/', { loading: true }), name: 'Loading · skeletons' };
export const Empty: Story = { ...desk('/', { health: 'empty' }), name: 'Empty · cold start' };
export const ErrorBroker: Story = { ...desk('/holdings?book=account', { health: 'error' }), name: 'Error · broker unreachable (Account book)' };
export const Light: Story = { ...desk('/', {}, { theme: 'light' }), name: 'Light theme' };
export const Live: Story = { ...desk('/', { env: 'live' }), name: 'LIVE environment' };
export const Tablet: Story = { args: { path: '/', width: 1024, height: 768 }, name: 'Tablet · nav rail' };
export const Paused: Story = { ...desk('/orders/pending', { trading: 'paused' }), name: 'Entries paused (Orders)' };
export const Held: Story = { ...desk('/orders/pending', { trading: 'held' }), name: 'Night held · approval mode (Orders)' };
export const Halted: Story = { ...desk('/', { trading: 'halted' }), name: 'Halted · ROKU 75 vs 74 (Overview)' };
export const Stopped: Story = { ...desk('/orders/pending', { trading: 'stopped' }), name: 'Stopped · kill (Orders)' };
export const Viewer: Story = { ...desk('/holdings', { role: 'viewer' }), name: 'Viewer role · read-only' };
export const ApiDown: Story = { ...desk('/', { apiDown: true }), name: 'Console API unreachable' };
export const PhoneOverview: Story = { ...phone('/'), name: 'Phone · Overview' };
export const PhoneHoldings: Story = { ...phone('/holdings'), name: 'Phone · Holdings' };
export const PhoneDetail: Story = { ...phone('/holdings/ORKA'), name: 'Phone · ORKA detail' };
export const PhoneOrders: Story = { ...phone('/orders/pending'), name: 'Phone · Orders pending' };
