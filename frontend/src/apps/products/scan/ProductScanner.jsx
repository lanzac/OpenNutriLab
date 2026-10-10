import { useEffect, useRef, useState } from 'react';

import { fill } from '../../../shared/format.js';
import { setInInventory } from '../api/client.js';
import { BarcodeScanner } from './BarcodeScanner.jsx';

// A barcode that stays in view of the camera is seen many times a second. It is
// acted on once, and again only after it has been out of view for this long. A
// photo is never taken for such a repeat: someone took it to be answered.
const REPEAT_AFTER_MS = 4000;

// How many of the last scans are shown.
const SHOWN = 5;

// Django's create view reads ?barcode= and asks OpenFoodFacts for the rest (see
// ProductCreateView).
const productCreateUrl = (barcode) =>
  `/products/new/?barcode=${encodeURIComponent(barcode)}`;

/**
 * Scanning products into the inventory: the camera, and under it what became
 * of each barcode it read. A product of the catalogue goes into the inventory
 * and the camera stays on for the next one; one the catalogue does not have is
 * offered to be created, which the create page does from OpenFoodFacts.
 *
 * @param {object} props
 * @param {object[]} props.products The catalogue, as the list fetched it.
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.csrfToken For the writes to the inventory.
 * @param {(barcode: string) => void} props.onAdded Told of each product put in
 *   the inventory, so that the list shows it.
 * @param {() => void} props.onClose
 */
export function ProductScanner({
  products,
  labels,
  csrfToken,
  onAdded,
  onClose,
}) {
  const [scans, setScans] = useState([]);
  // The latest catalogue: the camera calls back with what it was given when it
  // started, and a product added a moment ago must be seen as added.
  const productsRef = useRef(products);
  const lastSeen = useRef({ barcode: null, at: 0 });
  const nextId = useRef(0);

  useEffect(() => {
    productsRef.current = products;
  });

  const record = (scan) =>
    setScans((current) =>
      [{ ...scan, id: nextId.current++ }, ...current].slice(0, SHOWN),
    );

  function handleDetect(barcode, source) {
    const now = Date.now();
    const repeat =
      source === 'camera' &&
      lastSeen.current.barcode === barcode &&
      now - lastSeen.current.at < REPEAT_AFTER_MS;
    lastSeen.current = { barcode, at: now };
    if (repeat) return;

    // A buzz for a barcode read, for a person who is looking at the packaging.
    navigator.vibrate?.(60);

    const product = productsRef.current.find((p) => p.barcode === barcode);
    if (!product) {
      record({ kind: 'unknown', barcode });
    } else if (product.in_inventory) {
      record({ kind: 'already', barcode, name: product.name });
    } else {
      setInInventory(barcode, true, csrfToken)
        .then(() => {
          onAdded(barcode);
          record({ kind: 'added', barcode, name: product.name });
        })
        .catch((error) => {
          console.error(error);
          record({ kind: 'error', barcode, name: product.name });
        });
    }
  }

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
          <h2 className="h6 mb-0">{labels.scanProduct}</h2>
          <button
            type="button"
            className="btn-close"
            aria-label={labels.scanClose}
            onClick={onClose}
          />
        </div>
        <BarcodeScanner labels={labels} onDetect={handleDetect} />
        {scans.length > 0 && (
          <ul className="list-group list-group-flush mt-3" aria-live="polite">
            {scans.map((scan) => (
              <ScanResult key={scan.id} scan={scan} labels={labels} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const RESULTS = {
  added: { icon: 'fa-check text-success', text: 'scanAdded' },
  already: { icon: 'fa-circle-info text-body-secondary', text: 'scanAlready' },
  unknown: { icon: 'fa-circle-question text-warning', text: 'scanUnknown' },
  error: {
    icon: 'fa-triangle-exclamation text-danger',
    text: 'inventoryError',
  },
};

function ScanResult({ scan, labels }) {
  const { icon, text } = RESULTS[scan.kind];
  return (
    <li className="list-group-item d-flex align-items-center gap-2 px-0">
      <i className={`fa-solid ${icon}`} aria-hidden="true" />
      <span className="flex-grow-1">
        {fill(labels[text], { name: scan.name ?? '', barcode: scan.barcode })}
      </span>
      {scan.kind === 'unknown' && (
        <a
          className="btn btn-sm btn-primary text-nowrap"
          href={productCreateUrl(scan.barcode)}
        >
          {labels.scanCreate}
        </a>
      )}
    </li>
  );
}
