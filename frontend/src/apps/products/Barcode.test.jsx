import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Barcode } from './Barcode.jsx';
import { ean13Bars } from './ean13.js';

describe('Barcode', () => {
  it('draws a barcode in a picture that has the code for its name', () => {
    render(<Barcode code="3229820794556" label="Code barre" />);

    const picture = screen.getByRole('img', {
      name: 'Code barre 3229820794556',
    });
    expect(picture.querySelectorAll('rect[fill="#000"]')).toHaveLength(
      ean13Bars('3229820794556').length,
    );
  });

  it('is dark on white whatever the theme, with the margins a scanner needs', () => {
    const { container } = render(<Barcode code="3229820794556" label="Code" />);

    const [background, firstBar] = container.querySelectorAll('rect');
    expect(background).toHaveAttribute('fill', '#fff');
    // The viewBox is the 95 modules of the symbol, 11 before and 7 after.
    expect(container.querySelector('svg')).toHaveAttribute(
      'viewBox',
      expect.stringMatching(/^0 0 113 /),
    );
    expect(Number(firstBar.getAttribute('x'))).toBe(11);
  });

  it('writes the digits under the bars: the first one aside, then six and six', () => {
    const { container } = render(<Barcode code="3229820794556" label="Code" />);

    expect(
      [...container.querySelectorAll('text')].map((text) => text.textContent),
    ).toEqual(['3', '229820', '794556']);
  });

  it('writes a code that would not scan instead of drawing it', () => {
    const { container } = render(<Barcode code="1234567890123" label="Code" />);

    expect(container.querySelector('svg')).toBeNull();
    expect(screen.getByText('1234567890123')).toBeInTheDocument();
  });
});
