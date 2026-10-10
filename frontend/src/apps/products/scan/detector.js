// The reader of barcodes the scanner uses: the browser's own where it has one
// (Chrome on Android reads through Google's, which is quick and copes with poor
// light), a WebAssembly one where it has none (Safari, Firefox), which is not
// downloaded until a browser needs it.
import wasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url';

// What a product is known by: EAN-13, and UPC-A, an EAN-13 that starts with 0.
const FORMATS = ['ean_13', 'upc_a'];

async function createDetector() {
  const Native = globalThis.BarcodeDetector;
  if (Native) {
    const formats = (await Native.getSupportedFormats()).filter((format) =>
      FORMATS.includes(format),
    );
    if (formats.includes('ean_13')) return new Native({ formats });
  }

  const { BarcodeDetector, prepareZXingModule } =
    await import('barcode-detector/ponyfill');
  // The library fetches its .wasm from a CDN unless told where it is: it is
  // served with the rest of the site instead (nothing leaves for a third
  // party, and the reader works offline once the page is cached).
  prepareZXingModule({
    overrides: {
      locateFile: (path, prefix) =>
        path.endsWith('.wasm') ? wasmUrl : prefix + path,
    },
  });
  return new BarcodeDetector({ formats: FORMATS });
}

let detector = null;

/**
 * The detector, made once for the page: a second one would load the reader a
 * second time. A failure is not kept, so that opening the scanner again tries
 * again.
 *
 * @returns {Promise<{ detect: (image: CanvasImageSource) => Promise<{ rawValue: string }[]> }>}
 */
export function getDetector() {
  detector ??= createDetector().catch((error) => {
    detector = null;
    throw error;
  });
  return detector;
}
