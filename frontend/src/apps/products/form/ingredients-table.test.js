import { describe, expect, it } from 'vitest';

import { ciqualCell } from './ingredients-table.js';

describe('ciqualCell', () => {
  it('links the code to its sheet on the CIQUAL site', () => {
    const link = ciqualCell(
      '9410 (proxy)',
      'https://ciqual.anses.fr/#/aliments/9410',
    );

    expect(link.tagName).toBe('A');
    expect(link.textContent).toBe('9410 (proxy)');
    expect(link.href).toBe('https://ciqual.anses.fr/#/aliments/9410');
    expect(link.target).toBe('_blank');
    expect(link.rel).toBe('noopener noreferrer');
  });

  it('shows nothing for an ingredient without a code', () => {
    expect(ciqualCell('', null)).toBe('');
    expect(ciqualCell(undefined, undefined)).toBe('');
  });

  it('shows several codes as text, since one link would pass for them all', () => {
    const cell = ciqualCell('9311, 20009', null);

    expect(cell.tagName).toBe('SPAN');
    expect(cell.textContent).toBe('9311, 20009');
  });

  it('never reads a code as HTML', () => {
    const link = ciqualCell(
      '<img src=x onerror=alert(1)>',
      'https://ciqual.anses.fr/#/aliments/1',
    );

    expect(link.children).toHaveLength(0);
    expect(link.textContent).toBe('<img src=x onerror=alert(1)>');
  });

  it('never reads a code as HTML when there is no link either', () => {
    const cell = ciqualCell('<img src=x onerror=alert(1)>', null);

    expect(cell.children).toHaveLength(0);
    expect(cell.textContent).toBe('<img src=x onerror=alert(1)>');
  });
});
