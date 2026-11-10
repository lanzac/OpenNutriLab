import { useState } from 'react';

// The side of the square a product's photo is shown in. The stored photos are small
// (OpenFoodFacts' own sizes), so the browser scales them, none is cut.
const SIZE = 40;

/**
 * A product's photo, or the placeholder, which is also what stands in for a photo
 * that cannot be loaded. The name is beside it, so it has no text of its own.
 */
export function Photo({ src, placeholderImage, size = SIZE }) {
  const [failed, setFailed] = useState(false);
  return (
    <img
      src={failed || !src ? placeholderImage : src}
      alt=""
      width={size}
      height={size}
      className="rounded border bg-white flex-shrink-0"
      style={{ objectFit: 'contain' }}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
