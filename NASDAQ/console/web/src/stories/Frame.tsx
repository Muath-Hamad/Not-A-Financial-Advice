// One state-catalogue frame (docs/09c HANDOFF §5): the whole console at a
// fixed size, on a route, with the mock API in one scenario.

import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ConsoleApp, newQueryClient } from '@/app/App';
import type { Theme } from '@/app/console';

export interface FrameProps {
  path: string;
  width: number;
  height: number;
  theme?: Theme;
}

export function Frame({ path, width, height, theme = 'dark' }: FrameProps) {
  const [client] = useState(newQueryClient);
  return (
    <div style={{ width, height, overflow: 'hidden', position: 'relative' }}>
      <MemoryRouter initialEntries={[path]}>
        <ConsoleApp client={client} height={height + 'px'} theme={theme} />
      </MemoryRouter>
    </div>
  );
}
