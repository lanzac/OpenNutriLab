import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BarcodeScanner } from './BarcodeScanner.jsx';
import { getDetector } from './detector.js';
import { scanLabels as labels } from './labels.js';

// The reader is a WebAssembly module in the browsers that have none of their
// own: not something to load under test.
vi.mock('./detector.js', () => ({ getDetector: vi.fn() }));

const RICE = '4006381333931';

let track;
let getUserMedia;

function stubCamera() {
  track = { stop: vi.fn() };
  getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [track] });
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
  });
}

// What the reader makes of each frame, until it is told otherwise.
function stubReader(seen) {
  const detect = vi.fn().mockResolvedValue(seen);
  getDetector.mockResolvedValue({ detect });
  return detect;
}

beforeEach(() => {
  stubCamera();
  // jsdom plays no video and has none to read: a frame is always ready.
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4);
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  delete navigator.mediaDevices;
  delete window.isSecureContext;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  getDetector.mockReset();
});

describe('BarcodeScanner, live', () => {
  it('asks for the camera on the back and reports the barcode it reads', async () => {
    stubReader([{ rawValue: RICE }]);
    const onDetect = vi.fn();
    render(<BarcodeScanner labels={labels} onDetect={onDetect} />);

    await waitFor(() => expect(onDetect).toHaveBeenCalledWith(RICE, 'camera'));
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: false,
      video: expect.objectContaining({
        facingMode: { ideal: 'environment' },
      }),
    });
    expect(screen.getByText(labels.scanHint)).toBeInTheDocument();
  });

  it('keeps reading while the barcode is in view', async () => {
    const detect = stubReader([{ rawValue: RICE }]);
    const onDetect = vi.fn();
    render(<BarcodeScanner labels={labels} onDetect={onDetect} />);

    await waitFor(() => expect(onDetect.mock.calls.length).toBeGreaterThan(1));
    expect(detect.mock.calls.length).toBeGreaterThan(1);
  });

  it('says it is starting until the camera runs', async () => {
    stubReader([]);
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(screen.getByText(labels.scanStarting)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(labels.scanStarting)).not.toBeInTheDocument(),
    );
  });

  it('leaves what is not a barcode of a product', async () => {
    const detect = stubReader([
      { rawValue: '4006381333932' }, // wrong check digit
      { rawValue: 'https://example.org' },
    ]);
    const onDetect = vi.fn();
    render(<BarcodeScanner labels={labels} onDetect={onDetect} />);

    await waitFor(() => expect(detect).toHaveBeenCalled());
    expect(onDetect).not.toHaveBeenCalled();
  });

  it('switches the camera off when it is closed', async () => {
    const detect = stubReader([]);
    const { unmount } = render(
      <BarcodeScanner labels={labels} onDetect={vi.fn()} />,
    );
    await waitFor(() => expect(detect).toHaveBeenCalled());

    unmount();

    expect(track.stop).toHaveBeenCalled();
    const calls = detect.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(detect.mock.calls.length).toBeLessThanOrEqual(calls + 1);
  });

  it('switches the camera off if it is closed before the camera came', async () => {
    let allow;
    getUserMedia.mockReturnValue(
      new Promise((resolve) => {
        allow = () => resolve({ getTracks: () => [track] });
      }),
    );
    const { unmount } = render(
      <BarcodeScanner labels={labels} onDetect={vi.fn()} />,
    );

    unmount();
    allow();

    await waitFor(() => expect(track.stop).toHaveBeenCalled());
  });

  it('is not restarted by a new callback', async () => {
    stubReader([]);
    const { rerender } = render(
      <BarcodeScanner labels={labels} onDetect={vi.fn()} />,
    );
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));

    rerender(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(track.stop).not.toHaveBeenCalled();
  });

  it('says when the reader could not be loaded', async () => {
    getDetector.mockRejectedValue(new Error('offline'));
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      labels.scanReaderError,
    );
  });
});

describe('BarcodeScanner, without a live camera', () => {
  it('says the camera is blocked when it was refused, and offers a photo', async () => {
    getUserMedia.mockRejectedValue(
      new DOMException('refused', 'NotAllowedError'),
    );
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      labels.scanCameraDenied,
    );
    // The photo is the action now, not an alternative.
    expect(
      screen.getByRole('button', { name: labels.scanTakePicture }),
    ).toHaveClass('btn-primary');
  });

  it('says the camera could not start for any other failure', async () => {
    getUserMedia.mockRejectedValue(new DOMException('none', 'NotFoundError'));
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      labels.scanCameraFailed,
    );
  });

  it('says a page that is not https cannot have the live camera', async () => {
    // What a phone gets when it opens the dev server by its address.
    delete navigator.mediaDevices;
    window.isSecureContext = false;
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      labels.scanNeedsHttps,
    );
    expect(screen.queryByText(labels.scanStarting)).not.toBeInTheDocument();
  });

  it('does not blame https on a browser that has no camera API', async () => {
    delete navigator.mediaDevices;
    window.isSecureContext = true;
    render(<BarcodeScanner labels={labels} onDetect={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      labels.scanCameraFailed,
    );
  });
});

describe('BarcodeScanner, from a photo', () => {
  const photo = new File(['…'], 'photo.jpg', { type: 'image/jpeg' });

  function stubPicture(width, height) {
    const picture = { width, height, close: vi.fn() };
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn().mockImplementation(async (_source, options) => ({
        width: options?.resizeWidth ?? width,
        height: options?.resizeHeight ?? height,
        close: picture.close,
      })),
    );
    return picture;
  }

  async function takePhoto(onDetect) {
    // No live camera: the photo is the way left.
    delete navigator.mediaDevices;
    window.isSecureContext = false;
    render(<BarcodeScanner labels={labels} onDetect={onDetect} />);
    await screen.findByRole('alert');
    fireEvent.change(screen.getByLabelText(labels.scanTakePicture), {
      target: { files: [photo] },
    });
  }

  it('reports the barcode on the photo', async () => {
    stubPicture(800, 600);
    stubReader([{ rawValue: RICE }]);
    const onDetect = vi.fn();

    await takePhoto(onDetect);

    await waitFor(() => expect(onDetect).toHaveBeenCalledWith(RICE, 'picture'));
  });

  it('says so when there is no barcode on the photo, and keeps the other message', async () => {
    stubPicture(800, 600);
    stubReader([]);
    const onDetect = vi.fn();

    await takePhoto(onDetect);

    await waitFor(() =>
      expect(screen.getByText(labels.scanPictureEmpty)).toBeInTheDocument(),
    );
    expect(onDetect).not.toHaveBeenCalled();
    // The reason there is no live camera is still true.
    expect(screen.getByText(labels.scanNeedsHttps)).toBeInTheDocument();
  });

  it('shrinks a photo of twelve megapixels before it is read', async () => {
    stubPicture(4000, 3000);
    const detect = stubReader([{ rawValue: RICE }]);

    await takePhoto(vi.fn());

    await waitFor(() => expect(detect).toHaveBeenCalled());
    expect(createImageBitmap).toHaveBeenLastCalledWith(
      expect.anything(),
      expect.objectContaining({ resizeWidth: 1600, resizeHeight: 1200 }),
    );
    expect(detect).toHaveBeenCalledWith(
      expect.objectContaining({ width: 1600, height: 1200 }),
    );
  });

  it('reads a small photo as it is', async () => {
    stubPicture(800, 600);
    const detect = stubReader([]);

    await takePhoto(vi.fn());

    await waitFor(() => expect(detect).toHaveBeenCalled());
    expect(createImageBitmap).toHaveBeenCalledTimes(1);
  });

  it('says when the photo could not be read', async () => {
    stubPicture(800, 600);
    getDetector.mockRejectedValue(new Error('offline'));

    await takePhoto(vi.fn());

    await waitFor(() =>
      expect(screen.getByText(labels.scanReaderError)).toBeInTheDocument(),
    );
  });
});
