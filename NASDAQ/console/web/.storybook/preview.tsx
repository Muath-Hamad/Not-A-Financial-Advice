import type { Preview } from '@storybook/react';
import { initialize, mswLoader } from 'msw-storybook-addon';
import { handlers } from '../src/mocks/handlers';
import '../src/styles/nafa.css';
import '../src/styles/index.css';

initialize({ onUnhandledRequest: 'bypass', quiet: true });

const preview: Preview = {
  loaders: [mswLoader],
  parameters: {
    layout: 'fullscreen',
    msw: { handlers },
    backgrounds: { disable: true },
  },
};

export default preview;
