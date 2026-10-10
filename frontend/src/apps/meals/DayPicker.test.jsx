import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DayPicker } from './DayPicker.jsx';
import { DAY_URL, day, ok, renderApp, stubFetch } from './fixtures.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const labels = {
  day: 'Jour',
  dateHint: 'jj/mm/aaaa',
  chooseDay: 'Choisir un jour dans un calendrier',
};

const show = (props = {}) => {
  const onChange = vi.fn();
  render(
    <DayPicker
      day="2026-10-09"
      onChange={onChange}
      labels={labels}
      languageCode="fr-fr"
      {...props}
    />,
  );
  return { onChange, field: screen.getByLabelText('Jour') };
};

describe('the day picker', () => {
  it('writes the day with the day first in French, whatever the browser does', () => {
    const { field } = show();

    expect(field).toHaveValue('09/10/2026');
    expect(field).toHaveAttribute('placeholder', 'jj/mm/aaaa');
  });

  it('writes it as English does in English', () => {
    const { field } = show({ languageCode: 'en-us' });

    expect(field).toHaveValue('10/09/2026');
  });

  it('takes a day typed in the order of the language, when the field is left', () => {
    const { onChange, field } = show();

    fireEvent.change(field, { target: { value: '12/10/2026' } });
    // Nothing happens while it is typed.
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(field);

    expect(onChange).toHaveBeenCalledWith('2026-10-12');
  });

  it('takes it with Enter too', () => {
    const { onChange, field } = show();

    fireEvent.change(field, { target: { value: '01/11/2026' } });
    fireEvent.keyDown(field, { key: 'Enter' });

    expect(onChange).toHaveBeenCalledWith('2026-11-01');
  });

  it('goes back to the day it has when what is typed is no day', () => {
    const { onChange, field } = show();

    fireEvent.change(field, { target: { value: '31/06/2026' } });
    fireEvent.blur(field);

    expect(onChange).not.toHaveBeenCalled();
    expect(field).toHaveValue('09/10/2026');
  });

  it('does not change the day for the day it already is', () => {
    const { onChange, field } = show();

    fireEvent.change(field, { target: { value: '9.10.26' } });
    fireEvent.blur(field);

    expect(onChange).not.toHaveBeenCalled();
    expect(field).toHaveValue('09/10/2026');
  });

  it('opens the browser’s calendar from its button and takes the day chosen in it', () => {
    const { onChange } = show();
    const calendar = document.querySelector('input[type="date"]');
    calendar.showPicker = vi.fn();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Choisir un jour dans un calendrier',
      }),
    );
    expect(calendar.showPicker).toHaveBeenCalledOnce();
    fireEvent.change(calendar, { target: { value: '2026-12-25' } });

    expect(onChange).toHaveBeenCalledWith('2026-12-25');
  });

  it('works where the browser cannot open its calendar from a script', () => {
    show();

    expect(() =>
      fireEvent.click(
        screen.getByRole('button', {
          name: 'Choisir un jour dans un calendrier',
        }),
      ),
    ).not.toThrow();
  });

  it('loads the day typed in the page', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/meals/2026-10-12': ok(day({ day: '2026-10-12' })),
      'GET /api/v1/inventory/': ok([]),
    });
    renderApp();
    const field = await screen.findByLabelText('Jour');

    fireEvent.change(field, { target: { value: '12/10/2026' } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/v1/meals/2026-10-12',
        expect.anything(),
      ),
    );
    expect(await screen.findByLabelText('Jour')).toHaveValue('12/10/2026');
  });
});
